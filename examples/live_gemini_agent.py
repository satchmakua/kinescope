"""Tiny Gemini agent for the real-API artifact — shared by the recorder and the offline test.

Uses raw httpx (no SDK needed — the engine intercepts any httpx client) with the API key in
the `x-goog-api-key` HEADER, never the URL, so the committed trace stays key-free (auth headers
are redacted before storage). One small call, so a live run is free-tier / negligible.
"""

from __future__ import annotations

import os

import httpx

import kinescope

# Pinned to a concrete 3.x model with real free-tier quota. Note: the legacy flash models
# (gemini-2.0-flash, gemini-2.5-flash) return 429 "limit: 0" or 404 "no longer available to
# new users" on new keys — they're off the free tier, so retrying them never helps. Avoid the
# floating `-latest` aliases and `-preview` ids here so the recorded artifact stays regenerable.
MODEL = "gemini-3.1-flash-lite"
PROMPT = "In one word, what planet do humans live on?"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def run(inner: httpx.BaseTransport | None = None) -> str:
    """`inner=None` → real network (record); pass a stub transport for offline replay. During
    replay the key is irrelevant (the request never leaves the process)."""
    client = kinescope.http_client(inner=inner)
    key = os.environ.get("GEMINI_API_KEY") or "offline-replay-no-key-needed"
    body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT}]}],
        "generationConfig": {"maxOutputTokens": 64},
    }
    resp = client.post(URL, headers={"x-goog-api-key": key}, json=body)
    resp.raise_for_status()
    candidate = resp.json()["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    return parts[0]["text"] if parts else f"<no text; finishReason={candidate.get('finishReason')}>"
