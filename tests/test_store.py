"""LocalStore: content-addressed dedup blobs + run/event round-trips."""

from __future__ import annotations

import time

from eidetic.model import Event, Run, new_run_id
from eidetic.store.local import LocalStore


def test_blob_is_content_addressed_and_deduplicated(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")
    a = store.put_blob({"hello": "world"})
    b = store.put_blob({"hello": "world"})  # identical → same id, one file
    c = store.put_blob(b"raw-bytes")

    assert a == b
    assert a != c
    assert store.get_blob(a) == b'{"hello":"world"}'
    assert store.get_blob(c) == b"raw-bytes"

    files = list((tmp_path / ".eidetic" / "blobs").rglob("*.gz"))
    assert len(files) == 2  # the dup collapsed


def test_run_and_event_roundtrip(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")
    run = Run(run_id=new_run_id(), label="x", created_at=time.time())
    store.create_run(run)

    ev = dict(input_ref=None, output_ref=None)
    store.append_event(Event(run.run_id, seq=0, kind="tool", name="search", input_hash="h", **ev))
    store.append_event(Event(run.run_id, seq=1, kind="llm", name="messages", input_hash="h2", **ev))

    got = store.get_run(run.run_id)
    assert got.label == "x"
    events = store.events(run.run_id)
    assert [e.seq for e in events] == [0, 1]
    assert events[0].kind == "tool" and events[1].kind == "llm"

    assert [r.run_id for r in store.list_runs()] == [run.run_id]
