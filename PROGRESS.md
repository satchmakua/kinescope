# PROGRESS — Eidetic

A build log of what shipped and the notable decisions behind it. **Keep it honest** —
this is the working memory between build sessions. The forward-looking plan and
acceptance tests live in [ROADMAP.md](ROADMAP.md); this is the backward-looking "what
got done and why" companion.

**Current phase:** Phase 2 next (M3 — branching). M0 + M1 are in.

### State of the tree

| Component | File | Status |
|---|---|---|
| Trace model + canonical hashing | `src/eidetic/model.py` | ✅ M0 |
| Session (global seq, suppression, divergence) | `src/eidetic/session.py` | ✅ M1 |
| HTTP interception (sync + async, SSE) | `src/eidetic/intercept/http.py` | ✅ M1 |
| Tool interception | `src/eidetic/intercept/tools.py` | ✅ M1 |
| Clock/RNG/UUID interception | `src/eidetic/intercept/stdlib.py` | ✅ M1 |
| record() / replay() / http_client() / async | `src/eidetic/engine.py` | ✅ M1 |
| LocalStore (SQLite + blobs) | `src/eidetic/store/local.py` | ✅ M0 |
| TraceStore port | `src/eidetic/store/base.py` | ✅ M0 · MongoStore → M5 |
| CLI (`ls`, `show`) | `src/eidetic/cli.py` | ✅ M0 · replay/fork/ui → later |
| State snapshots + diff | `src/eidetic/diff.py` | ⏳ M2 |
| Branch engine | `src/eidetic/branch.py` | ⏳ M3 |
| Textual TUI | `src/eidetic/tui/` | ⏳ M4 |

---

## M1 — Full boundary capture · built 2026-06-28 (awaiting human confirm)

Extended capture from "just the LLM call" to the **whole nondeterministic frontier**,
with honest divergence detection, async, and streaming.

**What shipped**
- **`@eidetic.tool` / `instrument_tools()`** — a tool is an *atomic* boundary: on record
  it executes and we log input/output; on replay it does NOT execute (proven by a
  side-effect counter in the tests). Nondeterminism inside a tool body is **suppressed**
  (`Session.suppress()`) so it neither records nor consumes a seq — it's subsumed by the
  tool's recorded output.
- **Clock/RNG/UUID** interception (`StdlibPatcher`) — opt-in via `record(capture=[...])`
  (or `"all"`); patches `time.{time,monotonic,perf_counter}`, numeric `random.*`, and
  `uuid.uuid4`. Records the *value drawn* (inline in `meta`, no blob) and replays by
  position; UUIDs round-trip to `uuid.UUID`. Capture is **off by default** (it's invasive).
- **Async** transport (`EideticAsyncTransport`, `eidetic.async_http_client`) mirroring the
  sync path, for `anthropic.AsyncAnthropic`.
- **SSE streaming** — already buffered at the transport; added a real test proving an
  Anthropic `messages.stream()` is captured and re-materialized so `text_stream` yields
  identical text offline.
- **Divergence detector** — input-mismatch, kind-mismatch, extra-call (raises; nothing to
  return), and missing-call (via `finalize_replay`). `strict` raises on first; `warn`
  records and continues by position; persisted to `Run.divergences`.
- New `Run.capture` field/column so replay re-applies the exact recorded patch set
  (sequence stays aligned).

**Decisions / gotchas**
- **Eidetic must not trip its own patches.** Found & fixed a real bug: `gzip.compress()`
  defaults to `mtime=None`, which calls `time.time()` — so every blob write was emitting a
  phantom clock event under clock capture, corrupting replay alignment. Now `mtime=0`
  (also makes blobs byte-deterministic for dedup). All internal timing uses by-value
  imports (`from time import perf_counter`) so patches can't intercept Eidetic itself.
- **Library clock calls are captured too** (httpx/anthropic call `perf_counter`/`time`
  during a request). They replay deterministically because httpx's send path wraps our
  transport on *both* record and replay. The risk case — real network on record vs.
  short-circuited replay making *different* clock calls — would surface as a divergence,
  not silent corruption. This is the documented limit of global clock capture.
- Tool outputs are stored as JSON; tools should return JSON-shaped data (the agent norm).

**Verified**
- `pytest` → **18 passed** (added: tools, stdlib capture, async, SSE streaming, divergence).
- `ruff check .` clean · `mypy src` clean (12 files).
- `python examples/tool_agent.py` → tool + clock + RNG + LLM agent replays identically,
  8 events, 0 divergences. M0 `record_demo.py` still green (capture off → unaffected).
- `eidetic show <id>` renders clock/rng/tool/llm events with per-step I/O.

---

## M0 — Walking skeleton · built 2026-06-28 (awaiting human confirm)

Shipped the end-to-end **record → replay** loop, deterministic and offline.

**What shipped**
- **Interception at the httpx transport** (`EideticTransport`), not via SDK-method
  monkeypatching — robust to SDK version churn and captures the exact wire exchange.
  In record mode it tees the response body into the store; in replay mode it
  re-materializes the recorded bytes and never calls the inner transport.
- **Trace model** (`Event`/`Snapshot`/`Run`) with BLAKE2b-256 **canonical hashing** over
  the call *identity* (`method + url + body`, header-free) as the replay match key.
- **LocalStore**: SQLite (WAL) index + **content-addressed, gzipped, deduplicated** blob
  files under `.eidetic/blobs/`. Identical payloads collapse to one file.
- **Session** with a process-global `seq` counter and a first-cut **divergence detector**
  (`strict`/`warn`/`off`).
- **CLI** `eidetic ls` / `eidetic show` (Rich tables); **secret redaction** of auth headers
  before anything hits disk.
- **Offline demo** (`examples/record_demo.py`) driving the *real* Anthropic 0.112 SDK
  through a stub inner transport — records a `messages.create`, then replays it with a
  "forbidden" transport that raises if touched, proving replay is network-free.

**Decisions** (see ADRs 0001–0002)
- Core engine depends on **`httpx` only**; `anthropic`, `cli`, `tui`, `mongo` are extras —
  the adoption lever.
- Record **outputs**, never re-derive (no re-sampling, no RNG re-seeding) — determinism is
  at the boundary by construction.
- Event `meta` aligned to **OpenTelemetry GenAI** (`gen_ai.*`) vocabulary for future
  interop/export.

**Verified**
- `pytest` → 6 passed (record→replay determinism, divergence detection under warn/strict,
  blob dedup, store round-trip, session guard).
- `ruff check .` clean · `mypy src` clean (10 files).
- `python examples/record_demo.py` → records run, replays identically, 0 divergences.
- `eidetic ls` / `eidetic show <id>` render the run and its single LLM event.

**Gotchas for next session**
- Replay re-materializes the *decoded* body, so we strip `content-encoding`/`content-length`/
  `transfer-encoding` from stored response headers to avoid double-decoding. Keep this when
  adding SSE streaming (M1) — buffer the raw SSE body and replay it as bytes.
- `Run` is a mutable dataclass (status/divergences mutate); `Event`/`Snapshot` are frozen.
- Replay matching is purely positional by `seq` + input-hash; this is what M1's tool/clock/RNG
  interception must also funnel through (same `next_seq()`), or ordering will break.
