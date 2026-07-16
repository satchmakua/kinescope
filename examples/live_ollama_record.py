"""Record a REAL local Ollama call, prove it replays offline, and commit the trace as a bundle.

The cheapest reality-contact there is: a **local** model — no API key, no quota, no network.
Requires Ollama running with the model pulled (see `live_ollama_agent.py`). Run once:

    ./.venv/Scripts/python.exe examples/live_ollama_record.py

The resulting `examples/fixtures/real_ollama_run.zip` reproduces that exact real run **offline
forever** (see tests/test_real_run.py). Companion to `live_record.py` (Anthropic).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

import kinescope
from kinescope.store.local import LocalStore

sys.path.insert(0, str(Path(__file__).parent))
import live_ollama_agent  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "real_ollama_run.zip"


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay — determinism broken!")


def _server_ready() -> bool:
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=5).raise_for_status()
        return True
    except Exception:
        return False


def main() -> None:
    if not _server_ready():
        print("Ollama isn't reachable at localhost:11434 — start it with `ollama serve`,")
        print(f"and pull the model:  ollama pull {live_ollama_agent.MODEL}")
        raise SystemExit(2)

    store = LocalStore(tempfile.mkdtemp())  # transient; the committed bundle is the artifact
    with kinescope.record("real-ollama", store=store) as rec:
        reply = live_ollama_agent.run()  # <-- real call to the local Ollama server
    print(f"recorded REAL Ollama run {rec.run_id}: {live_ollama_agent.MODEL} said {reply!r}")

    with kinescope.replay(rec.run_id, store=store) as rep:
        reply2 = live_ollama_agent.run(inner=httpx.MockTransport(_forbidden))
    assert reply == reply2 and not rep.divergences, (reply, reply2, rep.divergences)
    print(f"offline replay reproduced it byte-for-byte (divergences={rep.divergences})")

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    kinescope.export_bundle(rec.run_id, FIXTURE, store=store)
    size = FIXTURE.stat().st_size
    print(f"committed artifact: examples/fixtures/{FIXTURE.name} ({size:,} bytes)")
    print("-> reproduce it offline any time with:  pytest tests/test_real_run.py")


if __name__ == "__main__":
    main()
