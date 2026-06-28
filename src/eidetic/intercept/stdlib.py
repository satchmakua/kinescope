"""Clock / RNG / UUID interception via scoped monkeypatching (DESIGN.md §6.1).

We record the *value drawn* (not seeds) and, on replay, return the recorded value by
position — consistent with every other boundary and robust across Python versions.

Patching the `time`/`random`/`uuid` module attributes intercepts callers that use
`time.time()` / `random.random()` / `uuid.uuid4()` (the common idiom). Callers that did
`from time import time` captured the original and are NOT intercepted — a documented
limitation. Because patching is invasive (libraries call these too), capture is OPT-IN
per `record(..., capture=[...])`; replay re-applies exactly the recorded set so the
sequence stays aligned.
"""

from __future__ import annotations

import random
import time
import uuid
from time import time as _wall
from typing import Any

from ..model import Event
from ..session import Session

# kind -> (module, attribute) patch targets.
_TARGETS: dict[str, list[tuple[Any, str]]] = {
    "clock": [(time, "time"), (time, "monotonic"), (time, "perf_counter")],
    "rng": [
        (random, "random"),
        (random, "randint"),
        (random, "uniform"),
        (random, "randrange"),
        (random, "getrandbits"),
    ],
    "uuid": [(uuid, "uuid4")],
}

VALID_CAPTURE = frozenset(_TARGETS)


def normalize_capture(capture: Any) -> list[str]:
    if capture in (None, (), [], ""):
        return []
    if capture == "all":
        return list(VALID_CAPTURE)
    kinds = [capture] if isinstance(capture, str) else list(capture)
    bad = set(kinds) - VALID_CAPTURE
    if bad:
        raise ValueError(f"unknown capture kind(s): {sorted(bad)}; valid: {sorted(VALID_CAPTURE)}")
    return kinds


def _to_jsonable(val: Any, cast: str | None) -> Any:
    return str(val) if cast == "uuid" else val


def _cast_back(value: Any, cast: str | None) -> Any:
    return uuid.UUID(value) if cast == "uuid" else value


class StdlibPatcher:
    """Installs/uninstalls the monkeypatches for a set of capture kinds within a session."""

    def __init__(self, session: Session, capture: list[str]) -> None:
        self.s = session
        self.capture = capture
        self._saved: list[tuple[Any, str, Any]] = []

    def install(self) -> None:
        for kind in self.capture:
            event_kind = "rng" if kind == "uuid" else kind
            cast = "uuid" if kind == "uuid" else None
            for module, attr in _TARGETS[kind]:
                self._patch(module, attr, event_kind, cast)

    def _patch(self, module: Any, attr: str, kind: str, cast: str | None) -> None:
        orig = getattr(module, attr)
        name = f"{module.__name__}.{attr}"
        s = self.s

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if s.suppressed():
                return orig(*args, **kwargs)
            seq = s.next_seq()
            if s.should_replay():
                ev = s.expect(seq, kind, "", name=name)  # type: ignore[arg-type]
                return _cast_back(ev.meta.get("value"), ev.meta.get("cast"))
            val = orig(*args, **kwargs)
            s.record_event(
                Event(
                    run_id=s.run_id,
                    seq=seq,
                    kind=kind,  # type: ignore[arg-type]
                    name=name,
                    input_hash="",
                    input_ref=None,
                    output_ref=None,
                    status="ok",
                    ts_wall=_wall(),
                    meta={"value": _to_jsonable(val, cast), "cast": cast},
                )
            )
            return val

        setattr(module, attr, wrapper)
        self._saved.append((module, attr, orig))

    def uninstall(self) -> None:
        for module, attr, orig in reversed(self._saved):
            setattr(module, attr, orig)
        self._saved.clear()
