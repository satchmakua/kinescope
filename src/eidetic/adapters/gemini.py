"""Google Gemini `generateContent` API → `gen_ai.*` meta.

A deliberately *different* wire shape from Anthropic/OpenAI — the stronger test that the
event schema is genuinely provider-agnostic: the model is in the **URL path** (not the body),
token counts are `promptTokenCount`/`candidatesTokenCount`, and `finishReason` is uppercase.
"""

from __future__ import annotations

import re
from typing import Any

from .base import safe_json

# .../v1beta/models/<model>:generateContent  → capture <model>
_MODEL_IN_URL = re.compile(r"/models/([^:/?]+)")


def normalize(url: str, req_body: Any, resp_bytes: bytes) -> dict[str, Any]:
    meta: dict[str, Any] = {"gen_ai.system": "gcp.gemini"}
    match = _MODEL_IN_URL.search(url or "")
    if match:
        meta["gen_ai.request.model"] = match.group(1)  # Gemini puts the model in the URL
    resp = safe_json(resp_bytes)
    if isinstance(resp, dict):
        usage = resp.get("usageMetadata") or {}
        if "promptTokenCount" in usage:
            meta["gen_ai.usage.input_tokens"] = usage["promptTokenCount"]
        if "candidatesTokenCount" in usage:
            meta["gen_ai.usage.output_tokens"] = usage["candidatesTokenCount"]
        candidates = resp.get("candidates") or []
        reasons = [c.get("finishReason") for c in candidates if c.get("finishReason")]
        if reasons:
            meta["gen_ai.response.finish_reasons"] = reasons
        if resp.get("modelVersion"):
            meta["gen_ai.response.model"] = resp["modelVersion"]
    return meta
