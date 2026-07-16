"""Ollama (locally-served models) → `gen_ai.*` meta.

Ollama exposes an OpenAI-compatible `/v1/chat/completions`, so the response parsing is shared
with the OpenAI adapter — only `gen_ai.system` differs. That sharing is itself the point: the
schema absorbs a new *runtime* without new parsing code, while Gemini (a different wire shape)
proves it absorbs new *shapes*. Recording a local model is also the cheapest real-provider
evidence available: no key, no quota, no network.
"""

from __future__ import annotations

from typing import Any

from .openai import normalize as _openai_normalize


def normalize(req_body: Any, resp_bytes: bytes) -> dict[str, Any]:
    meta = _openai_normalize(req_body, resp_bytes)
    meta["gen_ai.system"] = "ollama"  # OpenAI-compatible wire, local runtime
    return meta
