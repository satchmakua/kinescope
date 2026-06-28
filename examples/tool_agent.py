"""M1 showcase: a tool-using agent with clock + RNG, recorded and replayed offline.

The agent reads the clock directly, draws randomness directly, calls a `@eidetic.tool`,
and makes an LLM call (stubbed via a MockTransport — no network, no key). Replay returns
every recorded boundary by position; with `capture=["clock", "rng"]`, even the direct
`time.time()` and `random.random()` calls reproduce exactly.

Run:  python examples/tool_agent.py
"""

from __future__ import annotations

import random
import time

import anthropic
import httpx

import eidetic

CANNED = {
    "id": "msg_demo",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-4-8",
    "content": [{"type": "text", "text": "Those are some lucky rolls!"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 20, "output_tokens": 7},
}


@eidetic.tool
def roll(sides: int = 6) -> int:
    """A 'tool' whose internal randomness is subsumed by its recorded output."""
    return random.randint(1, sides)


def stub() -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(200, json=CANNED))


def forbidden() -> httpx.MockTransport:
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("network hit during replay")

    return httpx.MockTransport(boom)


def agent(inner: httpx.MockTransport) -> dict:
    client = anthropic.Anthropic(api_key="sk-demo", http_client=eidetic.http_client(inner=inner))
    started = time.time()  # direct clock use (captured)
    luck = round(random.random(), 6)  # direct RNG use (captured)
    rolls = [roll() for _ in range(3)]  # tool calls
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=32,
        messages=[{"role": "user", "content": f"My rolls were {rolls}."}],
    )
    return {"started": started, "luck": luck, "rolls": rolls, "reply": msg.content[0].text}


def main() -> None:
    with eidetic.record("dice-agent", capture=["clock", "rng"]) as rec:
        first = agent(stub())
    run_id = rec.run_id

    with eidetic.replay(run_id) as rep:
        second = agent(forbidden())

    assert first == second, f"replay diverged:\n  {first}\n  {second}"
    assert not rep.divergences, f"unexpected divergences: {rep.divergences}"

    print(f"recorded run : {run_id}")
    print(f"result       : {first}")
    print(f"replayed     : identical, {len(rep.events)} events, divergences={rep.divergences}")
    print("\nInspect it:  eidetic show", run_id)


if __name__ == "__main__":
    main()
