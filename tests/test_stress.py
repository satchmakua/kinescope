"""H2 — the determinism stress suite. The product *is* correctness-of-replay, so test it
adversarially: async ordering, concurrency, hidden nondeterminism the detector MUST flag,
a randomized property check, and a ≥10k-event scale/throughput run.
"""

from __future__ import annotations

import asyncio
import random
import time as _time
from time import perf_counter

import httpx

import kinescope
from kinescope.store.local import LocalStore


@kinescope.tool
def _bump(n: int) -> int:
    return n + 1


# --- async ordering ---------------------------------------------------------


def _canned(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"u": str(request.url)})


def test_sequential_async_boundaries_replay_deterministically(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    async def run(inner):
        client = kinescope.async_http_client(inner=inner)
        try:
            return [
                (await client.get(f"https://api.anthropic.com/m?i={i}")).json() for i in range(5)
            ]
        finally:
            await client.aclose()

    async def do_record():
        with kinescope.record("seq", store=store) as rec:
            out = await run(httpx.MockTransport(_canned))
        return rec.run_id, out

    run_id, out1 = asyncio.run(do_record())

    async def do_replay():
        with kinescope.replay(run_id, store=store) as rep:
            out = await run(httpx.MockTransport(_canned))
        return out, list(rep.divergences)

    out2, divergences = asyncio.run(do_replay())
    assert out1 == out2 and divergences == []


def test_concurrent_async_is_never_silently_wrong(tmp_path):
    """Concurrent boundaries (asyncio.gather) may reorder vs. the recording. The contract is
    that replay is then EITHER identical OR flagged — never silently wrong."""
    store = LocalStore(tmp_path / ".kinescope")

    async def run(inner):
        client = kinescope.async_http_client(inner=inner)

        async def one(i):
            return (await client.get(f"https://api.anthropic.com/c?i={i}")).json()

        try:
            return await asyncio.gather(*(one(i) for i in range(6)))
        finally:
            await client.aclose()

    async def do_record():
        with kinescope.record("conc", store=store) as rec:
            out = await run(httpx.MockTransport(_canned))
        return rec.run_id, out

    run_id, recorded = asyncio.run(do_record())

    async def do_replay():
        with kinescope.replay(run_id, store=store) as rep:
            out = await run(httpx.MockTransport(_canned))
        return out, list(rep.divergences)

    replayed, divergences = asyncio.run(do_replay())
    assert replayed == recorded or divergences  # invariant: never wrong AND silent


def test_boundary_reordering_is_flagged(tmp_path):
    """If boundaries are reordered between record and replay (the concurrency hazard),
    the divergence detector catches it via input-hash mismatch."""
    store = LocalStore(tmp_path / ".kinescope")

    def fire(order):
        client = kinescope.http_client(inner=httpx.MockTransport(_canned))
        return [client.get(f"https://api.anthropic.com/r?i={i}").json() for i in order]

    with kinescope.record("order", store=store) as rec:
        fire([0, 1, 2])
    with kinescope.replay(rec.run_id, store=store) as rep:
        fire([2, 1, 0])  # reordered

    assert any(d["reason"] == "input-mismatch" for d in rep.divergences)


# --- hidden nondeterminism the detector MUST flag ---------------------------


def test_hidden_nondeterminism_is_flagged(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    source = {"v": 0}  # stands in for an un-captured nondeterministic input

    @kinescope.tool
    def use(x):
        return x * 2

    def agent():
        return use(source["v"])

    with kinescope.record("hidden", store=store) as rec:
        agent()  # use(0)
    source["v"] = 99  # the input changed out from under replay

    with kinescope.replay(rec.run_id, store=store) as rep:
        agent()  # use(99) → input hash differs

    assert rep.divergences and rep.divergences[0]["reason"] == "input-mismatch"


# --- property: any deterministic agent replays faithfully -------------------


def _build_agent(seed: int):
    spec = random.Random(seed)  # builds the agent shape; NOT a captured boundary
    ops = [spec.choice(["rng", "clock", "tool"]) for _ in range(spec.randint(5, 30))]

    def run():
        out = []
        for op in ops:
            if op == "rng":
                out.append(random.random())  # module-level → captured under capture="all"
            elif op == "clock":
                out.append(_time.time())  # captured
            else:
                out.append(_bump(len(out)))  # tool boundary
        return out

    return run


def test_random_deterministic_agents_replay_faithfully(tmp_path):
    for seed in range(25):
        store = LocalStore(tmp_path / f"run{seed}")
        agent = _build_agent(seed)
        with kinescope.record(f"prop{seed}", store=store, capture="all") as rec:
            first = agent()
        with kinescope.replay(rec.run_id, store=store) as rep:
            second = agent()
        assert first == second, f"seed {seed} diverged in values"
        assert rep.divergences == [], f"seed {seed} reported divergences"


# --- scale / throughput -----------------------------------------------------


def test_large_trace_scale_and_throughput(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    n = 10_000

    t0 = perf_counter()
    with kinescope.record("scale", store=store, capture=["rng"]) as rec:
        recorded = [random.random() for _ in range(n)]
    record_s = perf_counter() - t0

    t0 = perf_counter()
    with kinescope.replay(rec.run_id, store=store) as rep:
        replayed = [random.random() for _ in range(n)]
    replay_s = perf_counter() - t0

    assert recorded == replayed  # 10k boundaries reproduced exactly
    assert rep.divergences == []
    assert len(store.events(rec.run_id)) == n
    assert record_s < 20 and replay_s < 10  # generous bounds; typically well under 1s each
    print(f"\nscale {n}: record {record_s:.2f}s ({n / record_s:,.0f}/s), "
          f"replay {replay_s:.2f}s ({n / replay_s:,.0f}/s)")


# --- documented limitation: thread-scoped capture ---------------------------


def test_worker_thread_boundaries_are_not_captured(tmp_path):
    """Known limit (pinned, not a surprise): the active session is contextvar-scoped, so
    boundaries on worker threads that don't inherit the context are NOT captured — and the
    divergence detector can't see what never entered the seq stream. Record on one
    thread/async-context per run, or propagate the context explicitly."""
    import concurrent.futures as cf

    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def work(n):
        return n * n

    with kinescope.record("threads", store=store) as rec:
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(work, range(4)))  # NOT captured (worker threads lack the session)
        work(99)  # captured (runs on the recording thread)

    assert len(store.events(rec.run_id)) == 1  # only the on-thread call entered the log
