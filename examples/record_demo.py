"""Offline end-to-end demo of the M0 record→replay loop.

Uses the *real* Anthropic SDK, but wires its HTTP through a Kinescope transport whose
inner transport is a stub (httpx.MockTransport) — so this runs with no network and no
API key. It records one `messages.create`, then replays it: replay returns the recorded
completion byte-for-byte and never touches the (forbidden) inner transport.

Run:  python examples/record_demo.py
Then: kinescope ls   /   kinescope show <run-id>
"""

from __future__ import annotations

import anthropic
import httpx

import kinescope

# A canned, valid Anthropic Messages API response.
CANNED = {
    "id": "msg_demo",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-4-8",
    "content": [{"type": "text", "text": "Hello from a recorded run."}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 12, "output_tokens": 8},
}


def stub_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=CANNED))


def forbidden_transport() -> httpx.MockTransport:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network was hit during replay — determinism broken!")

    return httpx.MockTransport(_boom)


def run_agent(inner: httpx.MockTransport) -> str:
    client = anthropic.Anthropic(api_key="sk-demo", http_client=kinescope.http_client(inner=inner))
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=64,
        messages=[{"role": "user", "content": "Say hello."}],
    )
    return msg.content[0].text


def main() -> None:
    with kinescope.record("hello-demo") as rec:
        recorded_text = run_agent(stub_transport())
    run_id = rec.run_id

    # Replay: inner transport raises if called → proves replay is offline & deterministic.
    with kinescope.replay(run_id) as rep:
        replayed_text = run_agent(forbidden_transport())

    assert recorded_text == replayed_text, "replay diverged from recording!"
    assert not rep.divergences, f"unexpected divergences: {rep.divergences}"

    print(f"recorded run : {run_id}")
    print(f"completion   : {recorded_text!r}")
    print(f"replayed     : identical, {len(rep.events)} event(s), divergences={rep.divergences}")
    print("\nInspect it:  kinescope ls   |   kinescope show", run_id)


if __name__ == "__main__":
    main()
