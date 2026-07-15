"""Tool boundary: replay returns the recorded output WITHOUT executing the body, nested
boundaries are suppressed, and arg changes are flagged as divergence."""

from __future__ import annotations

import kinescope
from kinescope.store.local import LocalStore


def test_tool_replay_returns_recorded_without_executing(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    calls = {"n": 0}

    @kinescope.tool
    def add(a, b):
        calls["n"] += 1
        return a + b

    with kinescope.record("t", store=store) as rec:
        r1 = add(2, 3)
    assert r1 == 5 and calls["n"] == 1

    with kinescope.replay(rec.run_id, store=store) as rep:
        r2 = add(2, 3)
    assert r2 == 5
    assert calls["n"] == 1  # body NOT executed on replay
    assert rep.divergences == []
    assert rep.events[0].kind == "tool" and rep.events[0].name == "add"


def test_tool_input_mismatch_is_a_divergence(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def add(a, b):
        return a + b

    with kinescope.record("t", store=store) as rec:
        add(2, 3)
    with kinescope.replay(rec.run_id, store=store) as rep:
        out = add(2, 4)  # different args at the same step

    assert out == 5  # recorded output returned by position (warn)
    assert rep.divergences and rep.divergences[0]["seq"] == 0
    assert rep.divergences[0]["reason"] == "input-mismatch"


def test_nested_boundary_inside_tool_is_suppressed(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def roll():
        import random

        return random.randint(1, 6)  # inner draw is part of the tool's output

    with kinescope.record("t", store=store, capture=["rng"]) as rec:
        roll()

    assert len(rec.events) == 1  # just the tool, not tool + rng
    assert rec.events[0].kind == "tool"


def test_instrument_tools_wraps_registry(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    def search(q):
        return f"results for {q}"

    registry = {"search": search}
    kinescope.instrument_tools(registry)
    with kinescope.record("t", store=store) as rec:
        registry["search"]("cats")

    assert rec.events[0].kind == "tool" and rec.events[0].name == "search"
