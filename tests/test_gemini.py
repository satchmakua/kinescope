"""Third provider, free & offline: the SAME engine records and replays a Google Gemini
`generateContent` call — a materially different wire shape (model in the URL, different token
fields, uppercase finish reason) — proving the schema generalizes beyond OpenAI's close
cousinhood to Anthropic. No key, no network (canned fixture over a MockTransport)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

import kinescope
from kinescope.store.local import LocalStore

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "gemini_generate.json").read_text())
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay")


def _call(inner: httpx.MockTransport) -> str:
    client = kinescope.http_client(inner=inner)
    body = {"contents": [{"role": "user", "parts": [{"text": "what planet?"}]}]}
    resp = client.post(URL, json=body)
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def test_gemini_records_and_replays_through_same_engine(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=FIXTURE))
    with kinescope.record("gemini", store=store) as rec:
        out1 = _call(canned)
    with kinescope.replay(rec.run_id, store=store) as rep:
        out2 = _call(httpx.MockTransport(_forbidden))
    assert out1 == out2 == "Earth."
    assert rep.divergences == []


def test_gemini_response_is_normalized_to_gen_ai_meta(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=FIXTURE))
    with kinescope.record("gemini", store=store) as rec:
        _call(canned)
    meta = store.events(rec.run_id)[0].meta
    assert meta["gen_ai.system"] == "gcp.gemini"
    assert meta["gen_ai.request.model"] == "gemini-2.5-flash"  # extracted from the URL path
    assert meta["gen_ai.usage.input_tokens"] == 7  # Gemini's promptTokenCount
    assert meta["gen_ai.usage.output_tokens"] == 2  # Gemini's candidatesTokenCount
    assert meta["gen_ai.response.finish_reasons"] == ["STOP"]
