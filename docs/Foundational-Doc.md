# Eidetic — Foundational Document

**Working codename:** Eidetic (eidetic memory = perfect total recall — what record-replay gives you; rename freely)
**One line:** `rr` for nondeterministic agents — capture every nondeterministic input so any run replays deterministically, *and* can be branched: "what if the model had chosen the other tool here?"
**Status:** Pre-implementation. Read fully before coding.

---

## 1. Thesis
Debugging agents today is archaeology through logs, made worse by nondeterminism (sampled model outputs, flaky tools, timing). Eidetic is the systems-engineering answer: record every nondeterministic boundary, replay any run bit-for-bit, and **fork counterfactuals** at any step. This is the **broadest-adoption** project of the set — *everyone* building agents has this pain — and it carries a strong record-replay/determinism lineage (rr, Pernosco) that signals real systems depth.

**Proves:** systems engineering (deterministic record-replay, interception, state capture), agentic-AI fluency, and product taste for a pain everyone feels. The counterfactual **branching** is the novel hook beyond plain tracing.

---

## 2. Scope discipline
**In scope (v1):**
- A record/replay library wrapping an agent's nondeterministic boundaries: **LLM calls, tool calls, clock, RNG, retrieval**.
- A **recorder**: ordered event log (inputs + outputs of each nondeterministic call) + periodic agent **state snapshots** (JSON; document-shaped).
- **Deterministic replay**: re-run feeding recorded outputs instead of calling out → reproducible execution.
- **Branching/counterfactual**: fork at step k, override one recorded event (swap a tool result or force an alternate completion), then switch from replay → live forward.
- A **timeline view** (CLI first, minimal web UI as stretch) to scrub steps and inspect messages/tool I/O/state diffs.

**Out of scope (v1, state in README):** distributed multi-agent at scale, automatic root-causing, reproducing provider-side sampling internals (handled by recording *outputs*, not re-deriving them). Single-agent, single-process to start.

**Honesty framing:** determinism is guaranteed at recorded boundaries; a **divergence detector** flags any hidden nondeterminism that escapes the shims.

---

## 3. Approach
1. **Interception layer** — shim the LLM client + tool registry + clock + RNG; each call emits a recorded event (input hash + output) to the log.
2. **Trace store** — ordered event log + periodic state snapshots; flat files or a document DB (recommended — pairs with the author's stack).
3. **Replay engine** — re-execute the agent; at each boundary return the recorded output rather than calling out → deterministic replay; compare against recording to detect divergence.
4. **Branch engine** — pick step k, mutate one event, then flip from replay to live for all subsequent calls → explore the counterfactual path.
5. **Timeline** — scrub events; per step show messages, tool calls, and state diff; fork button.

```
record:  agent ──► [LLM/tool/clock/RNG shims] ──► event log + state snapshots
replay:  agent ──► shims return recorded outputs ──► deterministic run (+divergence check)
branch:  fork@k → override one event → replay up to k, go LIVE after k → counterfactual run
view:    timeline scrub | per-step state diff | fork
```

---

## 4. Repo layout
```
eidetic/
  src/eidetic/
    intercept.py      # shims for LLM client, tool registry, clock, RNG
    record.py         # event log + state snapshots (serialization)
    replay.py         # deterministic replay + divergence detection
    branch.py         # fork@k, event override, replay→live switch
    store.py          # trace storage (files or document DB)
    timeline.py       # CLI scrub/inspect; (web UI = stretch)
    cli.py            # `eidetic record run.py` / `eidetic replay <id>` / `eidetic fork <id> --at 7`
  examples/           # sample agents + a recorded failing run
  tests/
  README.md           # lead with the replay+branch demo (gif)
  ROADMAP.md
```

---

## 5. Milestones
- **M0 — Record + replay:** intercept boundaries, log events, replay a simple agent deterministically. Ship skeleton.
- **M1 — State snapshots + diffs:** per-step state capture and diff view. 
- **M2 — Branching:** fork at step k, override one event, run forward live. *This is the novel-hook milestone.*
- **M3 — Timeline + demo:** scrub/fork UI (CLI ok) + the flagship demo below; add divergence detection.
- **M4 (stretch):** web timeline UI, shareable/exportable traces, multi-agent.

**Ship publicly at M1–M3.**

---

## 6. The demo that lands
An agent fails a task. Eidetic replays the failure deterministically; you scrub to the step where it picked the wrong tool, **fork and override just that one decision**, and watch the branched run complete successfully — fully reproducible from the recorded trace. A timeline gif of the fork-and-fix is the entire pitch.

---

## 7. Key decisions for next session
1. Interception mechanism (monkeypatch vs adapter/proxy vs explicit hooks) and which agent/LLM client to target first.
2. Event schema + state-snapshot granularity (every step vs checkpoints).
3. Storage: flat files vs document DB (recommend document DB — ties to the author's stack and is naturally document-shaped).
4. Divergence-detection policy and v1 timeline surface (CLI vs minimal web).

---

## 8. Positioning notes
- Frame as **"deterministic record-replay and counterfactual debugging for AI agents."**
- Broadest utility of the set — the "people actually use it" play; a used repo can outweigh an admired one.
- Strong systems signal (rr/Pernosco lineage); the branching counterfactual is what makes it more than a tracer.
- Lower formal-methods content than Congruent/Inductor/Manifold — deliberately the *adoption* anchor alongside those *differentiation* anchors.

---
*Next session: M0 — implement the interception + record/replay loop on a simple agent, then add M1 state snapshots.*
