"""Anthropic Messages API → `gen_ai.*` meta."""

from __future__ import annotations

from typing import Any

from .base import safe_json


def normalize(req_body: Any, resp_bytes: bytes) -> dict[str, Any]:
    meta: dict[str, Any] = {"gen_ai.system": "anthropic"}
    if isinstance(req_body, dict) and req_body.get("model"):
        meta["gen_ai.request.model"] = req_body["model"]
    resp = safe_json(resp_bytes)  # None for SSE/streaming bodies — model still set from request
    if isinstance(resp, dict):
        usage = resp.get("usage") or {}
        if "input_tokens" in usage:
            meta["gen_ai.usage.input_tokens"] = usage["input_tokens"]
        if "output_tokens" in usage:
            meta["gen_ai.usage.output_tokens"] = usage["output_tokens"]
        if resp.get("stop_reason"):
            meta["gen_ai.response.finish_reasons"] = [resp["stop_reason"]]
        if resp.get("model"):
            meta["gen_ai.response.model"] = resp["model"]
    return meta
