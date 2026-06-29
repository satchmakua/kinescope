# Eidetic

> `rr` for nondeterministic AI agents — capture every nondeterministic input so any run replays deterministically, *and* can be branched: "what if the model had chosen the other tool here?"

Eidetic records the **nondeterministic frontier** of an agent (LLM calls, tool calls, clock, RNG/UUID, retrieval), replays any run **deterministically** from the trace, and lets you **fork** at any step — override one recorded event and resume *live* — to explore counterfactuals. A Textual timeline lets you scrub steps, inspect message/tool I/O and state diffs, and fork with one key.

**The demo:** an agent fails a task; you scrub to the step where it picked the wrong tool, fork and override just that decision, and watch the branched run complete — fully reproducible from the recording.

- **Local-first:** traces live in `.eidetic/` (SQLite index + content-addressed blobs). No external services.
- **Tiny core:** the engine depends on `httpx` only; `anthropic`, the CLI, the TUI, and Mongo are optional extras.
- **First adapter:** the Anthropic Messages API, intercepted at the httpx transport (provider-agnostic event schema; OpenAI next).

**Status:** **M0–M2 shipped** — deterministic record→replay across the full nondeterministic frontier (LLM calls — sync, async, SSE streaming; `@eidetic.tool` calls; opt-in clock/RNG/UUID), an honest divergence detector, and state snapshots with per-step diffs. See [ROADMAP.md](ROADMAP.md) for the plan and [PROGRESS.md](PROGRESS.md) for what's done.

---

## Run it

**Prerequisites:** Python ≥ 3.11 (check: `python --version`).

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"        # core + anthropic + cli + tui + test tooling
```

See the record→replay loop end-to-end (offline — no API key, no network):

```powershell
python examples\record_demo.py     # records one Anthropic call, then replays it deterministically
python examples\tool_agent.py      # a tool + clock + RNG + LLM agent, recorded and replayed
python examples\stateful_agent.py  # snapshots state across steps, then diffs it
eidetic ls                         # list recorded runs
eidetic show <run-id> [--step k]   # inspect a run's events and I/O
eidetic diff <run-id> <a> <b>      # state diff between two steps
```

Both examples use the real Anthropic SDK wired through an Eidetic transport with a stub
inner transport, so they record and replay with no network and no key — and replay
provably never touches the network.

### Use it in your own agent

```python
import anthropic, eidetic

@eidetic.tool                              # tool calls are recorded boundaries
def get_weather(city: str) -> dict:
    ...

def run_agent():
    client = anthropic.Anthropic(http_client=eidetic.http_client())
    msg = client.messages.create(
        model="claude-opus-4-8", max_tokens=256,
        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
    )
    return msg

# capture=[...] also records direct clock/RNG/UUID use (opt-in; off by default)
with eidetic.record("paris", capture=["clock", "rng"]) as rec:
    run_agent()

with eidetic.replay(rec.run_id) as rep:    # reproduce, offline & deterministic
    run_agent()
assert not rep.divergences
```

For async agents use `eidetic.async_http_client()` with `anthropic.AsyncAnthropic`.
Streaming (`messages.stream(...)`) is captured and replayed automatically.

### Commands

| Command | What it does |
|---|---|
| `python examples\record_demo.py` | Run the offline record→replay demo |
| `eidetic ls` | List recorded runs |
| `eidetic show <id> [--step k]` | Inspect a run's events / per-step I/O |
| `pytest` | Run the tests |
| `ruff check . && mypy src` | Lint + typecheck |

---

## How to give feedback

You mainly **test and report**:

- Describe what happened in plain language.
- Paste any errors verbatim (the single most useful thing).
- Screenshots for anything visual (the TUI, once it lands).

Every milestone in [ROADMAP.md](ROADMAP.md) ends with explicit **Test** steps.

---

## Project docs

| Doc | What's in it |
|---|---|
| [DESIGN.md](DESIGN.md) | The full design and rationale — the single source of truth. |
| [ROADMAP.md](ROADMAP.md) | The milestone checklist (the plan + what's done). |
| [PROGRESS.md](PROGRESS.md) | Build log: what shipped each milestone and why. |
| [`docs/`](docs/) | Deeper docs and architecture decisions (ADRs). |
| [Eidetic-Foundational-Doc.md](Eidetic-Foundational-Doc.md) | The original thesis the design grew from. |

## Tech stack

Python 3.11+ · `httpx` transport interception · `anthropic` 0.112 (first adapter) · SQLite + content-addressed blobs · Typer (CLI) · Textual (TUI). Hexagonal/ports-and-adapters around a deterministic core.

## License

MIT — see [LICENSE](LICENSE).
