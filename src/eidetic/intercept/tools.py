"""Tool interception (DESIGN.md §6.1).

A tool is an *atomic* boundary: on record it executes and we log its input/output; on
replay it does NOT execute — we return the recorded output. Nondeterminism inside a tool
body (clock/RNG/HTTP) is therefore subsumed by the tool's recorded output and is
suppressed during recording so it neither records nor consumes a seq.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from time import perf_counter
from time import time as _wall
from typing import Any, TypeVar

from ..model import Event, canon_hash
from ..session import Session, active_session

F = TypeVar("F", bound=Callable[..., Any])


def tool(fn: F | None = None, *, name: str | None = None) -> Any:
    """Decorator marking a callable as a recorded tool boundary.

    Usage: ``@eidetic.tool`` or ``@eidetic.tool(name="search")``. Outside a session it
    is a transparent no-op.
    """

    def wrap(f: F) -> F:
        tname = str(name if name is not None else getattr(f, "__name__", "tool"))

        @functools.wraps(f)
        def inner(*args: Any, **kwargs: Any) -> Any:
            ses = active_session()
            if ses is None or ses.suppressed():
                return f(*args, **kwargs)
            seq = ses.next_seq()
            ident = {"name": tname, "args": list(args), "kwargs": kwargs}
            input_hash = canon_hash(ident)

            if ses.should_replay():
                ev = ses.expect(seq, "tool", input_hash, name=tname)
                return _load_recorded(ses, ev)

            t0 = perf_counter()
            try:
                with ses.suppress():  # inner boundaries are part of this tool's output
                    out = f(*args, **kwargs)
            except Exception as exc:
                _emit(ses, seq, tname, input_hash, ident, {"__error__": repr(exc)}, "error", t0)
                raise
            _emit(ses, seq, tname, input_hash, ident, out, "ok", t0)
            return out

        return inner  # type: ignore[return-value]

    return wrap(fn) if fn is not None else wrap


def instrument_tools(registry: dict[str, Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    """Wrap every callable in a name→callable registry in place (and return it)."""
    for key, func in list(registry.items()):
        registry[key] = tool(func, name=key)
    return registry


def _emit(
    ses: Session,
    seq: int,
    name: str,
    input_hash: str,
    ident: dict[str, Any],
    output: Any,
    status: str,
    t0: float,
) -> None:
    ses.record_event(
        Event(
            run_id=ses.run_id,
            seq=seq,
            kind="tool",
            name=name,
            input_hash=input_hash,
            input_ref=ses.store.put_blob(ident),
            output_ref=ses.store.put_blob(output),
            status="error" if status == "error" else "ok",
            ts_wall=_wall(),
            dur_ms=(perf_counter() - t0) * 1000.0,
        )
    )


def _load_recorded(ses: Session, ev: Event) -> Any:
    data = json.loads(ses.store.get_blob(ev.output_ref)) if ev.output_ref else None
    if ev.status == "error":
        msg = data.get("__error__") if isinstance(data, dict) else data
        raise RuntimeError(f"recorded tool error: {msg}")
    return data
