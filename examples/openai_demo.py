"""The same engine, a second provider — Kinescope is provider-agnostic (H1).

Records and replays an OpenAI `chat.completions` call through the identical record→replay
machinery used for Anthropic, offline (stub transport, no key). The only provider-specific
code is the `gen_ai.*` normalization in `kinescope/adapters/openai.py`.

Run:  python examples/openai_demo.py
"""

from __future__ import annotations

import httpx
import openai

import kinescope

CANNED = {
    "id": "chatcmpl-demo",
    "object": "chat.completion",
    "created": 1736600000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from a recorded OpenAI run."},
            "logprobs": None,
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 8, "total_tokens": 19},
}


def run_agent(inner: httpx.MockTransport) -> str:
    client = openai.OpenAI(api_key="sk-demo", http_client=kinescope.http_client(inner=inner))
    resp = client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "Say hello."}]
    )
    return resp.choices[0].message.content


def main() -> None:
    stub = httpx.MockTransport(lambda req: httpx.Response(200, json=CANNED))

    def forbidden(req: httpx.Request) -> httpx.Response:
        raise AssertionError("network hit during replay")

    with kinescope.record("openai-hello") as rec:
        recorded = run_agent(stub)
    run_id = rec.run_id

    with kinescope.replay(run_id) as rep:
        replayed = run_agent(httpx.MockTransport(forbidden))

    assert recorded == replayed and not rep.divergences
    meta = {k: v for k, v in rep.events[0].meta.items() if k.startswith("gen_ai")}
    print(f"recorded run : {run_id}")
    print(f"completion   : {recorded!r}")
    print(f"replayed     : identical, divergences={rep.divergences}")
    print(f"gen_ai meta  : {meta}")


if __name__ == "__main__":
    main()
