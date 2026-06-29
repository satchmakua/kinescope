"""Structural JSON diffing for state snapshots (DESIGN.md §6.5).

Emits RFC 6902-shaped ops (add / remove / replace over JSON Pointer paths). Computed
lazily — only when a step is inspected — so scrubbing a long run stays O(1). Lists are
diffed positionally (an append shows up as an `add` at the tail), which is exactly what
a growing message history wants.
"""

from __future__ import annotations

import json
from typing import Any

from .model import Snapshot
from .store.base import TraceStore


def _esc(token: Any) -> str:
    """JSON Pointer escaping: ~ -> ~0, / -> ~1."""
    return str(token).replace("~", "~0").replace("/", "~1")


def json_diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    """Return the ops that transform `a` into `b`."""
    ops: list[dict[str, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a:
            if key not in b:
                ops.append({"op": "remove", "path": f"{path}/{_esc(key)}"})
        for key, bv in b.items():
            child = f"{path}/{_esc(key)}"
            if key not in a:
                ops.append({"op": "add", "path": child, "value": bv})
            elif a[key] != bv:
                ops.extend(json_diff(a[key], bv, child))
    elif isinstance(a, list) and isinstance(b, list):
        common = min(len(a), len(b))
        for i in range(common):
            if a[i] != b[i]:
                ops.extend(json_diff(a[i], b[i], f"{path}/{i}"))
        for i in range(common, len(b)):
            ops.append({"op": "add", "path": f"{path}/{i}", "value": b[i]})
        for i in range(len(a) - 1, common - 1, -1):  # remove tail high→low
            ops.append({"op": "remove", "path": f"{path}/{i}"})
    elif a != b:
        ops.append({"op": "replace", "path": path or "/", "value": b})
    return ops


def _at_or_before(snaps: list[Snapshot], seq: int) -> Snapshot:
    candidates = [s for s in snaps if s.after_seq <= seq]
    return candidates[-1] if candidates else snaps[0]


def diff_snapshots(store: TraceStore, run_id: str, a: int, b: int) -> list[dict[str, Any]]:
    """Diff the snapshots nearest at-or-before steps `a` and `b`."""
    snaps = store.snapshots(run_id)
    if not snaps:
        raise ValueError(
            f"run {run_id} has no snapshots — call eidetic.snapshot(state) in the agent"
        )
    sa, sb = _at_or_before(snaps, a), _at_or_before(snaps, b)
    state_a = json.loads(store.get_blob(sa.state_ref))
    state_b = json.loads(store.get_blob(sb.state_ref))
    return json_diff(state_a, state_b)
