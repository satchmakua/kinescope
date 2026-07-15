"""The timeline TUI: scrub updates the detail/diff panes, and `f` forks-and-runs live.

Driven headlessly via Textual's pilot (wrapped in asyncio.run so no pytest-asyncio dep)."""

from __future__ import annotations

import asyncio

from textual.widgets import DataTable

import kinescope
from kinescope.store.local import LocalStore
from kinescope.tui.app import KinescopeApp


def _record_stateful(store):
    @kinescope.tool
    def step(n):
        return n * 10

    with kinescope.record("t", store=store) as rec:
        state = {"count": 0, "log": []}
        kinescope.snapshot(state, "start")
        step(1)
        state["count"] = 1
        state["log"].append("a")
        kinescope.snapshot(state, "s1")
        step(2)
        state["count"] = 2
        state["log"].append("b")
        kinescope.snapshot(state, "s2")
    return rec.run_id


def test_tui_scrub_shows_events_and_diff(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    run_id = _record_stateful(store)

    async def scenario():
        app = KinescopeApp(run_id, store)
        async with app.run_test() as pilot:
            table = app.query_one("#steps", DataTable)
            assert table.row_count == 2  # two tool events

            await pilot.press("down")  # move to the second step
            await pilot.pause()
            detail = str(app.last_detail)
            assert "step" in detail and "#1" in detail

            diff = str(app.last_diff)
            assert "/count" in diff and "/log/1" in diff  # state delta s1 → s2

    asyncio.run(scenario())


def test_tui_fork_creates_and_shows_child(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def sensor(city):
        return 30

    @kinescope.tool
    def classify(temp):
        return "cold" if temp < 50 else "warm"

    def agent():
        return {"temp": sensor("Paris"), "verdict": classify(sensor("Paris"))}

    with kinescope.record("w", store=store) as rec:
        agent()
    parent_id = rec.run_id

    async def scenario():
        app = KinescopeApp(parent_id, store, agent=agent)
        async with app.run_test():
            before = len(store.list_runs())
            child_id = app.do_fork(0, {"output": 72})  # override the sensor read
            assert len(store.list_runs()) == before + 1
            assert app.run_id == child_id  # the app switched to the new branch

            child = store.get_run(child_id)
            assert child.parent_run_id == parent_id
            events = store.events(child_id)
            assert events[0].meta.get("overridden") is True

    asyncio.run(scenario())


def test_fork_without_agent_warns_not_crash(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    run_id = _record_stateful(store)

    async def scenario():
        app = KinescopeApp(run_id, store)  # no agent
        async with app.run_test() as pilot:
            await pilot.press("f")  # should notify, not raise
            await pilot.pause()
            assert app.run_id == run_id  # unchanged

    asyncio.run(scenario())
