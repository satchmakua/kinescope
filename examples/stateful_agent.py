"""M2 showcase: snapshot document-shaped agent state across steps, then diff it.

A tiny research agent grows a `notes` document as it calls a tool. We snapshot the state
after each step; replay reproduces the run deterministically, and `eidetic.diff_snapshots`
(also `eidetic diff <id> a b` on the CLI) shows the per-step state delta.

Run:  python examples/stateful_agent.py
"""

from __future__ import annotations

import eidetic
from eidetic.store.local import LocalStore


@eidetic.tool
def fetch(topic: str) -> dict:
    return {"topic": topic, "fact": f"{topic} is interesting"}


def agent() -> dict:
    state: dict = {"step": 0, "notes": []}
    eidetic.snapshot(state, "start")
    for topic in ("comets", "tides"):
        result = fetch(topic)
        state["step"] += 1
        state["notes"].append(result["fact"])
        eidetic.snapshot(state, f"after-{topic}")
    return state


def main() -> None:
    store = LocalStore(".eidetic")
    with eidetic.record("research", store=store) as rec:
        final = agent()
    run_id = rec.run_id

    with eidetic.replay(run_id, store=store) as rep:
        replayed = agent()
    assert final == replayed and not rep.divergences

    snaps = store.snapshots(run_id)
    print(f"recorded run : {run_id}")
    print(f"snapshots    : {[(s.after_seq, s.label) for s in snaps]}")
    print("state diff step 0 -> 1 (after-comets -> after-tides):")
    for op in eidetic.diff_snapshots(store, run_id, 0, 1):
        value = "" if op["op"] == "remove" else f"  {op['value']!r}"
        print(f"  {op['op']:<7} {op['path']}{value}")


if __name__ == "__main__":
    main()
