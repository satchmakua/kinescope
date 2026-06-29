# ROADMAP — Eidetic

The milestone checklist. Standing instruction: **"continue"** → build the next
unchecked milestone.

**Rules of the road:**
- Each milestone is an **independently runnable** slice — something the human can
  actually test, not an internal-only refactor.
- Every milestone ends with explicit **Test** steps: what to do and what should
  happen. These are the acceptance criteria.
- Build **top-down**: a thin end-to-end slice first, then deepen. Counts and scopes
  are budgets, not promises — split a milestone if it grows too big.
- Check a box **only after the human confirms its Test passes**, then add a
  `PROGRESS.md` entry.

See [DESIGN.md](DESIGN.md) for the full rationale behind each milestone.

---

## Phase 0 — Walking skeleton

- [x] **M0 — Skeleton & it runs.** The deterministic record→replay loop end-to-end on
  the simplest agent: an `httpx`-transport shim captures one Anthropic `messages.create`
  to a local SQLite + content-addressed blob store; `eidetic.replay()` re-runs the agent
  returning the recorded completion with no network; `eidetic ls`/`show` inspect it.
  Lint/typecheck/tests wired up.
  **Test:** `python examples\record_demo.py` → prints a run id and "replayed: identical";
  `pytest` → green; `eidetic ls` → shows the run. _(verified at scaffold time; awaiting human confirm)_

## Phase 1 — The full nondeterministic frontier

- [x] **M1 — Full boundary capture + ordering + divergence.** Added the `@eidetic.tool`
  decorator and `instrument_tools(registry)`; opt-in scoped monkeypatch of clock/RNG/UUID
  (`time`, `random`, `uuid`) via `record(capture=...)`; **async** transport sibling
  (`async_http_client`); **SSE streaming** capture & re-materialization; a real divergence
  detector (strict/warn/off) covering input/kind/extra/missing mismatches; nested
  boundaries inside a tool are suppressed. Replays a multi-step tool-using agent
  deterministically.
  **Test:** `python examples\tool_agent.py` → records a tool + clock + RNG + LLM agent and
  replays it identically with 0 divergences; `pytest` → green (tools, stdlib, async,
  streaming, divergence). _(verified at build time; awaiting human confirm)_

- [x] **M2 — State snapshots & diffs.** `eidetic.snapshot(state)` + optional auto-snapshot
  after each LLM event (`record(snapshot=...)`); content-addressed dedup of snapshots; lazy
  RFC 6902-shape JSON diff (`eidetic.json_diff` / `diff_snapshots`); `eidetic diff <id> a b`
  shows the state delta using the nearest preceding snapshots. Snapshot is a no-op on replay.
  **Test:** `python examples\stateful_agent.py` → records a state-mutating agent, replays it
  identically, and prints the per-step diff; `eidetic diff <id> 0 1` prints add/replace ops;
  `pytest` → green (dedup, diff, auto-snapshot). _(verified at build time; awaiting human confirm)_

## Phase 2 — The novel hook

- [x] **M3 — Branching (counterfactual).** `eidetic.fork(run_id, at=k, override={"output": …})`:
  copies events `0..k-1`, swaps event `k`'s output for the override, replays that prefix, then
  flips to **live** for `seq > k`, recording a new child run (`parent_run_id`, `forked_at_seq`,
  `overrides`). Works for tool / LLM / clock / RNG fork points. Branches are themselves
  replayable; `eidetic ls` shows the lineage. (CLI `fork` subcommand deferred — it needs an
  agent entry-point runner, same as CLI `replay`.)
  **Test:** `python examples\fork_demo.py` → records a faulty-sensor agent ("cold"), forks at
  the sensor step, overrides the reading, and the live re-classify flips it to "warm"; the
  child is linked to its parent and re-replays identically. `pytest` → green (override + live
  tail, prefix determinism, replayable branch, LLM override, range check).

## Phase 3 — The product

- [x] **M4 — Timeline TUI + flagship demo.** A Textual three-pane app (`eidetic ui <id>` /
  `eidetic.ui(run_id, agent=...)`): steps list (fork/divergence markers) · detail (input/
  output/meta) · state diff vs. previous snapshot; ↑/↓ scrub, `f` fork-and-run-live. Captured
  a timeline screenshot ([docs/timeline.svg](docs/timeline.svg)); `examples/fork_demo_tui.py`
  is the interactive fork-and-fix.
  **Test:** `pytest tests/test_tui.py` (headless via Textual pilot) → scrubbing updates the
  detail/diff panes; `f` with an agent forks, creates a linked child, and the app switches to
  it; `f` without an agent warns instead of crashing. _(verified at build time; awaiting human confirm)_

## Phase 4 — Reach (stretch; pick by signal)

- [~] **M5 — Beyond v1.** OpenAI adapter (shipped as **H1**) ✓ · **OTel `gen_ai.*` span
  export** ✓ (`eidetic.export_otel` / `eidetic export-otel`) · **`MongoStore`** ✓
  (`eidetic[mongo]` — a document-DB backend; the same record/replay/fork engine runs against
  it unchanged, proving the `TraceStore` port generalizes; tested hermetically with mongomock) ·
  **shareable trace bundles** ✓ (`eidetic.export_bundle`/`import_bundle`, `eidetic export`/`import`:
  zip a run's events+snapshots+blobs; imports into any store and stays replayable/forkable —
  stdlib-only). Remaining: minimal web timeline (deprioritized vs. the TUI).
  **Test:** `pytest tests/test_otel.py tests/test_mongo.py tests/test_bundle.py` → green;
  `python examples\share_bundle.py` → export→import→replay across stores. _(verified; awaiting human confirm)_

---

**North star:** a developer records a failing agent run, scrubs the timeline to the
step where it went wrong, forks-and-overrides that single decision, and watches the
branched run succeed — all reproduced bit-for-bit from one local trace. If that loop
feels effortless, Eidetic is good.

---

## Review-driven hardening — from *built* to *proven* (added 2026-06-28)

> Added after an external code review (captured in `../ai-docs/project_eval/`). M3
> branching — the differentiator — is now **done**; these items prove the abstraction
> generalizes and stress the determinism guarantee the whole product rests on.
> **Standing rule:** a milestone is checked only when it has produced **one real,
> captured, reproducible artifact**, not merely passing unit tests.

**Definition of Done — the "Sparkle Bar"** (applies to every milestone):
1. **Real artifact captured** — produced against reality, pinned at the top of the README with the exact reproduce command.
2. **Flagship demo in one screen** — the named demo shipped as a screenshot/gif.
3. **Stress-tested** — property-based + failure-path + one scale test on the invariant-critical core, not just happy-path units.
4. **Honest numbers** — CIs/bounds, a named baseline, an explicit "can't do" list.
5. **Cold-clone reproducible** — pinned deps, fixed seeds, one `make demo`, CI runs the real-or-recorded path.
6. **Polished** — no stray files, consistent docs, README opens with the artifact.
7. **Positioned** — one paragraph: who it's for, what it beats, why this not the obvious alternative.

**Hardening items (Eidetic-specific):**
- [x] **H1 — Promote the OpenAI adapter out of "stretch" (M5 → now).** It is the only real test that the event schema is genuinely **provider-agnostic** — the abstraction is unproven with one provider. *Accept:* an OpenAI `chat.completions` call records + replays through the same engine with **no core schema change**; a recorded fixture proves it offline. **Done:** provider normalizers live in `src/eidetic/adapters/` (dispatch by host, JSON-only, no SDK needed); the engine's only change was moving the hardcoded `gen_ai.system` into the adapter. The real `openai` 2.x SDK records+replays via `tests/fixtures/openai_chat.json` offline (`examples/openai_demo.py`, `tests/test_openai.py`); OpenAI `prompt/completion_tokens` normalize to the same `gen_ai.usage.*` as Anthropic's `input/output_tokens`. _(awaiting human confirm)_
- [x] **H2 — Determinism stress suite.** The product *is* correctness-of-replay — tested adversarially in `tests/test_stress.py`: sequential **async** boundaries replay deterministically; **concurrent** (`asyncio.gather`) boundaries are never silently wrong (identical-or-flagged); boundary **reordering** and **hidden nondeterminism** are flagged; a **randomized property** check (25 random agents) replays faithfully; a **10k-event** scale run reproduces exactly. Also found+fixed a perf bug (per-event SQLite commit) and pinned the contextvar/thread capture limit. *Accept:* all pass; throughput documented (~10k inline events record+replay in <1s; see PROGRESS). _(verified at build time; awaiting human confirm)_
- [ ] **H3 — Ship the flagship gif (with M4).** The fork-and-fix gif leads the README; `make demo` reproduces the branched run offline.
