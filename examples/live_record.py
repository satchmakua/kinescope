"""Record a REAL Anthropic call, prove it replays offline, and commit the trace as a bundle.

This is the one place Kinescope touches a live model. Needs `ANTHROPIC_API_KEY` + network.
Run once to (re)generate the artifact:

    ./.venv/Scripts/python.exe examples/live_record.py

The resulting `examples/fixtures/real_anthropic_run.zip` then reproduces that exact real run
**offline forever** — no key, no network — via `tests/test_real_run.py`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

import kinescope
from kinescope.store.local import LocalStore

sys.path.insert(0, str(Path(__file__).parent))
import live_agent  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "real_anthropic_run.zip"


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay — determinism broken!")


def main() -> None:
    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set in this environment — set it and re-run.")
        raise SystemExit(2)

    store = LocalStore(tempfile.mkdtemp())  # transient; the committed bundle is the artifact
    with kinescope.record("real-anthropic", store=store) as rec:
        reply = live_agent.run()  # <-- the real network call to api.anthropic.com
    print(f"recorded REAL run {rec.run_id}: Claude said {reply!r}")

    with kinescope.replay(rec.run_id, store=store) as rep:
        reply2 = live_agent.run(inner=httpx.MockTransport(_forbidden))
    assert reply == reply2 and not rep.divergences, (reply, reply2, rep.divergences)
    print(f"offline replay reproduced it byte-for-byte (divergences={rep.divergences})")

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    kinescope.export_bundle(rec.run_id, FIXTURE, store=store)
    size = FIXTURE.stat().st_size
    print(f"committed artifact: examples/fixtures/{FIXTURE.name} ({size:,} bytes)")
    print("-> reproduce it offline any time with:  pytest tests/test_real_run.py")


if __name__ == "__main__":
    main()
