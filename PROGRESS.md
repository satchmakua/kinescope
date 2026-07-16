# PROGRESS — Kinescope

A build log of what shipped and the notable decisions behind it. **Keep it honest** —
this is the working memory between build sessions. The forward-looking plan and
acceptance tests live in [ROADMAP.md](ROADMAP.md); this is the backward-looking "what
got done and why" companion.

**Current phase:** Complete for practical purposes. M0–M4 + H1 + H2 + H3 + M5 done, plus **three
real recorded runs** that reproduce offline (hosted **Anthropic**, hosted **Gemini**, local
**Ollama**), a **CLI agent runner** (`record`/`replay`/`fork -- <cmd>`), and **four providers**
(Anthropic, OpenAI, Gemini, Ollama). **65 tests, no skips**, ruff/mypy clean, human-verified. A
`Makefile` (`make demo`/`test`/`lint`) is committed. **Remaining (all optional, tracked in
ROADMAP → _Deferred / later_):** **Groq**, a live OpenAI run, and a web timeline. The real gap
is now **distribution** (PyPI, users), not engineering.

### State of the tree

| Component | File | Status |
|---|---|---|
| Trace model + canonical hashing | `src/kinescope/model.py` | ✅ M0 |
| Session (seq, suppression, divergence, snapshots, branch) | `src/kinescope/session.py` | ✅ M3 |
| HTTP interception (sync + async, SSE) | `src/kinescope/intercept/http.py` | ✅ M1 |
| Tool interception | `src/kinescope/intercept/tools.py` | ✅ M1 |
| Clock/RNG/UUID interception | `src/kinescope/intercept/stdlib.py` | ✅ M1 |
| Provider adapters (gen_ai.* normalize: anthropic + openai + gemini) | `src/kinescope/adapters/` | ✅ H1 + |
| CLI agent runner (record/replay/fork -- <cmd>) | `src/kinescope/runner.py` | ✅ |
| OTel gen_ai span export | `src/kinescope/export/otel.py` | ✅ M5 |
| Shareable trace bundles (export/import) | `src/kinescope/export/bundle.py` | ✅ M5 |
| Real recorded Anthropic run (offline-reproducible) | `examples/live_record.py` + fixture | ✅ |
| record() / replay() / http_client() / snapshot() | `src/kinescope/engine.py` | ✅ M2 |
| Branch engine (fork@k, override, replay→live) | `src/kinescope/branch.py` | ✅ M3 |
| State snapshots + structural diff | `src/kinescope/diff.py` | ✅ M2 |
| LocalStore (SQLite + blobs) | `src/kinescope/store/local.py` | ✅ M0 |
| TraceStore port | `src/kinescope/store/base.py` | ✅ M0 |
| MongoStore (document-DB backend) | `src/kinescope/store/mongo.py` | ✅ M5 |
| CLI (`ls`, `show`, `diff`, `ui`) | `src/kinescope/cli.py` | ✅ M4 · `fork` runner → later |
| Textual TUI (3-pane scrub/detail/diff + fork) | `src/kinescope/tui/` | ✅ M4 |

---

## 2026-07-16 — Live Gemini run: the last skip is gone

`examples/fixtures/real_gemini_run.zip` is committed and
`test_real_gemini_run_replays_offline` passes — **65 tests, no skips**. Three providers now
have genuine recorded runs that reproduce offline: hosted **Anthropic**, hosted **Gemini**,
local **Ollama**.

**The 429 was a misdiagnosis, and the error body proved it.** Every prior attempt (CI *and*
the author's machine) failed with `429`, which reads as "rate-limited, wait it out." It
wasn't. Reading the response body:

- `gemini-2.0-flash` → `Quota exceeded ... generate_content_free_tier_requests, limit: 0` —
  **limit zero**, i.e. this key has *no* free-tier quota for that model. Waiting could never
  have fixed it, despite the API's own "Please retry in 56s" hint.
- `gemini-2.5-flash` → `404: "This model is no longer available to new users."`

Google has moved the legacy flash models off the free tier. Pinned **`gemini-3.1-flash-lite`**
(a concrete 3.x model with real free quota — verified alongside `gemini-flash-lite-latest` and
`gemini-3-flash-preview`, which also work; `gemini-3.5-flash`/`gemini-flash-latest` were 503
"high demand"). Recorded first try. Deliberately avoided the floating `-latest` aliases and
`-preview` ids so the artifact stays regenerable.

**Lesson worth keeping:** on a `429`, read the *body* — Google names the exact quota metric and
its limit. `limit: 0` means "wrong model for this tier," not "slow down." Status code alone
sent us chasing a nonexistent rate limit across two networks and several days.

**The recorded run:** `gemini-3.1-flash-lite` said `'Earth'`; offline replay reproduced it
byte-for-byte, 0 divergences. Meta: `gen_ai.system=gcp.gemini`, model **pulled from the URL
path** (Gemini's distinctive shape), real tokens (12 in / 1 out), `finish_reasons=['STOP']`,
`x-goog-api-key` redacted; bundle scanned — no `AIza` token.

**Verified:** `pytest` → **65 passed, 0 skipped**; `ruff` clean; `mypy` clean (27 files).

---

## 2026-07-16 — Live Ollama run: a second real-run artifact (free, local)

Closed the review's #1 remaining item — the multi-provider claim is now **live-proven twice**,
not once.

- **`adapters/ollama.py`** — Ollama serves an OpenAI-compatible `/v1/chat/completions`, so the
  response parsing is *reused* from the OpenAI adapter; only `gen_ai.system` differs
  (`"ollama"`). Dispatch is by Ollama's well-known **port 11434** (the host is just
  `localhost`, so host-matching can't work) — see `adapters/base.py`. That reuse is the point:
  the schema absorbs a new *runtime* with no new parsing, while Gemini proved it absorbs new
  *wire shapes*.
- **`examples/live_ollama_agent.py` + `live_ollama_record.py`** — records a real
  `qwen2.5:1.5b-instruct` call via the **OpenAI SDK pointed at Ollama** (the idiomatic usage),
  so this also shows the engine intercepting a real SDK against a local model. Committed
  `examples/fixtures/real_ollama_run.zip` (1,829 bytes).
- **The run:** the model answered `'Earth.'`; offline replay reproduced it byte-for-byte with
  **0 divergences** against a forbidden transport. Recorded meta: `gen_ai.system=ollama`,
  `model=qwen2.5:1.5b-instruct`, real token counts (40 in / 3 out), `finish_reasons=['stop']`,
  `authorization` redacted.

**Why this matters:** it's reality-contact with **zero cost and zero flakiness** — no key, no
quota, no network — so unlike the Gemini capture (still blocked on free-tier `429`) it will
keep working in CI forever. `tests/test_real_run.py` now has **2 passing** real-run replays
(Anthropic, Ollama) and 1 skipped (Gemini, until its bundle exists).

**Verified:** `pytest` → **64 passed, 1 skipped**; `ruff` clean; `mypy` clean (27 files).

---

## 2026-07-15 — Renamed Eidetic to Kinescope

Full product rename: PyPI/package name `eidetic` → `kinescope`, package dir
`src/eidetic/` → `src/kinescope/`, console script `eidetic` → `kinescope`, local trace
dir `.eidetic/` → `.kinescope/`, and all current-facing docs. Historical entries below
keep the old name; previously recorded traces in `.eidetic/` dirs are not auto-found.

---

## Reviewer follow-ups — live run + CLI runner + Gemini · 2026-07-10 (confirmed)

Closed the three remaining items from the external review (`../ai-docs/project_eval/Eidetic.md`).

- **Live-key Anthropic run (reality-contact).** `examples/live_record.py` records a genuine
  Claude Haiku call (via the User-env key, injected without logging it), proves it replays
  offline, and commits `examples/fixtures/real_anthropic_run.zip`. `tests/test_real_run.py`
  imports that bundle and replays it **offline, 0 divergences** — so a *real* run is now
  reproducible in CI forever, with no key. Verified the committed bundle contains no
  `sk-ant-` token (auth header redacted to `<redacted>`).
- **CLI agent runner.** `src/eidetic/runner.py` + `eidetic record`/`replay`/`fork -- python
  agent.py` run a user's script in-process under a session (runpy, `__main__`), so boundaries
  are captured from the command line — not just the library. Contract: the script builds its
  client with `eidetic.http_client()` and doesn't open its own `record()`. Demoed by
  `examples/agent_script.py`; end-to-end record→replay(0 div)→fork all confirmed via the CLI.
- **Third provider — Gemini (`adapters/gemini.py`).** Deliberately a *different* wire shape
  than OpenAI/Anthropic: model in the **URL path**, `promptTokenCount`/`candidatesTokenCount`,
  uppercase `finishReason`. Records/replays through the same engine (raw httpx + fixture,
  **free/offline**) and normalizes to the shared `gen_ai.*` vocab (`gen_ai.system=gcp.gemini`).

**Verified:** `pytest` → **62 passed, 1 skipped** (added `test_real_run.py`, `test_runner.py`,
`test_gemini.py`, a Gemini adapter unit test; the Gemini real-run test skips until its bundle
exists); `ruff` clean; `mypy` clean (26 files). Also fixed the stale `cli.py` docstring the
review flagged.

**Live Gemini recorder built, capture pending.** `examples/live_gemini_agent.py` +
`examples/live_gemini_record.py` mirror the Anthropic pair (key in the `x-goog-api-key`
*header*, so the trace stays key-free). Attempting the live capture from the CI sandbox hit
Google throttling (429/503 across models; the key itself is valid — `models.list` returned
200), so the real Gemini bundle must be generated from a non-shared network:
`./.venv/Scripts/python.exe examples/live_gemini_record.py` (key already in the user's env).
Until then Gemini is proven offline (adapter fixture test) and the real-run test skips. A
`make demo` target and a live OpenAI run remain as optional polish.

---

## H3 — Flagship fork-and-fix gif · 2026-07-10 (confirmed)

The README now opens with the artifact. `docs/timeline.gif` (1114×665, ~208 KB) was recorded
from `examples/fork_demo_tui.py`: fork the `sensor` step, override the reading, and the
downstream `classify` re-runs live — verdict flips **cold → warm**, reproduced from the trace.
Embedded at the top of the README with the reproduce command. The static `docs/timeline.svg`
is kept as a fallback frame; only leftover is a `make demo` target.

Also this session: the full suite was **human-verified** on the user's machine — `pytest` 54
passed, `ruff` clean, `mypy` clean (24 files); `fork_demo.py` and `share_bundle.py` both ran.

---

## M5 (slice) — Shareable trace bundles · built 2026-06-29

Hand a failing run to someone else: export it whole, import it anywhere, replay/fork it there.

**What shipped**
- **`eidetic.export_bundle(run_id, path, store=None)` / `import_bundle(path, store=None)`**
  (`src/eidetic/export/bundle.py`) — a zip with `manifest.json` (run + events + snapshots) and
  every referenced blob. Content-addressed blobs mean the event/snapshot refs stay valid after
  import; versioned (`bundle_version`) and stdlib-only (`zipfile`), so it's core, not an extra.
- **`eidetic export <id> <path>` / `eidetic import <path>`** CLI.

**Verified**
- `pytest` → **54 passed** (added `test_bundle.py`): a run exported from one store imports into
  a *fresh* store and replays identically (0 divergences); the imported run is **forkable**;
  unknown `bundle_version` is rejected.
- `ruff` clean · `mypy` clean (24 files). `python examples/share_bundle.py` and the
  `eidetic export`/`import` CLI roundtrip both work offline.

---

## M5 (slice) — MongoStore: the second backend · built 2026-06-29

The storage analog of H1: if the same engine runs against a totally different backend with
**zero engine changes**, the `TraceStore` port (the design's other load-bearing abstraction)
is real — not just LocalStore wearing an interface.

**What shipped**
- **`src/eidetic/store/mongo.py`** — `MongoStore` mapping Run/Event/Snapshot to collection
  documents and content-addressed, gzipped, deduplicated blobs (`_id` = BLAKE2b). `commit()`
  is a no-op (Mongo writes are durable on ack). Construct from a URI/`pymongo` client, or
  inject any compatible client. Requires the `mongo` extra.
- **Gotcha handled:** MongoDB historically disallows dots in field *names*, and our `meta`
  keys are dotted (`gen_ai.system`, `http.status`). So `meta` is stored as a JSON string
  (everything else — overrides/divergences/sdk_versions/capture — has safe keys, stored
  native). Round-trips verified.

**Verified**
- `pytest` → **51 passed** (added `test_mongo.py`, hermetic via `mongomock`): record→replay
  determinism, fork + lineage + override marker, blob dedup, and dotted-key `meta` round-trip
  — all through `MongoStore` with the engine untouched.
- `ruff` clean · `mypy` clean (23 files).

---

## M5 (slice) — OTel `gen_ai.*` span export · built 2026-06-29

Delivered on the design's standing promise (§4.3) that `Event.meta` is OTel-aligned "so a
future export path is cheap" — it is.

**What shipped**
- **`eidetic.export_otel(run_id, store=None, tracer_provider=None)`** (`src/eidetic/export/otel.py`)
  — emits one parent `eidetic.run` span with a child per LLM (`chat {model}`) and tool
  (`execute_tool {name}`) boundary, carrying the recorded `gen_ai.*` attributes and the
  recorded wall-clock start/end times. Returns the gen_ai-span count.
- **`eidetic export-otel <id>`** CLI → prints spans via OTel's `ConsoleSpanExporter` (lazy
  import; friendly error without the `otel` extra).
- **`otel` optional extra** (`opentelemetry-sdk`); `opentelemetry` is imported only when
  `export_otel` runs, so the core stays dependency-light.

**Why it matters:** every observability backend I surveyed (Phoenix, Langfuse, LangSmith,
Laminar) ingests OTel GenAI spans — so a recorded Eidetic trace drops into the existing
ecosystem with no glue. It also confirms the `gen_ai.*` normalization (H1) is real output,
not just stored strings.

**Verified**
- `pytest` → **47 passed** (added `test_otel.py`: span names, `gen_ai.*` attributes incl.
  `finish_reasons`, parent/child structure, and recorded-timing fidelity via an in-memory
  exporter).
- `ruff` clean · `mypy` clean (22 files).
- `python examples/otel_export.py` and `eidetic export-otel <id>` both print real spans
  (`chat claude-opus-4-8`, `execute_tool search`, `eidetic.run`).

---

## H2 — Determinism stress suite · built 2026-06-29

Stressed the one guarantee everything rests on — correctness-of-replay — and turned up a
real perf bug along the way.

**What shipped** (`tests/test_stress.py`, 7 tests)
- **Async ordering:** sequential async boundaries replay byte-identical, 0 divergences.
- **Concurrency honesty:** `asyncio.gather`-fired boundaries are *never silently wrong* —
  replay is identical-or-flagged (the documented contract for concurrent ordering).
- **Reordering flagged:** boundaries fired in a different order on replay → input-mismatch
  divergence (the concurrency hazard is caught, not hidden).
- **Hidden nondeterminism flagged:** an input that changes out from under replay (un-captured
  source) → divergence at the right step.
- **Property check:** 25 randomly-structured deterministic agents (rng/clock/tool mixes,
  `capture="all"`) each replay faithfully with 0 divergences.
- **Scale:** 10k inline (rng) boundaries record + replay reproducing every value exactly.

**Perf bug found + fixed.** `LocalStore.append_event` was committing per event — one fsync
per boundary throttled record to **~700–1,800 events/s**. Events are now buffered on the
connection and flushed by a new `commit()` that the engine calls when a session closes
(`update_run` already ran in every `finally`; `commit()` makes it explicit). Record throughput
for inline events jumped ~10–100× to **~20k–190k/s** (cache-warmth dependent; 10k events in
~0.05–0.55s); replay **~130–165k/s** (~0.06–0.08s). Trade: a crashed recording loses its
in-flight tail — fine for a debugger.

**Honest numbers / "can't do":**
- Inline events (clock/RNG): ~20k–190k/s record (warmth-dependent), >130k/s replay; 10k
  events record+replay in <1s either way.
- Tool/LLM events are bound by **blob writes** (gzip + a file per *distinct* payload):
  ~1k/s for 10k distinct outputs; identical payloads dedup to zero cost. (Future: inline
  small blobs in SQLite.)
- **Thread-scoped capture is a real gap** (pinned by `test_worker_thread_boundaries_are_not_
  captured`): the session is a contextvar, so boundaries on worker threads that don't inherit
  it are NOT captured — and since they never enter the seq stream, the divergence detector
  can't flag them. Record on one thread / async-context per run. (asyncio tasks DO inherit
  the context, so single-thread async is fine.)

**Verified:** `pytest` → **45 passed**; `ruff` clean; `mypy` clean (20 files); all examples green.

---

## H1 — OpenAI adapter: the provider-agnostic proof · built 2026-06-29

The headline hardening item: prove the event schema generalizes beyond Anthropic. It does —
with **no core change** beyond moving one hardcoded string into an adapter.

**What shipped**
- **`src/eidetic/adapters/`** — `base.normalize_meta(url, req_body, resp_bytes)` dispatches by
  request host to `anthropic.py` / `openai.py` normalizers (JSON-only, never raises, needs no
  provider SDK installed). The engine's only change: `intercept/http.py` now calls
  `normalize_meta(...)` instead of hardcoding `"gen_ai.system": "anthropic"`.
- **OpenAI normalization** maps the wire differences to the shared OTel vocabulary:
  `prompt_tokens → gen_ai.usage.input_tokens`, `completion_tokens → output_tokens`,
  `choices[].finish_reason → gen_ai.response.finish_reasons`.
- **`openai` optional extra** (resolved to 2.44.0, which accepts `http_client=`); added to dev.
- **Offline artifact:** `tests/fixtures/openai_chat.json` — a representative captured response
  the real `openai` SDK replays through the engine with zero network. `examples/openai_demo.py`
  is the runnable second-provider demo.

**Why it matters (positioning):** the interception lives at the httpx transport, so it was
already provider-neutral; the open question was whether the *schema* was. The same record→
replay→(fork) machinery now drives OpenAI unchanged — the abstraction is no longer "trust me
with one provider."

**Verified**
- `pytest` → **38 passed** (added: `test_openai.py` real-SDK record/replay + meta normalization;
  `test_adapters.py` anthropic/openai/unknown-host/streaming-body unit tests).
- `ruff check .` clean · `mypy src` clean (20 files).
- `python examples/openai_demo.py` → records + replays an OpenAI call identically, 0
  divergences, with normalized `gen_ai.*` meta. All Anthropic examples/tests still green.

---

## M4 — Timeline TUI + flagship demo · built 2026-06-29

The product surface: a scrubbable terminal timeline where the fork-and-fix loop is visible.

**What shipped**
- **`EideticApp`** (Textual) — three panes: STEPS (event log, kind-colored, `fork`/`!`
  markers) · DETAIL (input/output/meta of the highlighted step) · DIFF (state delta vs. the
  previous snapshot, reusing `json_diff`). ↑/↓ scrub, `r` reload, `q` quit.
- **`f` fork-and-run** — opens a modal prefilled with override JSON; on submit it runs
  `eidetic.fork(...)` with the supplied agent, then switches the view to the new child run.
  Without an agent (e.g. `eidetic ui <id>`) it warns instead of forking — honest about the
  CLI's inability to re-run arbitrary agent code.
- **`eidetic ui <run-id>`** CLI (lazy `textual` import → friendly error if the extra is
  missing) and **`eidetic.ui(run_id, agent=..., default_override=...)`** API.
- **Artifact:** [docs/timeline.svg](docs/timeline.svg) — a captured screenshot of the branched
  run (sensor `fork`-marked, classify showing `72 → "warm"`, the `verdict` diff, parent
  lineage). `examples/fork_demo_tui.py` is the interactive version.

**Decisions / gotchas**
- **Textual 8.2.7 has no `Static.renderable` accessor.** Rather than depend on widget
  internals, the app stashes the current panes' `Text` on `self.last_detail`/`self.last_diff`
  for tests/introspection.
- TUI tests run **headless via Textual's pilot**, wrapped in `asyncio.run` so there's no
  `pytest-asyncio` dependency.
- `f` is wired to `do_fork(at, override)` (also the tested entry point); the modal is the
  interactive front-end to it.

**Verified**
- `pytest` → **32 passed** (added: scrub updates detail+diff panes with correct content; `f`
  forks → linked child + view switches; no-agent fork warns, doesn't crash).
- `ruff check .` clean · `mypy src` clean (16 files).
- Generated `docs/timeline.svg` headlessly; `eidetic ui --help` works; all four
  non-interactive examples still green.

---

## M3 — Branching (the counterfactual hook) · built 2026-06-28

The novel feature: fork a run at step *k*, override that one event's output, and run the
tail live to explore "what if this step had gone differently?".

**What shipped**
- **`eidetic.fork(parent_id, at=k, override={"output": ...})`** — a context manager
  (mirrors `replay`). Re-run the agent inside it to drive the branch.
- **The mechanism is elegant reuse:** fork pre-builds the child's event log as the parent's
  events `0..k-1` copied verbatim plus event `k` with its **output blob swapped** for the
  override, then runs a `branch`-mode Session that replays seq ≤ k (so the agent reaches the
  fork point and receives the override) and goes **live** for seq > k. The *only* new engine
  surface is `Session.should_replay(seq)` returning `seq <= fork_at` in branch mode — the
  replay→live switch the M1/M2 seam anticipated.
- Override works for any fork-point kind: tool/LLM/retrieval (output → blob) and clock/RNG
  (scalar → `meta.value`). The overridden event is tagged `meta.overridden = True`.
- **Lineage:** child records `parent_run_id`, `forked_at_seq`, `overrides`; `eidetic ls`
  shows a "forked from" column. Branches are normal runs — themselves replayable and forkable.

**Decisions / gotchas**
- The prefix `0..k-1` is copied verbatim (blobs are content-addressed, so it's just event
  rows pointing at shared blobs). The agent still re-executes the prefix to rebuild in-memory
  state before the live tail — divergence in the prefix would be surfaced as usual.
- Snapshots are NOT pre-copied; the agent's `snapshot()` calls re-create them in the child as
  it runs (avoids `(run_id, after_seq)` collisions).
- **CLI `fork` deferred.** Like CLI `replay`, it needs to re-run the user's agent program,
  which requires an entry-point runner (`record -- <cmd>`) we haven't built. The library
  `fork()` is the first-class path; `eidetic ls` shows the resulting lineage.

**Verified**
- `pytest` → **29 passed** (added: override + live tail flips outcome, prefix determinism with
  a mid-run fork, branch is replayable, LLM-response override, out-of-range guard).
- `ruff check .` clean · `mypy src` clean (14 files).
- `python examples/fork_demo.py` → recorded `{'temp':30,'verdict':'cold'}`; fork@0 override
  72 → `{'temp':72,'verdict':'warm'}` (live re-classify); child linked to parent, re-replays
  identically with 0 divergences.

---

## M2 — State snapshots & diffs · built 2026-06-28

Made runs *inspectable*: capture document-shaped agent state over time and show what
changed between steps.

**What shipped**
- **`eidetic.snapshot(state, label=None)`** — stores a content-addressed (deduplicated)
  snapshot tagged with the seq of the most recent boundary (`after_seq`). No-op outside a
  session and on replay (recorded snapshots are authoritative).
- **Auto-snapshot** via `record(snapshot=lambda: agent.state)` — fires after every LLM
  event (`Session.record_event` hook), labelled `post-llm`.
- **Structural JSON diff** (`diff.py`) — RFC 6902-shaped ops (add/remove/replace over JSON
  Pointer paths, with `~0/~1` escaping); lists diffed positionally so an append shows as an
  `add` at the tail. Computed **lazily** (only when inspected). `diff_snapshots()` resolves
  the nearest snapshot at-or-before each requested step.
- **`eidetic diff <id> a b`** CLI — colored add/remove/replace render.

**Decisions / gotchas**
- **Windows console safety:** Rich/`print` fall back to legacy cp1252 on some Windows
  terminals, which can't encode `→`/`⚠`/`…`. Switched all CLI/example glyphs to ASCII
  (`->`, `(!)`, `...`). Keep CLI output ASCII-only.
- Snapshots are keyed `(run_id, after_seq)`; an explicit + auto snapshot at the same seq
  would collide (last wins). Fine for now; revisit if multi-snapshot-per-step is needed.
- Diff is intentionally a *structural* (not minimal-edit/LCS) diff — right for human
  timeline reading and growing message lists; not a minimal patch.

**Verified**
- `pytest` → **24 passed** (added: json_diff add/remove/replace + pointer escaping, snapshot
  dedup, cross-step diff, replay no-op, auto-snapshot-after-llm).
- `ruff check .` clean · `mypy src` clean (13 files).
- `python examples/stateful_agent.py` → records a state-growing agent, replays identically,
  prints the step 0→1 diff (`add /notes/1`, `replace /step`). `eidetic diff <id> 0 1` matches.

---

## M1 — Full boundary capture · built 2026-06-28

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

## M0 — Walking skeleton · built 2026-06-28

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
