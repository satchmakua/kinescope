"""Real-run reproducibility (the reality-contact proof): a genuine Anthropic call, recorded
once against the live API by `examples/live_record.py` and committed as a bundle, replays
here **offline** with a forbidden network transport — 0 divergences.

Skips cleanly if the bundle hasn't been generated yet (it needs a key, once)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

import kinescope
from kinescope.store.local import LocalStore

EXAMPLES = Path(__file__).parent.parent / "examples"
BUNDLE = EXAMPLES / "fixtures" / "real_anthropic_run.zip"
GEMINI_BUNDLE = EXAMPLES / "fixtures" / "real_gemini_run.zip"
sys.path.insert(0, str(EXAMPLES))


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay of a recorded real run")


@pytest.mark.skipif(
    not BUNDLE.exists(),
    reason="run examples/live_record.py once (needs ANTHROPIC_API_KEY) to generate the bundle",
)
def test_real_anthropic_run_replays_offline(tmp_path):
    import live_agent

    store = LocalStore(tmp_path / ".kinescope")
    run_id = kinescope.import_bundle(BUNDLE, store=store)

    with kinescope.replay(run_id, store=store) as rep:
        reply = live_agent.run(inner=httpx.MockTransport(_forbidden))

    assert rep.divergences == []
    assert isinstance(reply, str) and reply  # the real completion came back from the trace

    llm_events = [e for e in store.events(run_id) if e.kind == "llm"]
    assert len(llm_events) == 1
    assert llm_events[0].meta.get("gen_ai.system") == "anthropic"


@pytest.mark.skipif(
    not GEMINI_BUNDLE.exists(),
    reason="run examples/live_gemini_record.py once (needs GEMINI_API_KEY) to generate the bundle",
)
def test_real_gemini_run_replays_offline(tmp_path):
    import live_gemini_agent

    store = LocalStore(tmp_path / ".kinescope")
    run_id = kinescope.import_bundle(GEMINI_BUNDLE, store=store)

    with kinescope.replay(run_id, store=store) as rep:
        reply = live_gemini_agent.run(inner=httpx.MockTransport(_forbidden))

    assert rep.divergences == []
    assert isinstance(reply, str) and reply
    llm_events = [e for e in store.events(run_id) if e.kind == "llm"]
    assert len(llm_events) == 1
    assert llm_events[0].meta.get("gen_ai.system") == "gcp.gemini"
