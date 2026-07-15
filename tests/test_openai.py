"""H1 — the second-provider proof: an OpenAI chat.completions call records and replays
through the *same engine*, with no core schema change, fully offline from a recorded
fixture. This is the only real test that the event schema is provider-agnostic.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import openai

import kinescope
from kinescope.store.local import LocalStore

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "openai_chat.json").read_text())


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay")


def _run(inner: httpx.MockTransport) -> str:
    client = openai.OpenAI(api_key="sk-test", http_client=kinescope.http_client(inner=inner))
    resp = client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )
    return resp.choices[0].message.content


def test_openai_records_and_replays_through_same_engine(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=FIXTURE))

    with kinescope.record("openai", store=store) as rec:
        out1 = _run(canned)

    with kinescope.replay(rec.run_id, store=store) as rep:
        out2 = _run(httpx.MockTransport(_forbidden))  # replay must not touch the network

    assert out1 == out2 == "Hello from a recorded OpenAI run."
    assert rep.divergences == []


def test_openai_response_is_normalized_to_gen_ai_meta(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=FIXTURE))

    with kinescope.record("openai", store=store) as rec:
        _run(canned)

    meta = store.events(rec.run_id)[0].meta
    assert meta["gen_ai.system"] == "openai"
    assert meta["gen_ai.request.model"] == "gpt-4o-mini"
    assert meta["gen_ai.usage.input_tokens"] == 11  # OpenAI's prompt_tokens
    assert meta["gen_ai.usage.output_tokens"] == 8  # OpenAI's completion_tokens
    assert meta["gen_ai.response.finish_reasons"] == ["stop"]
