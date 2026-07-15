"""State snapshots: content-addressed dedup, structural diffing, and the auto-snapshot
hook after LLM events."""

from __future__ import annotations

import httpx

import kinescope
from kinescope.diff import diff_snapshots, json_diff
from kinescope.store.local import LocalStore


def test_json_diff_add_remove_replace():
    a = {"keep": 1, "drop": 2, "change": "x", "list": [1, 2]}
    b = {"keep": 1, "change": "y", "list": [1, 2, 3], "new": True}
    ops = {(o["op"], o["path"]): o.get("value") for o in json_diff(a, b)}

    assert ops[("remove", "/drop")] is None
    assert ops[("replace", "/change")] == "y"
    assert ops[("add", "/list/2")] == 3
    assert ops[("add", "/new")] is True


def test_json_diff_escapes_pointer_tokens():
    ops = json_diff({"a/b": 1}, {"a/b": 2})
    assert ops == [{"op": "replace", "path": "/a~1b", "value": 2}]


def test_snapshot_dedup_identical_states(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def noop():
        return 1

    with kinescope.record("t", store=store) as rec:
        state = {"x": 1}
        kinescope.snapshot(state)
        noop()
        kinescope.snapshot(state)  # unchanged → same blob

    snaps = store.snapshots(rec.run_id)
    assert len(snaps) == 2
    assert snaps[0].state_ref == snaps[1].state_ref  # deduplicated
    blobs = list((tmp_path / ".kinescope" / "blobs").rglob("*.gz"))
    # one snapshot blob (shared) + the tool's input/output blobs
    assert sum(1 for _ in blobs) <= 3


def test_snapshot_diff_across_steps(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def step():
        return "ok"

    with kinescope.record("t", store=store) as rec:
        state = {"count": 0, "log": []}
        kinescope.snapshot(state, "start")  # after_seq -1
        step()
        state["count"] = 1
        state["log"].append("a")
        kinescope.snapshot(state, "s1")  # after_seq 0
        step()
        state["count"] = 2
        state["log"].append("b")
        kinescope.snapshot(state, "s2")  # after_seq 1

    ops = diff_snapshots(store, rec.run_id, 0, 1)  # s1 → s2
    by = {(o["op"], o["path"]): o.get("value") for o in ops}
    assert by[("replace", "/count")] == 2
    assert by[("add", "/log/1")] == "b"


def test_snapshot_is_noop_on_replay(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def step():
        return "ok"

    with kinescope.record("t", store=store) as rec:
        kinescope.snapshot({"v": 1})
        step()
    before = len(store.snapshots(rec.run_id))

    with kinescope.replay(rec.run_id, store=store):
        kinescope.snapshot({"v": 999})  # ignored during replay
        step()

    assert len(store.snapshots(rec.run_id)) == before == 1


def test_auto_snapshot_after_llm_event(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    state = {"turns": 0}

    def call():
        client = kinescope.http_client(inner=canned)
        client.get("https://api.anthropic.com/v1/messages")

    with kinescope.record("t", store=store, snapshot=lambda: dict(state)) as rec:
        state["turns"] = 1
        call()  # llm event → auto-snapshot fires

    snaps = store.snapshots(rec.run_id)
    assert len(snaps) == 1 and snaps[0].label == "post-llm"
    import json

    assert json.loads(store.get_blob(snaps[0].state_ref)) == {"turns": 1}
