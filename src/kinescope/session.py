"""Session: the active record/replay context that every interception adapter funnels
through. Owns the process-global sequence counter and the divergence detector
(DESIGN.md §4.1, §6.4).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any, Literal

from .model import BoundaryKind, Event, Run, Snapshot
from .store.base import TraceStore

Mode = Literal["record", "replay", "branch"]
Policy = Literal["strict", "warn", "off"]

_active: ContextVar[Session | None] = ContextVar("kinescope_active_session", default=None)


class DivergenceError(RuntimeError):
    """Raised under policy='strict' (or on an unrecoverable replay) when replay
    diverges from the recording."""


def active_session() -> Session | None:
    return _active.get()


class Session:
    def __init__(
        self,
        store: TraceStore,
        run: Run,
        mode: Mode,
        policy: Policy = "warn",
        recorded: list[Event] | None = None,
    ) -> None:
        self.store = store
        self.run = run
        self.mode = mode
        self.policy = policy
        self._recorded = recorded or []  # replay: the events to feed back, by seq
        self._seq = 0
        self._suppress = 0  # >0 while inside a recorded tool body (nested boundaries skip)
        self._lock = threading.Lock()
        self.snapshot_fn: Callable[[], Any] | None = None  # auto-snapshot after each LLM event
        self.fork_at = -1  # branch mode: replay seq<=fork_at (incl. the override), live after

    # --- identity / lifecycle -----------------------------------------------

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def divergences(self) -> list[dict[str, Any]]:
        return self.run.divergences

    @property
    def events(self) -> list[Event]:
        """The recorded events (replay: preloaded; record: read back from store)."""
        return self._recorded if self.mode == "replay" else self.store.events(self.run_id)

    def activate(self) -> Any:
        return _active.set(self)

    def deactivate(self, token: Any) -> None:
        _active.reset(token)

    # --- sequencing & nesting ------------------------------------------------

    def next_seq(self) -> int:
        with self._lock:
            seq = self._seq
            self._seq += 1
            return seq

    def should_replay(self, seq: int) -> bool:
        """Whether the boundary at `seq` returns a recorded output rather than calling out.

        In `branch` mode the prefix (incl. the overridden fork point at `fork_at`) replays;
        everything after goes live — this is the replay→live switch."""
        if self.mode == "replay":
            return True
        if self.mode == "branch":
            return seq <= self.fork_at
        return False

    def suppressed(self) -> bool:
        return self._suppress > 0

    @contextlib.contextmanager
    def suppress(self) -> Iterator[None]:
        """Within a recorded tool body, nested boundaries are subsumed by the tool's
        recorded output — they neither record nor consume a seq."""
        self._suppress += 1
        try:
            yield
        finally:
            self._suppress -= 1

    # --- record path ---------------------------------------------------------

    def record_event(self, ev: Event) -> None:
        self.store.append_event(ev)
        if self.snapshot_fn is not None and ev.kind == "llm" and not self.suppressed():
            self.take_snapshot(self.snapshot_fn(), label="post-llm")

    def take_snapshot(self, state: Any, label: str | None = None) -> None:
        """Store a content-addressed (deduplicated) state snapshot, tagged with the seq
        of the most recent boundary. No-op during replay (the recording is authoritative)."""
        if self.mode == "replay":
            return
        state_ref = self.store.put_blob(state)
        self.store.put_snapshot(
            Snapshot(self.run_id, after_seq=self._seq - 1, state_ref=state_ref, label=label)
        )

    # --- replay path: match a live boundary against the recording -------------

    def expect(self, seq: int, kind: BoundaryKind, input_hash: str, name: str = "") -> Event:
        """Return the recorded Event for `seq`, flagging divergence on mismatch.

        Under 'warn'/'off' we still return the recorded event *by position* so the run
        can continue; under 'strict' we raise. This is the honesty mechanism (§6.4):
        determinism is claimed only where it holds, and leaks are surfaced — never hidden.
        """
        if seq >= len(self._recorded):
            self._diverge(seq, kind, "extra-call", expected=None, actual=f"{kind}:{name}")
            raise DivergenceError(f"replay made an unrecorded call at seq={seq} ({kind} {name})")

        ev = self._recorded[seq]
        if ev.kind != kind:
            self._diverge(seq, kind, "kind-mismatch", expected=ev.kind, actual=kind)
        elif ev.input_hash != input_hash and input_hash != "":
            self._diverge(seq, kind, "input-mismatch", expected=ev.input_hash, actual=input_hash)
        return ev

    def finalize_replay(self) -> None:
        """Called after the agent finishes a replay: any recorded events the agent did
        not reach are 'missing-call' divergences (the agent took a shorter path)."""
        for ev in self._recorded[self._seq :]:
            self._diverge(
                ev.seq, ev.kind, "missing-call", expected=f"{ev.kind}:{ev.name}", actual=None
            )

    def _diverge(
        self,
        seq: int,
        kind: BoundaryKind,
        reason: str,
        *,
        expected: Any,
        actual: Any,
    ) -> None:
        self.run.divergences.append(
            {"seq": seq, "kind": kind, "reason": reason, "expected": expected, "actual": actual}
        )
        self.run.status = "diverged"
        self.store.update_run(self.run)
        if self.policy == "strict":
            raise DivergenceError(
                f"divergence at seq={seq}: {reason} (expected {expected!r}, got {actual!r})"
            )
