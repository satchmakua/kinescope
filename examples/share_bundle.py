"""Share a recorded run as a portable bundle, then replay it in a fresh store — offline.

Demonstrates handing a failing run to someone else: export to a zip, import on the other
side, and it replays (and forks) bit-for-bit.

Run:  python examples/share_bundle.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import kinescope
from kinescope.store.local import LocalStore


@kinescope.tool
def lookup(city: str) -> int:
    return {"Paris": 30, "Cairo": 95}[city]


def agent() -> dict:
    state: dict = {"reading": None}
    kinescope.snapshot(state, "start")
    state["reading"] = lookup("Paris")
    kinescope.snapshot(state, "read")
    return state


def main() -> None:
    work = Path(tempfile.mkdtemp())
    src = LocalStore(work / "src")
    with kinescope.record("trip", store=src) as rec:
        original = agent()
    print(f"recorded {rec.run_id} in src store: {original}")

    bundle = work / "trip.zip"
    kinescope.export_bundle(rec.run_id, bundle, store=src)
    print(f"exported bundle: {bundle.name} ({bundle.stat().st_size:,} bytes)")

    dst = LocalStore(work / "dst")  # a completely separate store (think: another machine)
    run_id = kinescope.import_bundle(bundle, store=dst)
    with kinescope.replay(run_id, store=dst) as rep:
        replayed = agent()
    assert replayed == original and not rep.divergences
    print(f"imported into a fresh store and replayed identically: {replayed} "
          f"(divergences={rep.divergences})")


if __name__ == "__main__":
    main()
