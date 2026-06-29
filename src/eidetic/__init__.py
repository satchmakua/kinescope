"""Eidetic — deterministic record-replay and counterfactual branching for AI agents.

Quickstart::

    import anthropic, eidetic

    def run_agent():
        client = anthropic.Anthropic(http_client=eidetic.http_client())
        return client.messages.create(model="claude-opus-4-8", max_tokens=64,
                                       messages=[{"role": "user", "content": "hi"}])

    with eidetic.record("demo") as rec:
        run_agent()

    with eidetic.replay(rec.run_id) as rep:
        run_agent()          # returns the recorded completion; no network call
    assert not rep.divergences
"""

from __future__ import annotations

from .branch import fork
from .diff import diff_snapshots, json_diff
from .engine import async_http_client, http_client, record, replay, snapshot
from .intercept import instrument_tools, tool
from .model import Event, Run, Snapshot
from .session import DivergenceError, Session, active_session
from .store import LocalStore, TraceStore

__version__ = "0.0.1"

__all__ = [
    "record",
    "replay",
    "fork",
    "http_client",
    "async_http_client",
    "tool",
    "instrument_tools",
    "snapshot",
    "json_diff",
    "diff_snapshots",
    "LocalStore",
    "TraceStore",
    "Session",
    "Event",
    "Run",
    "Snapshot",
    "DivergenceError",
    "active_session",
    "__version__",
]
