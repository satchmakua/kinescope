"""Provider normalizers: turn a recorded HTTP exchange into OTel-GenAI `gen_ai.*` meta
(DESIGN.md §4.3). The engine stays provider-agnostic — only these adapters know a
provider's wire shape, dispatched by request host. Normalization parses JSON only, so it
needs no provider SDK installed.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit


def safe_json(data: bytes) -> Any:
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None


OLLAMA_PORT = 11434  # Ollama's well-known local port


def normalize_meta(url: str, req_body: Any, resp_bytes: bytes) -> dict[str, Any]:
    """Best-effort `gen_ai.*` metadata for the timeline (never raises)."""
    split = urlsplit(url)
    host = (split.hostname or "").lower()
    if "ollama" in host or split.port == OLLAMA_PORT:
        from .ollama import normalize as ollama_normalize

        return ollama_normalize(req_body, resp_bytes)  # local, OpenAI-compatible wire
    if "anthropic" in host:
        from .anthropic import normalize

        return normalize(req_body, resp_bytes)
    if "openai" in host or "azure" in host:
        from .openai import normalize

        return normalize(req_body, resp_bytes)
    if "generativelanguage" in host or "gemini" in host:
        from .gemini import normalize as gemini_normalize

        return gemini_normalize(url, req_body, resp_bytes)  # needs the URL: model lives there
    meta: dict[str, Any] = {"gen_ai.system": host or "unknown"}
    if isinstance(req_body, dict) and req_body.get("model"):
        meta["gen_ai.request.model"] = req_body["model"]
    return meta
