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

- [ ] **M2 — State snapshots & diffs.** `eidetic.snapshot(state)` (+ optional auto-snapshot
  after each LLM event); content-addressed dedup of snapshots; lazy RFC 6902-shape JSON
  diff between steps; `eidetic show --step k` shows I/O, `eidetic diff <id> a b` shows the
  state delta.
  **Test:** record an agent that mutates a state dict across steps; `eidetic diff <id> 2 3`
  prints the add/remove/replace ops; identical adjacent states share one blob on disk.

## Phase 2 — The novel hook

- [ ] **M3 — Branching (counterfactual).** `eidetic.fork(run_id, at=k, override=…)` and
  `eidetic fork <id> --at k --override-tool '…'`: replay events `0..k-1`, substitute the
  override as event `k`'s output, then flip to **live** for `seq > k`, recording a new child
  run (`parent_run_id`, `forked_at_seq`, `overrides`). Branches are themselves replayable.
  **Test:** fork a recorded failing run at the bad step, override that one tool result, and
  the branched run completes differently; `eidetic ls` shows the child linked to its parent.

## Phase 3 — The product

- [ ] **M4 — Timeline TUI + flagship demo.** A Textual three-pane app (`eidetic ui <id>`):
  steps list · message/tool I/O detail · state diff; `f` to fork. Polish divergence display.
  Build `examples/weather_agent.py` (picks the wrong tool) and record the fork-and-fix gif.
  **Test:** `eidetic ui <id>` opens; arrow keys scrub; selecting a step shows its I/O and the
  diff vs. the previous snapshot; `f` forks and the new run appears.

## Phase 4 — Reach (stretch; pick by signal)

- [ ] **M5 — Beyond v1.** OpenAI adapter (validates the provider-agnostic schema) · OTel
  `gen_ai.*` span export · `MongoStore` (`eidetic[mongo]`) · shareable/exportable trace
  bundles · minimal web timeline.
  **Test:** per sub-feature — e.g. record an OpenAI `chat.completions` call and replay it
  deterministically through the same engine.

---

**North star:** a developer records a failing agent run, scrubs the timeline to the
step where it went wrong, forks-and-overrides that single decision, and watches the
branched run succeed — all reproduced bit-for-bit from one local trace. If that loop
feels effortless, Eidetic is good.
