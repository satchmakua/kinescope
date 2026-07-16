"""Tiny local-Ollama agent for the real-run artifact — shared by the recorder and the offline
test so the recorded and replayed requests are byte-identical.

Uses the OpenAI SDK pointed at Ollama's OpenAI-compatible endpoint (the idiomatic way to call
Ollama), which also demonstrates the engine intercepting a real SDK against a **local** model:
no API key, no quota, no network. Requires Ollama running with the model pulled:

    ollama serve            # usually already running
    ollama pull qwen2.5:1.5b-instruct
"""

from __future__ import annotations

import httpx

import kinescope

MODEL = "qwen2.5:1.5b-instruct"
BASE_URL = "http://localhost:11434/v1"
PROMPT = "In one word, what planet do humans live on?"
MAX_TOKENS = 16


def run(inner: httpx.BaseTransport | None = None) -> str:
    """`inner=None` → real call to the local Ollama server (record); pass a stub transport for
    offline replay. Ollama ignores the API key; the OpenAI SDK just requires one to be set."""
    import openai

    client = openai.OpenAI(
        base_url=BASE_URL,
        api_key="ollama",  # not a secret — Ollama doesn't authenticate
        http_client=kinescope.http_client(inner=inner),
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": PROMPT}],
    )
    return resp.choices[0].message.content
