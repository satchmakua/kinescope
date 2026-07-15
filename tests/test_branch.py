"""Branching: fork@k overrides one event, the tail goes live, lineage is recorded, and
the child run is itself replayable and forkable (DESIGN.md §6.3)."""

from __future__ import annotations

import httpx
import pytest

import kinescope
from kinescope.store.local import LocalStore


def _make_agent(reading):
    @kinescope.tool
    def sensor(city):
        return reading["v"]

    @kinescope.tool
    def classify(temp):
        return "cold" if temp < 50 else "warm"

    def agent():
        temp = sensor("Paris")
        return {"temp": temp, "verdict": classify(temp)}

    return agent


def test_fork_overrides_one_event_and_runs_tail_live(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    agent = _make_agent({"v": 30})

    with kinescope.record("w", store=store) as rec:
        base = agent()
    assert base == {"temp": 30, "verdict": "cold"}

    with kinescope.fork(rec.run_id, at=0, override={"output": 72}, store=store) as br:
        branched = agent()

    assert branched == {"temp": 72, "verdict": "warm"}  # override + live re-classify
    assert br.divergences == []

    child = store.get_run(br.run_id)
    assert child.parent_run_id == rec.run_id and child.forked_at_seq == 0

    events = store.events(br.run_id)
    assert len(events) == 2
    assert events[0].meta.get("overridden") is True  # the swapped fork point
    assert events[1].name == "classify"  # re-recorded live


def test_branch_is_itself_replayable(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    agent = _make_agent({"v": 30})

    with kinescope.record("w", store=store) as rec:
        agent()
    with kinescope.fork(rec.run_id, at=0, override={"output": 72}, store=store) as br:
        branched = agent()
    child_id = br.run_id

    with kinescope.replay(child_id, store=store) as rep:
        replayed = agent()

    assert replayed == branched == {"temp": 72, "verdict": "warm"}
    assert rep.divergences == []


def test_fork_preserves_deterministic_prefix(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def step(n):
        return n * 10

    def agent():
        a = step(1)
        b = step(2)  # fork here
        c = step(3)
        return [a, b, c]

    with kinescope.record("p", store=store) as rec:
        assert agent() == [10, 20, 30]

    # Override step(2)'s output (seq 1) from 20 → 999; seq 0 stays, seq 2 re-runs live.
    with kinescope.fork(rec.run_id, at=1, override={"output": 999}, store=store) as br:
        result = agent()

    assert result == [10, 999, 30]
    assert br.divergences == []
    events = store.events(br.run_id)
    assert [e.meta.get("overridden", False) for e in events] == [False, True, False]


def test_fork_out_of_range_raises(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def only():
        return 1

    with kinescope.record("x", store=store) as rec:
        only()

    with pytest.raises(ValueError):
        with kinescope.fork(rec.run_id, at=5, override={"output": 0}, store=store):
            only()


def test_fork_overrides_an_llm_response(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda r: httpx.Response(200, json={"answer": "original"}))

    def call():
        client = kinescope.http_client(inner=canned)
        return client.get("https://api.anthropic.com/v1/messages").json()

    with kinescope.record("llm", store=store) as rec:
        assert call() == {"answer": "original"}

    forbidden = httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(AssertionError("should not call out at fork point"))
    )

    def call_forked():
        client = kinescope.http_client(inner=forbidden)
        return client.get("https://api.anthropic.com/v1/messages").json()

    with kinescope.fork(rec.run_id, at=0, override={"output": {"answer": "forced"}}, store=store):
        result = call_forked()

    assert result == {"answer": "forced"}
