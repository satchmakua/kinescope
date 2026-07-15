"""Flagship demo: scrub the timeline and fork-and-fix in the TUI.

Records a weather agent that reaches the wrong verdict ("cold") from a faulty sensor
reading, then opens the timeline. Scrub to step 0 (the sensor read), press `f`, accept
the prefilled override `{"output": 72}`, and watch the downstream classify re-run live —
flipping the verdict to "warm". Press `q` to quit.

Run:  python examples/fork_demo_tui.py
"""

from __future__ import annotations

import kinescope
from kinescope.store.local import LocalStore

FAULTY_READING = 30


@kinescope.tool
def sensor(city: str) -> int:
    return FAULTY_READING


@kinescope.tool
def classify(temp: int) -> str:
    return "cold" if temp < 50 else "warm"


def agent() -> dict:
    state: dict = {"city": "Paris", "reading": None, "verdict": None}
    kinescope.snapshot(state, "start")
    state["reading"] = sensor("Paris")
    kinescope.snapshot(state, "sensed")
    state["verdict"] = classify(state["reading"])
    kinescope.snapshot(state, "classified")
    return state


def main() -> None:
    store = LocalStore(".kinescope")
    with kinescope.record("weather", store=store) as rec:
        agent()
    print(f"Recorded {rec.run_id} (verdict: cold).")
    print("Opening the timeline — scrub to step 0, press 'f', accept {\"output\": 72},")
    print("and watch the verdict flip to 'warm'. Press 'q' to quit.\n")
    kinescope.ui(rec.run_id, store=store, agent=agent, default_override={"output": 72})


if __name__ == "__main__":
    main()
