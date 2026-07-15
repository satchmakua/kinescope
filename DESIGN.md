# Kinescope — Design

> `rr` for nondeterministic AI agents: capture every nondeterministic input so any run replays deterministically — and can be *branched*: "what if the model had picked the other tool here?"

**Status:** Design draft · **Language:** Python 3.11+ · **Stack target:** local-first library + CLI/TUI (cross-platform)

Name: **Kinescope** (kinescope memory = perfect total recall). Working codename — rename freely; the word is generic English and carries no usable trademark for dev tools, but do a quick PyPI/name check before publishing the package.

> **Privacy / secrets note (read first).** Kinescope records the full request/response of every LLM and tool call, which routinely contains API keys, auth headers, user PII, and proprietary prompts. Redaction is therefore a *core feature, not an afterthought*: Kinescope strips credential headers (`authorization`, `x-api-key`, `anthropic-*` auth) **by default** and exposes a scrubber hook for payload fields. Traces are local files by default; nothing leaves the machine unless the user exports it. See §6.6.

---

## 1. Concept

Debugging an agent today is archaeology through logs, made worse by nondeterminism: sampled model outputs, flaky tools, wall-clock and RNG drift. You cannot reliably reproduce the failure, so you cannot reliably fix it.

Kinescope is the systems answer. It sits at the **nondeterministic frontier** of an agent — the handful of places where the same code can produce different results: LLM calls, tool calls, the clock, the RNG/UUIDs, retrieval — and records the *output* of every crossing into an ordered event log plus periodic state snapshots. From that trace it can:

- **Replay** the run deterministically, feeding recorded outputs back instead of calling out, so the failure reproduces every time;
- **Branch** at any step *k*: override exactly one recorded event (swap a tool result, force a different completion), replay up to *k*, then **switch to live** execution for everything after — exploring the counterfactual path;
- **Scrub** the timeline in a terminal UI, inspecting each step's messages, tool I/O, and the JSON **diff** of agent state, with a one-key **fork**.

The thing a reader should "see": an agent fails a task; you `kinescope ui` the recorded run, scrub to step 7 where it called the wrong tool, hit **fork**, override that one tool result, and watch the branched run complete successfully — fully reproducible from the trace. That fork-and-fix is the entire pitch.

### Engineering pillars (the 1–3 things that make or break this)

1. **Transparent, total interception of the nondeterministic frontier.** Capture LLM (incl. **SSE streaming** and **async**), tools, clock, RNG/UUID — with a single global **sequence order** across all of them — *without the user rewriting their agent*. Get this wrong and replays drift. Approach: an **httpx transport shim** for HTTP boundaries (robust to SDK versions), a scoped **monkeypatch** for stdlib nondeterminism, and a **decorator/registry wrap** for tools — all funneling into one ordered log. (§4, §6.1)
2. **Replay→live branching with honest divergence detection.** Replaying to *k* bit-for-bit, overriding one event, then *resuming live* while the recorder keeps capturing the new tail — and **detecting hidden nondeterminism** that escapes the shims instead of silently lying about determinism. (§6.3, §6.4)
3. **State capture & diffing of document-shaped state at run length.** Content-addressed, deduplicated snapshots and lazy structural diffs so the timeline scrubs instantly even on long runs. (§6.5)

---

## 2. Goals / Non-goals

**Goals (v1 — each is testable):**

- Record a single-process agent's LLM + tool + clock + RNG/UUID boundaries to a local trace with **zero changes to agent logic** beyond wrapping it in a context manager and decorating tools.
- **Byte-stable deterministic replay**: a replayed run makes the identical sequence of boundary calls with identical inputs; any deviation is reported as a *divergence*, not hidden.
- Support both **sync and async**, and both **non-streaming and SSE-streaming** Anthropic Messages calls.
- **Branch** at step *k* with a single-event override and a clean replay→live handoff, producing a new child run linked to its parent.
- A **Textual TUI** to scrub steps and view message/tool I/O and state diffs, with fork.
- **Local-first, low-friction**: the recording core has a tiny dependency footprint (essentially `httpx`); storage is a `.kinescope/` dir (SQLite index + content-addressed blobs) with no external services.
- A provider-agnostic event schema (Anthropic adapter shipped) aligned with **OpenTelemetry GenAI** vocabulary so a second adapter and OTel export are cheap.

**Non-goals (v1) — deliberately out, with the "when":**

- **Reproducing provider-side sampling internals.** We record *outputs*; we never try to re-derive a completion from a seed/temperature. Determinism is at the *boundary*, by construction.
- **Distributed / multi-process / many-agent orchestration.** Single agent, single process first. Multi-process record-replay (shared clock/order across processes) is a hard future milestone.
- **Automatic root-cause analysis.** Kinescope gives you the deterministic substrate and the fork; it does not diagnose for you (an LLM-judge "explain this divergence" feature is a stretch).
- **A hosted SaaS / web dashboard.** CLI + TUI first; a web timeline is a stretch goal (§8 M5), not v1.
- **Framework-level instrumentation (LangGraph/CrewAI nodes).** We intercept at the SDK/HTTP boundary, which works *under* any framework. First-class framework adapters come later if demand appears.
- **Non-HTTP tool nondeterminism we can't see.** Tools that read files, hit databases via non-HTTP drivers, or spawn subprocesses are captured only via the `@kinescope.tool` wrapper; un-wrapped side effects are surfaced by the divergence detector, not magically captured.
- **Editing more than one event per fork in v1.** Single-event override keeps the counterfactual causal story clean; multi-edit forks are a later addition.

---

## 3. Tech stack

Verified **2026-06-28** against PyPI / official docs.

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | The agent ecosystem is Python; 3.11 gives `tomllib`, `ExceptionGroup`, `Self`, and faster asyncio. The instrumentation lives where agents live. |
| LLM target | **`anthropic` 0.112.0** (Messages API) | First adapter; the user's ecosystem. Built on **httpx ≥0.25,<1**, which is exactly the seam we intercept. Made an *optional* extra — the engine itself only needs httpx. |
| Interception (HTTP) | **Custom `httpx` transport** | The SDK accepts `http_client=httpx.Client(transport=…)` (public, documented API) → we wrap the real transport. Robust to SDK version churn; captures raw request/response incl. SSE bodies; works sync **and** async. Far safer than monkeypatching SDK methods. |
| Interception (stdlib) | **Scoped monkeypatch** of `time`, `random`, `uuid` | Clock/RNG/UUID are stdlib; record each value drawn, replay in order. Patched only within the `record()`/`replay()` scope and restored on exit. |
| Trace index | **SQLite** (stdlib `sqlite3`, WAL mode) | Zero-dependency, embedded, transactional, great for the timeline's "events for run, ordered by seq" queries. The `TraceStore` interface keeps it swappable. |
| Trace payloads | **Content-addressed blob files** (BLAKE2b-256, gzip) | Large payloads (prompts, completions) live as deduplicated, compressed blobs outside SQLite; identical system prompts stored once. `hashlib.blake2b` + `gzip` are stdlib. |
| State diffs | **In-house canonical-JSON differ** (RFC 6902 / JSON-Patch shape) | Tiny, dependency-free; emits add/remove/replace ops over JSON pointers, rendered human-readably in the TUI. |
| CLI | **Typer** (`kinescope[cli]` extra) | Clean, typed, Click-based; behind an extra so the core stays minimal. |
| TUI | **Textual 8.2.7** (`kinescope[tui]` extra) | Modern, well-maintained terminal UI; gives the scrubbable timeline + fork demo without a web stack. |
| Pretty output | **Rich** (pulled by Typer/Textual) | Diff coloring, tables in `show`/`diff`. |
| Packaging | **`uv` + `hatchling`**, `pyproject.toml` | Fast, modern, lockfile-based; `kinescope` console entry point. |
| Test / lint | **pytest**, **ruff**, **mypy** | Standard. Replay determinism is itself the headline test target. |
| Storage adapter (later) | **`pymongo`** (`kinescope[mongo]` extra) | Document-shaped traces map cleanly to Mongo; ships post-v1 as a `MongoStore` implementing `TraceStore`. |

**Dependency story (the adoption lever):** the *core* engine depends on **`httpx` only**. `anthropic`, `typer`+`rich`, `textual`, and `pymongo` are all **extras**. `pip install kinescope` gives you record/replay; `pip install kinescope[anthropic,cli,tui]` gives the full experience. All licenses are permissive/commercial-friendly (anthropic MIT, httpx BSD, Textual MIT, Typer MIT, Rich MIT, pymongo Apache-2.0).

---

## 4. The trace model & interception contract — get this exactly right

Everything downstream (replay, branch, diff, divergence) is correct **iff** the trace and the interception contract are correct. This is the load-bearing core.

### 4.1 The three invariants

1. **Total order.** Every crossing of the nondeterministic frontier gets a single, process-global, monotonically increasing `seq`. Replay reconstructs exactly this order. (One `threading.Lock`-guarded counter in the active session; v1 is single-process.)
2. **Output-authoritative replay.** On replay, a boundary *never* calls out; it returns the recorded `output` for the matching `seq`. The model is never re-sampled; tools never re-execute; `time.time()` returns the recorded float.
3. **Input-verified matching.** Each boundary's *input* is canonicalized and hashed at record time. On replay, the live call's input hash is compared to the recorded one. Match → return recorded output. Mismatch (or wrong count) → **divergence** (policy-controlled, §6.4). This is what makes the determinism claim *honest*.

### 4.2 Canonical input hashing

The hash must be **stable across runs** and ignore volatile-but-irrelevant fields, or every replay would false-positive a divergence.

```python
# Canonicalize → BLAKE2b-256 hex. Used for matching, NOT for storage keys of output.
def canon_hash(kind: str, payload: dict) -> str:
    norm = _strip_volatile(kind, payload)          # see exclusions below
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=_json_default).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=32).hexdigest()
```

**Volatile fields excluded from the LLM input hash** (recorded in the raw blob, just not hashed): request `idempotency-key`, `x-request-id`, any `*-timestamp`/`date` header, retry counters, and SDK user-agent/version. **Kept (they change meaning):** model, messages, system, tools, tool_choice, temperature, top_p, max_tokens, stop sequences. For **tools**, the hash covers the tool name + canonicalized args. For **clock/RNG**, there is no meaningful input — they match purely by `(kind, seq)` position.

### 4.3 Core types

```python
from dataclasses import dataclass
from typing import Literal, Optional

BoundaryKind = Literal["llm", "tool", "clock", "rng", "retrieval"]

@dataclass(frozen=True, slots=True)
class Event:
    run_id: str
    seq: int                      # process-global order, 0-based
    kind: BoundaryKind
    name: str                     # "messages.create" | tool name | "time.time" | "uuid4" ...
    input_hash: str               # canon_hash(kind, input) — "" for clock/rng
    input_ref: Optional[str]      # blob id (BLAKE2b) of full input payload; None if trivial
    output_ref: Optional[str]     # blob id of full output payload
    status: Literal["ok", "error"]
    ts_wall: float                # real wall time at record (informational; never used by replay)
    dur_ms: float                 # informational
    meta: dict                    # kind-specific, OTel-GenAI-aligned (see below)

@dataclass(frozen=True, slots=True)
class Snapshot:
    run_id: str
    after_seq: int                # state as it was immediately after Event[after_seq]
    state_ref: str                # blob id of canonical-JSON state document
    label: Optional[str]          # e.g. "post-tool", user-supplied tag

@dataclass(frozen=True, slots=True)
class Run:
    run_id: str                   # sortable: f"{base32(ts_ms)}-{rand4}"
    label: str
    created_at: float
    status: Literal["recording", "complete", "error", "diverged"]
    parent_run_id: Optional[str]  # set for branched runs
    forked_at_seq: Optional[int]  # the k of the fork
    overrides: list[dict]         # the single-event override applied at the fork
    sdk_versions: dict            # {"kinescope": "...", "anthropic": "0.112.0", "python": "3.11.x"}
    divergences: list[dict]       # populated by replay/branch; [] when clean
```

`meta` for an `llm` event mirrors **OpenTelemetry GenAI** semantic conventions so the data speaks the industry's language and can later export as `gen_ai.*` spans:

```python
meta = {
  "gen_ai.system": "anthropic",
  "gen_ai.request.model": "claude-opus-4-8",
  "gen_ai.usage.input_tokens": 1234,
  "gen_ai.usage.output_tokens": 567,
  "gen_ai.response.finish_reasons": ["tool_use"],
  "stream": True,
  "http.status": 200,
}
```

### 4.4 The interception/replay contract (why the httpx seam works for streaming)

The LLM boundary is intercepted at the **httpx transport**, so we capture the exact wire exchange — including the SSE event stream — and can **re-materialize it** on replay without the network. The Anthropic SDK's own SSE parser then re-parses identical bytes, yielding identical typed objects.

```python
class KinescopeTransport(httpx.BaseTransport):           # + async sibling
    def __init__(self, inner: httpx.BaseTransport, session: "Session"):
        self._inner, self._s = inner, session

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        seq = self._s.next_seq()
        inp = _request_to_payload(request)             # method,url,headers(redacted),body(json/sse)
        if self._s.mode == "replay":
            ev = self._s.expect(seq, kind="llm", input_hash=canon_hash("llm", inp))
            body = self._s.store.get_blob(ev.output_ref)        # recorded raw response bytes
            return httpx.Response(ev.meta["http.status"], headers=ev.meta["resp_headers"],
                                  stream=httpx.ByteStream(body), request=request)
        # record (or live tail of a branch): call out, tee the body, log the event
        resp = self._inner.handle_request(request)
        raw = resp.read()                              # buffers SSE/non-SSE alike
        self._s.record(Event(kind="llm", seq=seq, input_hash=canon_hash("llm", inp),
                             input_ref=self._s.store.put_blob(inp),
                             output_ref=self._s.store.put_blob(raw), ...))
        return httpx.Response(resp.status_code, headers=resp.headers,
                              stream=httpx.ByteStream(raw), request=request)
```

> **Streaming caveat, stated honestly:** buffering the SSE body means a replayed stream yields its chunks *all at once* rather than time-spaced. That is correct for content (identical tokens, identical tool_use blocks) and is the right tradeoff for deterministic debugging; we are reproducing *what*, not *the latency of*, the stream. If a user opts into the SDK's `aiohttp` transport extra instead of httpx, the shim doesn't see it — the divergence detector will flag the un-captured call. (Documented limitation.)

Clock/RNG/UUID and tools do **not** go through httpx; they are intercepted by monkeypatch and decorator respectively (§6.1), but obey the same `Event` contract and the same global `seq`.

---

## 5. Architecture

**Pattern: ports-and-adapters (hexagonal) around a deterministic core.** The core (`session`, `record`, `replay`, `branch`, event model) knows nothing about *how* boundaries are intercepted or *where* traces live — those are adapters. This is what makes "add OpenAI", "add MongoStore", "add OTel export" cheap, and keeps the determinism logic testable in isolation.

```
                       ┌────────────────────── user's agent code ──────────────────────┐
                       │  with kinescope.record("run"):                                    │
                       │      client = anthropic.Anthropic(http_client=ses.http_client())│
                       │      @kinescope.tool  def search(q): ...                          │
                       │      kinescope.snapshot(state)                                    │
                       └───────────────┬───────────────────────────────────────────────┘
            INTERCEPTION ADAPTERS      │  (every crossing → Event with global seq)
   ┌───────────────┬──────────────────┼───────────────────┬───────────────────┐
   │ httpx transport│ tool decorator/  │ clock/rng/uuid    │ retrieval (HTTP    │
   │ shim (LLM)     │ registry wrap    │ monkeypatch       │ via same shim)     │
   └───────┬────────┴────────┬─────────┴─────────┬─────────┴─────────┬─────────┘
           └─────────────────┴──── Session (mode: record│replay│branch) ───────┘
                                    • global seq counter   • divergence detector
                                    • redaction            • snapshot capture
                                              │
                        ┌─────────────────────┴─────────────────────┐
                        │  CORE ENGINE                                │
                        │  record.py · replay.py · branch.py · model  │
                        └─────────────────────┬─────────────────────┘
                                              │  TraceStore (port)
                        ┌─────────────────────┴─────────────────────┐
                        │ LocalStore (default): SQLite index + blobs/ │   ← MongoStore (later)
                        └─────────────────────┬─────────────────────┘
                                              │
                   ┌──────────────────────────┴──────────────────────────┐
                   │  PRESENTATION                                          │
                   │  cli.py (Typer)  ·  tui/ (Textual)  ·  diff renderer   │
                   └───────────────────────────────────────────────────────┘
```

Data flow per mode:

```
record:  agent → adapters → Event(seq,k) + Snapshot → TraceStore
replay:  agent → adapters return recorded output by (seq, input_hash) → deterministic run + divergence report
branch:  replay seq<k → override Event[k] → adapters go LIVE for seq>k → new child Run recorded
view:    TraceStore → CLI/TUI: scrub seq · per-step I/O · JSON-Patch state diff · fork
```

Repo layout:

```
kinescope/
  src/kinescope/
    __init__.py        # public API: record(), replay(), tool, snapshot, http_client()
    session.py         # Session: mode, global seq, divergence, redaction
    model.py           # Event, Snapshot, Run, BoundaryKind, canon_hash
    record.py          # record-mode logic
    replay.py          # replay-mode logic + divergence detector
    branch.py          # fork@k, single-event override, replay→live switch
    intercept/
      http.py          # KinescopeTransport (sync+async) for LLM/retrieval
      stdlib.py        # clock/rng/uuid monkeypatch (scoped)
      tools.py         # @tool decorator + instrument_tools(registry)
    adapters/
      anthropic.py     # raw exchange → OTel-aligned meta; output reconstruction
    store/
      base.py          # TraceStore port
      local.py         # SQLite index + content-addressed blobs (default)
    diff.py            # canonical JSON + RFC6902-shape differ
    cli.py             # Typer: record/replay/ls/show/diff/fork/ui
    tui/               # Textual timeline app
  examples/
    weather_agent.py   # the demo agent (picks wrong tool → fork fixes it)
  tests/
  README.md  ROADMAP.md  DESIGN.md  PROGRESS.md  CLAUDE.md
```

---

## 6. Core systems

### 6.1 Interception layer

**What:** turn every boundary crossing into an `Event` with the global `seq`, transparently.

- **LLM / retrieval (HTTP):** `session.http_client()` returns an `httpx.Client`/`AsyncClient` whose transport is `KinescopeTransport` (§4.4). The user passes it to `anthropic.Anthropic(http_client=…)`. A convenience `kinescope.instrument(client)` swaps the transport on an already-built client for the zero-reconstruction path.
- **Tools:** `@kinescope.tool` wraps a callable; `kinescope.instrument_tools(mapping)` wraps a name→callable registry in place. Records `(name, canon args)` → return/raise.

```python
def tool(fn=None, *, name=None):
    def wrap(f):
        @functools.wraps(f)
        def inner(*a, **kw):
            ses = active_session()
            if ses is None: return f(*a, **kw)            # no-op outside a session
            seq = ses.next_seq(); inp = {"args": a, "kwargs": kw}
            if ses.mode == "replay" and not ses.is_live_after_fork(seq):
                ev = ses.expect(seq, "tool", canon_hash("tool", inp), name=name or f.__name__)
                return ses.store.get_json(ev.output_ref)  # tool does NOT execute
            out = f(*a, **kw)                              # record / live-tail: execute
            ses.record_tool(seq, name or f.__name__, inp, out)
            return out
        return inner
    return wrap(fn) if fn else wrap
```

- **Clock / RNG / UUID:** within a session, `time.time/monotonic/perf_counter`, `datetime.now/utcnow`, `random.random/randint/...`, and `uuid.uuid4` are patched to **record the value drawn** and, on replay, **return the recorded value by seq**. We record outputs (not seeds) — robust across Python versions, consistent with every other boundary. Patches are installed on `__enter__` and restored on `__exit__` (even on exception).

### 6.2 Recorder

Opens a `Run`, sets `Session.mode="record"`, installs adapters, captures `Event`s and `Snapshot`s through the `TraceStore`, finalizes status on exit. Public surface:

```python
with kinescope.record("nightly-repro", store=kinescope.LocalStore(".kinescope")) as ses:
    run_my_agent()                      # boundaries auto-captured
print(ses.run_id)                       # e.g. "01JZ8…-a3f1"
```

### 6.3 Replay engine & branch engine

**Replay:** `Session.mode="replay"`; adapters consult the log instead of calling out. The engine walks user code again; `expect(seq, kind, input_hash)` returns the recorded output or raises/records a divergence. Output for `llm` is re-materialized as raw bytes through the transport so the SDK rebuilds identical objects.

**Branch (the novel hook):**

```python
new_id = kinescope.fork(
    run_id, at=7,
    override={"kind": "tool", "output": {"temp_f": 71, "city": "Paris"}},  # OR llm completion
)
# semantics: replay events 0..6 deterministically; substitute the override AS event 7's output;
# from seq 8 onward, Session flips to LIVE — real LLM/tool calls — recording a NEW child Run
# whose parent_run_id=run_id, forked_at_seq=7, overrides=[...].
```

The replay→live switch is a single boolean keyed on `seq > forked_at_seq`. The branched tail is recorded exactly like a fresh run, so branches are themselves replayable and forkable (a tree of runs).

### 6.4 Divergence detector (the honesty mechanism)

During replay/branch-prefix, every boundary is checked:

- **Input mismatch:** live `input_hash` ≠ recorded → record a `divergence` `{seq, kind, expected, actual}`.
- **Order/count mismatch:** agent makes a call at a `seq` of a different `kind`, or runs off the end of the log, or finishes early.
- **Un-captured nondeterminism:** a boundary that *should* be in the log isn't (e.g., an un-wrapped tool, an aiohttp-transport call) shows up as an order mismatch — surfaced, not swallowed.

Policy via `record()/replay(policy=…)`: `strict` (raise on first), `warn` (default — log, continue using recorded-by-position), `off`. Divergences are written to `Run.divergences` and shown in `show`/TUI. **This is the feature that lets Kinescope claim determinism honestly:** it tells you precisely where the guarantee leaked.

### 6.5 State snapshots & diffs

- **Capture:** `kinescope.snapshot(obj, label=None)` serializes a document-shaped state (the messages list, scratchpad, memory — user's choice) to canonical JSON and stores it content-addressed, tagged `after_seq = current seq`. Optionally `record(snapshot=lambda: agent.state)` auto-snapshots after each `llm` event.
- **Dedup:** identical states (common across adjacent steps) collapse to one blob via BLAKE2b id.
- **Diff:** `diff.py` computes an RFC 6902-shaped patch (`add`/`remove`/`replace` over JSON pointers) between any two snapshots, **lazily** (only when a step is viewed), rendered with Rich coloring. No diff is precomputed → scrubbing stays O(1).

```python
# kinescope diff <run> 6 7   →
# replace /messages/8/content  "I'll use convert_units"  →  "I'll use get_weather"
# add     /scratchpad/last_tool  "get_weather"
```

### 6.6 Storage (`TraceStore` port + `LocalStore`)

```python
class TraceStore(Protocol):
    def create_run(self, run: Run) -> None: ...
    def update_run(self, run: Run) -> None: ...
    def get_run(self, run_id: str) -> Run: ...
    def list_runs(self) -> list[Run]: ...
    def append_event(self, ev: Event) -> None: ...
    def events(self, run_id: str) -> list[Event]: ...          # ordered by seq
    def put_snapshot(self, snap: Snapshot) -> None: ...
    def snapshots(self, run_id: str) -> list[Snapshot]: ...
    def put_blob(self, data: bytes | dict) -> str: ...          # → BLAKE2b id, dedup, gzip
    def get_blob(self, blob_id: str) -> bytes: ...
```

`LocalStore` layout (everything under `.kinescope/`):

```
.kinescope/
  index.db            # SQLite (WAL): runs, events, snapshots tables
  blobs/<aa>/<blake2b-hex>.json.gz   # content-addressed, gzipped, deduplicated
```

**Redaction** runs *before* `put_blob` on any input payload: credential headers dropped, plus a user `scrubber(payload) -> payload` hook for body fields (e.g., redact `messages[*].content` matching a regex). On by default for auth headers; opt-in for body scrubbing.

### 6.7 CLI & TUI surface

```
kinescope record -- python weather_agent.py     # run an agent under recording
kinescope ls                                     # list runs (id, label, status, #events, divergences)
kinescope show <run-id> [--step k]               # event detail: messages / tool I/O / meta
kinescope diff <run-id> <a> <b>                  # state diff between two steps
kinescope replay <run-id> [--policy strict]      # deterministic replay + divergence report
kinescope fork <run-id> --at k --override-tool '{"temp_f":71}'   # → new child run id
kinescope ui <run-id>                            # Textual timeline (scrub · inspect · fork)
```

`record -- <cmd>` runs the user's program with an env flag that auto-activates a default session (for programs that call `kinescope.record()` themselves, it's a no-op wrapper). The first-class path is the in-code `with kinescope.record(...)`.

---

## 7. TUI — the timeline (where the demo lives)

A three-pane Textual app; the fork-and-fix gif is recorded here.

```
┌ Kinescope ── run 01JZ8…-a3f1  "weather repro"  ⚠ 0 divergences ──────────────────────┐
│ STEPS                  │ STEP 7 · tool · get_weather            │ STATE DIFF (6→7)   │
│  4  llm  messages.crea │ input  { "city": "Paris" }             │ replace /messages/8│
│  5  tool get_weather   │ output { "temp_f": 71, "sky": "clear"} │   "use convert" →  │
│  6  llm  messages.crea │ status ok · 142ms                      │   "use get_weather"│
│ ▸7  tool convert_units │ ─────────────────────────────────────  │ add /scratchpad/…  │
│  8  llm  messages.crea │ [ f ] fork here   [ enter ] open       │                    │
└─ ↑/↓ scrub · f fork · d diff · / filter · q quit ──────────────────────────────────┘
```

- **Steps pane:** the event log, color-coded by kind, fork points marked `⑂`, divergences marked `⚠`.
- **Detail pane:** selected step's normalized message / tool I/O / `meta`.
- **Diff pane:** lazy JSON-Patch diff vs. the previous snapshot.
- **`f` (fork):** prompts for the single-event override, calls `branch.fork`, and (stretch) drops you into the new child run live. The core feel-good loop: *scrub → spot the bad step → fork → watch it go right.*

---

## 8. Milestones

Top-down, each independently runnable. Scaffold turns these into `ROADMAP.md` (adding explicit Test steps).

- **M0 — Walking skeleton (record→replay one call).** `with kinescope.record()` + `KinescopeTransport` capture a single non-streaming Anthropic `messages.create` to `LocalStore`; `kinescope replay <id>` re-runs a one-call example agent returning the recorded completion; `kinescope ls`/`show`. **Proves** the end-to-end record→replay loop and the store on the simplest agent.
- **M1 — Full frontier + ordering + divergence.** Add `@kinescope.tool`, clock/RNG/UUID monkeypatch, the global `seq`, **async** + **SSE streaming** capture, and the divergence detector. Deterministically replay a multi-step, tool-using agent. **Proves** pillar 1 (total interception) and honest determinism.
- **M2 — State snapshots & diffs.** `kinescope.snapshot()`, content-addressed dedup, lazy RFC 6902 diffs; `show --step k`, `diff a b`. **Proves** pillar 3 (state diffing) and makes runs inspectable.
- **M3 — Branching (the novel hook).** `kinescope fork --at k --override …`, replay→live switch, child-run lineage, re-recorded tail. **Proves** pillar 2 — the counterfactual that makes Kinescope more than a tracer.
- **M4 — Timeline TUI + flagship demo.** Textual three-pane scrub/inspect/diff with `f`-to-fork; polish divergence display; record the fork-and-fix gif against `examples/weather_agent.py`. **Proves** the product — the pitch in one screen recording.
- **M5 — Reach (stretch, pick by signal).** OpenAI adapter (second provider validates the abstraction) · OTel `gen_ai.*` span export · `MongoStore` · shareable/exportable trace bundles · minimal web timeline.

**Ship publicly at M3–M4** (replay + branch + a demo is the story).

---

## 9. Risks / open questions

- **Hidden nondeterminism escapes the shims** (un-wrapped tools, file/DB reads, threads, dict/set ordering). → The **divergence detector** is the mitigation *and* the honest framing: we don't claim magic, we claim "deterministic at instrumented boundaries, and we'll tell you when something leaked." Document the wrap-your-tools contract clearly.
- **SSE replay loses streaming timing** (chunks arrive batched). → Accept it: debugging needs *what*, not *when*. Note in docs; a "paced replay" option is a possible later nicety.
- **Alternate SDK transports** (`anthropic[aiohttp]`) bypass the httpx seam. → Detect as an order mismatch and warn; httpx is the SDK default, so the common path is covered. An aiohttp adapter is a later add.
- **Replay→live branch divergence at the seam** (the live tail behaves unexpectedly because prefix state wasn't perfectly reconstructed). → Snapshots + divergence checks bracket the fork; the branch records a fresh trace so the result is itself inspectable. Open question: how aggressively to snapshot around fork points (every step near *k* vs. just at *k*).
- **Large traces / blob bloat** on long runs with big prompts. → Content-addressed dedup + gzip handles repetition; add a retention/prune command if needed.
- **Open question — auto-snapshot ergonomics.** Is a single `kinescope.snapshot(state)` call enough, or do we need framework-aware auto-capture of the messages list? Resolve in M2 against the real example agent.
- **Open question — multi-process / multi-agent.** Out for v1; the global-seq design is single-process. A future cross-process clock/order is a genuine research-grade extension (and a strong systems flex if pursued).

---

## 10. References

Prior art and standards the design leans on (verified **2026-06-28**):

- **rr** (Mozilla) & **Pernosco** — deterministic record-replay for native processes; the lineage and the bar for "replay any run." Kinescope is this idea, moved to the LLM-agent boundary.
- **VCR.py** (vcrpy 8.x) — HTTP record/replay via "cassettes." Kinescope generalizes the *technique* (transport-level record/replay) but adds agent state, global ordering across non-HTTP boundaries, and counterfactual branching — none of which VCR targets.
- **LangGraph time-travel / checkpointers** — fork/replay of agent runs, but **framework-locked** and rewinds *graph state* rather than replaying recorded *nondeterministic inputs*. Kinescope works *under* any framework at the SDK/HTTP seam.
- **Agent observability** (LangSmith, Langfuse, AgentOps, Arize Phoenix, W&B Weave, OpenLLMetry/Traceloop, Laminar) — strong *tracing/visualization*, but read-only: no deterministic replay, no single-event counterfactual fork. Kinescope's unoccupied niche.
- **OpenTelemetry GenAI semantic conventions** (`gen_ai.*` spans/events, Development status as of 2026) — the `Event.meta` vocabulary aligns to it for credibility and a future export path. <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- **Key libraries:** `anthropic` 0.112.0 (MIT; httpx-based) · `httpx` ≥0.25,<1 (BSD) · `textual` 8.2.7 (MIT) · `typer`/`rich` (MIT) · `pymongo` (Apache-2.0, later). Stdlib: `sqlite3`, `hashlib.blake2b`, `gzip`, `time`, `random`, `uuid`.
- **Stack reuse note:** the `MongoStore` adapter ties Kinescope to a document-DB stack if/when the author wants persistence beyond local files; the `TraceStore` port keeps that a drop-in, not a rewrite.
```
