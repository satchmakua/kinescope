"""OpenAI Chat Completions API → `gen_ai.*` meta (the second-provider proof, H1)."""

from __future__ import annotations

from typing import Any

from .base import safe_json


def normalize(req_body: Any, resp_bytes: bytes) -> dict[str, Any]:
    meta: dict[str, Any] = {"gen_ai.system": "openai"}
    if isinstance(req_body, dict) and req_body.get("model"):
        meta["gen_ai.request.model"] = req_body["model"]
    resp = safe_json(resp_bytes)
    if isinstance(resp, dict):
        usage = resp.get("usage") or {}
        if "prompt_tokens" in usage:  # OpenAI names differ from Anthropic's
            meta["gen_ai.usage.input_tokens"] = usage["prompt_tokens"]
        if "completion_tokens" in usage:
            meta["gen_ai.usage.output_tokens"] = usage["completion_tokens"]
        choices = resp.get("choices") or []
        reasons = [c.get("finish_reason") for c in choices if c.get("finish_reason")]
        if reasons:
            meta["gen_ai.response.finish_reasons"] = reasons
        if resp.get("model"):
            meta["gen_ai.response.model"] = resp["model"]
    return meta
