"""Record a REAL Google Gemini call, prove it replays offline, and commit the trace as a bundle.

Needs `GEMINI_API_KEY` (free from Google AI Studio — no credit card) + network. Run once:

    ./.venv/Scripts/python.exe examples/live_gemini_record.py

The resulting `examples/fixtures/real_gemini_run.zip` reproduces that exact real run **offline
forever** (see tests/test_real_run.py) — no key, no network. Companion to `live_record.py`
(Anthropic); together they show the same engine driving two different real providers.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import httpx

import eidetic
from eidetic.store.local import LocalStore

sys.path.insert(0, str(Path(__file__).parent))
import live_gemini_agent  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "real_gemini_run.zip"


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay — determinism broken!")


def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set — get a free key at aistudio.google.com/apikey, then re-run.")
        raise SystemExit(2)

    store = LocalStore(tempfile.mkdtemp())
    try:
        with eidetic.record("real-gemini", store=store) as rec:
            reply = live_gemini_agent.run()  # <-- real call to generativelanguage.googleapis.com
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        print(f"Gemini returned HTTP {code} for model '{live_gemini_agent.MODEL}'.")
        if code == 429:
            print("  Rate-limited — wait a minute (free tier is strict) and retry, or run from a")
            print("  non-shared network. Free-tier quotas reset over time.")
        elif code == 404:
            print("  Model not available to this key — pick another from `models.list` and set")
            print("  MODEL in examples/live_gemini_agent.py (e.g. gemini-flash-latest).")
        raise SystemExit(1) from exc
    print(f"recorded REAL Gemini run {rec.run_id}: model said {reply!r}")

    with eidetic.replay(rec.run_id, store=store) as rep:
        reply2 = live_gemini_agent.run(inner=httpx.MockTransport(_forbidden))
    assert reply == reply2 and not rep.divergences, (reply, reply2, rep.divergences)
    print(f"offline replay reproduced it byte-for-byte (divergences={rep.divergences})")

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    eidetic.export_bundle(rec.run_id, FIXTURE, store=store)
    size = FIXTURE.stat().st_size
    print(f"committed artifact: examples/fixtures/{FIXTURE.name} ({size:,} bytes)")


if __name__ == "__main__":
    main()
