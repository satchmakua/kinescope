"""The tiny agent used for the real-API reproducibility artifact — shared by the recorder
(`live_record.py`) and the offline test (`tests/test_real_run.py`) so the recorded request
and the replayed request are byte-identical.

Deliberately minimal — one small Claude Haiku call — so a live run costs a fraction of a cent.
"""

from __future__ import annotations

import os

import httpx

import kinescope

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 16
PROMPT = "In one word, what planet do humans live on?"


def run(inner: httpx.BaseTransport | None = None) -> str:
    """Make the Claude call through Kinescope's transport. `inner=None` → real network (record);
    pass a stub transport for offline replay. During replay the API key is irrelevant (the
    request never leaves the process), so a placeholder is fine when the env var is unset."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY") or "offline-replay-no-key-needed"
    client = anthropic.Anthropic(api_key=api_key, http_client=kinescope.http_client(inner=inner))
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": PROMPT}],
    )
    return msg.content[0].text
