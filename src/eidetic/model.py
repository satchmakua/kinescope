"""Core trace model: Event / Snapshot / Run, plus canonical hashing.

See DESIGN.md §4 ("The trace model & interception contract"). These types are the
load-bearing core — replay, branching, diffing, and divergence all depend on them
being correct and stable.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from time import time as _wall
from typing import Any, Literal

BoundaryKind = Literal["llm", "tool", "clock", "rng", "retrieval"]

# Headers stripped from STORED payloads (secrets must never hit disk). See §6.6.
REDACT_HEADERS = {"authorization", "x-api-key", "x-goog-api-key", "api-key", "cookie"}


def new_run_id() -> str:
    """Lexicographically sortable run id: zero-padded ms epoch + random suffix."""
    return f"{int(_wall() * 1000):013d}-{secrets.token_hex(2)}"


def _json_default(o: Any) -> Any:
    if isinstance(o, (bytes, bytearray)):
        return {"__b64__": __import__("base64").b64encode(bytes(o)).decode("ascii")}
    return str(o)


def canonical_bytes(payload: Any) -> bytes:
    """Deterministic JSON encoding used for hashing and content addressing."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default
    ).encode("utf-8")


def canon_hash(payload: Any) -> str:
    """BLAKE2b-256 of the canonicalized payload — the match key for replay (§4.2).

    Callers pass only the *identity* of a call (e.g. {method, url, body} for HTTP),
    deliberately excluding volatile fields like auth headers and request ids.
    """
    return hashlib.blake2b(canonical_bytes(payload), digest_size=32).hexdigest()


@dataclass(frozen=True, slots=True)
class Event:
    run_id: str
    seq: int  # process-global order, 0-based
    kind: BoundaryKind
    name: str
    input_hash: str  # canon_hash of the call identity; "" for clock/rng
    input_ref: str | None  # blob id of the full (redacted) input payload
    output_ref: str | None  # blob id of the full output payload
    status: Literal["ok", "error"] = "ok"
    ts_wall: float = 0.0  # real wall time at record; never used by replay logic
    dur_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Snapshot:
    run_id: str
    after_seq: int
    state_ref: str
    label: str | None = None


@dataclass(slots=True)
class Run:
    run_id: str
    label: str
    created_at: float
    status: Literal["recording", "complete", "error", "diverged"] = "recording"
    parent_run_id: str | None = None
    forked_at_seq: int | None = None
    overrides: list[dict[str, Any]] = field(default_factory=list)
    sdk_versions: dict[str, str] = field(default_factory=dict)
    divergences: list[dict[str, Any]] = field(default_factory=list)
    capture: list[str] = field(default_factory=list)  # stdlib kinds patched (clock/rng/uuid)
