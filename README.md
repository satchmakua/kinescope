# Eidetic

> `rr` for nondeterministic AI agents — capture every nondeterministic input so any run replays deterministically, *and* can be branched: "what if the model had chosen the other tool here?"

Eidetic records the nondeterministic frontier of an agent (LLM calls, tool calls, clock, RNG/UUID, retrieval), replays any run deterministically from the trace, and lets you **fork** at any step — override one recorded event and resume *live* — to explore counterfactuals. A Textual timeline lets you scrub steps, inspect message/tool I/O and state diffs, and fork with one key.

**The demo:** an agent fails a task; you scrub to the step where it picked the wrong tool, fork and override just that decision, and watch the branched run complete — fully reproducible from the recording.

- Local-first: `.eidetic/` (SQLite index + content-addressed blobs), no external services.
- Tiny core (depends on `httpx`); `anthropic`, CLI, TUI, and Mongo are optional extras.
- First adapter: Anthropic Messages API, intercepted at the httpx transport (sync + async, streaming).

**Status:** design draft — see [DESIGN.md](DESIGN.md). Run `/scaffold` to build.
