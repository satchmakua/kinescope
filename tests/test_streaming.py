"""SSE streaming: the Anthropic stream is captured at the transport as raw bytes and
re-materialized on replay, so the SDK's stream parser yields identical text — offline."""

from __future__ import annotations

import json

import anthropic
import httpx

import kinescope
from kinescope.store.local import LocalStore


def _sse(*events: tuple[str, dict]) -> bytes:
    """Encode (event, data) pairs as an SSE byte stream."""
    return b"".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events
    )


# A minimal but valid Anthropic Messages streaming body for "Hello world".
SSE = _sse(
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-4-8",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 5, "output_tokens": 0},
            },
        },
    ),
    (
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": " world"},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
)


def _sse_inner() -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda req: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=SSE
        )
    )


def _forbidden() -> httpx.MockTransport:
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("network hit during replay")

    return httpx.MockTransport(boom)


def _stream(inner: httpx.MockTransport) -> str:
    client = anthropic.Anthropic(api_key="sk-demo", http_client=kinescope.http_client(inner=inner))
    text = ""
    with client.messages.stream(
        model="claude-opus-4-8",
        max_tokens=16,
        messages=[{"role": "user", "content": "hi"}],
    ) as stream:
        for chunk in stream.text_stream:
            text += chunk
    return text


def test_sse_streaming_record_then_replay(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    with kinescope.record("s", store=store) as rec:
        t1 = _stream(_sse_inner())
    with kinescope.replay(rec.run_id, store=store) as rep:
        t2 = _stream(_forbidden())

    assert t1 == t2 == "Hello world"
    assert rep.divergences == []
