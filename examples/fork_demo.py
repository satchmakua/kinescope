"""M3 showcase: the fork-and-fix counterfactual, fully offline.

A tiny agent reads a sensor, then classifies the reading. In the recorded run the sensor
returns a faulty value (30) and the agent concludes "cold". We `fork` at the sensor step,
**override just that one output** to the correct value (72), and the downstream `classify`
tool re-runs *live* — flipping the conclusion to "warm". One event changed; everything
after it recomputed. The child run is linked to its parent and is itself replayable.

Run:  python examples/fork_demo.py
"""

from __future__ import annotations

import kinescope
from kinescope.store.local import LocalStore

FAULTY_READING = 30  # the bug in the recorded run


@kinescope.tool
def sensor(city: str) -> int:
    return FAULTY_READING


@kinescope.tool
def classify(temp: int) -> str:
    return "cold" if temp < 50 else "warm"


def agent() -> dict:
    temp = sensor("Paris")  # seq 0
    return {"temp": temp, "verdict": classify(temp)}  # classify = seq 1


def main() -> None:
    store = LocalStore(".kinescope")

    with kinescope.record("weather", store=store) as rec:
        original = agent()
    print(f"recorded run {rec.run_id}: {original}")  # {'temp': 30, 'verdict': 'cold'}

    # Fork at step 0 (the sensor read), override its output to the correct value.
    with kinescope.fork(rec.run_id, at=0, override={"output": 72}, store=store) as br:
        branched = agent()
    print(f"branched run {br.run_id}: {branched}")  # {'temp': 72, 'verdict': 'warm'}

    # The classify step after the fork re-ran LIVE with the corrected input.
    events = store.events(br.run_id)
    summary = [(e.seq, e.name, e.meta.get("overridden", False)) for e in events]
    print(f"  child events : {summary}")
    print(f"  parent       : {br.run.parent_run_id} @ fork {br.run.forked_at_seq}")

    # A branch is just another run — replay it deterministically.
    with kinescope.replay(br.run_id, store=store) as rep:
        replayed = agent()
    assert replayed == branched and not rep.divergences
    print(f"  re-replayed  : {replayed} (branches are replayable; divergences={rep.divergences})")


if __name__ == "__main__":
    main()
