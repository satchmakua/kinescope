"""record() / replay() context managers and the http_client() factories — the public
entry points that drive a Session (DESIGN.md §6.2, §6.3).
"""

from __future__ import annotations

import contextlib
import platform
from collections.abc import Callable, Iterator
from time import time as _wall
from typing import Any

import httpx

from .intercept.http import KinescopeAsyncTransport, KinescopeTransport
from .intercept.stdlib import StdlibPatcher, normalize_capture
from .model import Run, new_run_id
from .session import Policy, Session, active_session
from .store.base import TraceStore
from .store.local import LocalStore


def _versions() -> dict[str, str]:
    vers = {"kinescope": "0.0.1", "python": platform.python_version()}
    with contextlib.suppress(Exception):
        import anthropic  # type: ignore

        vers["anthropic"] = anthropic.__version__
    return vers


@contextlib.contextmanager
def record(
    label: str = "run",
    store: TraceStore | None = None,
    *,
    policy: Policy = "warn",
    capture: Any = (),
    snapshot: Callable[[], Any] | None = None,
) -> Iterator[Session]:
    """Record the nondeterministic boundaries of the agent code run inside this block.

    `capture` opts into stdlib interception: any of "clock", "rng", "uuid" (or "all").
    Tool boundaries (`@kinescope.tool`) and HTTP/LLM boundaries are always captured.
    `snapshot` is an optional zero-arg callable; if given, agent state is auto-snapshotted
    after every LLM event (in addition to any explicit `kinescope.snapshot()` calls).
    """
    store = store or LocalStore()
    capture_kinds = normalize_capture(capture)
    run = Run(
        run_id=new_run_id(),
        label=label,
        created_at=_wall(),
        status="recording",
        sdk_versions=_versions(),
        capture=capture_kinds,
    )
    store.create_run(run)
    ses = Session(store=store, run=run, mode="record", policy=policy)
    ses.snapshot_fn = snapshot
    patcher = StdlibPatcher(ses, capture_kinds)
    token = ses.activate()
    patcher.install()
    try:
        yield ses
        if run.status == "recording":
            run.status = "complete"
    except BaseException:
        run.status = "error"
        raise
    finally:
        patcher.uninstall()
        store.update_run(run)
        store.commit()  # flush buffered events durably
        ses.deactivate(token)


@contextlib.contextmanager
def replay(
    run_id: str,
    store: TraceStore | None = None,
    *,
    policy: Policy = "warn",
) -> Iterator[Session]:
    """Re-run the same agent code; boundaries return recorded outputs instead of calling out.

    The exact stdlib capture set recorded with the run is re-applied so the boundary
    sequence stays aligned.
    """
    store = store or LocalStore()
    run = store.get_run(run_id)
    run.divergences = []  # fresh divergence report for this replay
    recorded = store.events(run_id)
    ses = Session(store=store, run=run, mode="replay", policy=policy, recorded=recorded)
    patcher = StdlibPatcher(ses, run.capture)
    token = ses.activate()
    patcher.install()
    try:
        yield ses
        ses.finalize_replay()  # surface any recorded events the agent didn't reach
    finally:
        patcher.uninstall()
        store.update_run(run)
        store.commit()  # flush buffered events durably
        ses.deactivate(token)


def http_client(*, inner: httpx.BaseTransport | None = None, **kwargs: Any) -> httpx.Client:
    """A sync httpx.Client whose transport records/replays through the active session.

    Pass to the SDK, e.g. `anthropic.Anthropic(http_client=kinescope.http_client())`.
    `inner` overrides the real network transport (used by tests to inject a stub).
    """
    ses = _require_session()
    inner = inner if inner is not None else httpx.HTTPTransport()
    return httpx.Client(transport=KinescopeTransport(inner, ses), **kwargs)


def async_http_client(
    *, inner: httpx.AsyncBaseTransport | None = None, **kwargs: Any
) -> httpx.AsyncClient:
    """An async httpx.AsyncClient for `anthropic.AsyncAnthropic(http_client=...)`."""
    ses = _require_session()
    inner = inner if inner is not None else httpx.AsyncHTTPTransport()
    return httpx.AsyncClient(transport=KinescopeAsyncTransport(inner, ses), **kwargs)


def snapshot(state: Any, label: str | None = None) -> None:
    """Capture a content-addressed snapshot of document-shaped agent state at this point.

    A no-op outside a session and during replay (the recorded snapshots are authoritative).
    """
    ses = active_session()
    if ses is not None:
        ses.take_snapshot(state, label=label)


def _require_session() -> Session:
    ses = active_session()
    if ses is None:
        raise RuntimeError("kinescope.http_client() must be called inside record()/replay()")
    return ses
