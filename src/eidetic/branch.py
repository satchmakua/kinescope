"""Branching — the counterfactual hook (DESIGN.md §6.3).

`fork(parent, at=k, override=...)` builds a new child run whose log is the parent's
events `0..k-1` copied verbatim, plus event `k` with its **output swapped** for the
override. Re-running the agent inside the `fork()` context then replays that prefix
(so it reaches step `k` and receives the overridden output) and switches to **live**
execution for every boundary after `k` — exploring "what if this one step had gone
differently?". The child is a normal recorded run: itself replayable and forkable.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import replace
from time import time as _wall
from typing import Any

from .engine import _versions
from .intercept.stdlib import StdlibPatcher
from .model import Event, Run, new_run_id
from .session import Policy, Session
from .store.base import TraceStore
from .store.local import LocalStore


def _apply_override(store: TraceStore, parent_k: Event, output: Any, child_id: str) -> Event:
    """Clone the parent's fork-point event into the child with its output replaced."""
    meta = {**parent_k.meta, "overridden": True}
    if parent_k.kind in ("clock", "rng"):  # scalar output lives inline in meta
        meta["value"] = output
        return replace(parent_k, run_id=child_id, output_ref=None, meta=meta)
    return replace(parent_k, run_id=child_id, output_ref=store.put_blob(output), meta=meta)


@contextlib.contextmanager
def fork(
    parent_id: str,
    at: int,
    override: dict[str, Any],
    store: TraceStore | None = None,
    *,
    policy: Policy = "warn",
) -> Iterator[Session]:
    """Fork `parent_id` at step `at`, substituting `override["output"]` for that step's
    output, then re-run the agent inside this context to explore the branch live.

    The new child run's id is `session.run_id`; it records `parent_run_id`, `forked_at_seq`,
    and the override.
    """
    store = store or LocalStore()
    parent = store.get_run(parent_id)
    events = store.events(parent_id)
    if not 0 <= at < len(events):
        raise ValueError(f"fork point {at} out of range (run has {len(events)} events)")
    if "output" not in override:
        raise ValueError("override must include an 'output' value")

    child = Run(
        run_id=new_run_id(),
        label=f"{parent.label}#fork@{at}",
        created_at=_wall(),
        status="recording",
        parent_run_id=parent_id,
        forked_at_seq=at,
        overrides=[override],
        sdk_versions=_versions(),
        capture=parent.capture,
    )
    store.create_run(child)
    for ev in events[:at]:  # copy the deterministic prefix 0..at-1 verbatim
        store.append_event(replace(ev, run_id=child.run_id))
    store.append_event(_apply_override(store, events[at], override["output"], child.run_id))

    ses = Session(
        store=store,
        run=child,
        mode="branch",
        policy=policy,
        recorded=store.events(child.run_id),  # the pre-built prefix 0..at
    )
    ses.fork_at = at
    patcher = StdlibPatcher(ses, child.capture)
    token = ses.activate()
    patcher.install()
    try:
        yield ses
        if child.status == "recording":
            child.status = "complete"
        ses.finalize_replay()
    except BaseException:
        child.status = "error"
        raise
    finally:
        patcher.uninstall()
        store.update_run(child)
        ses.deactivate(token)
