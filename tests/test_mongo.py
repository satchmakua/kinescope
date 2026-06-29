"""MongoStore: the same record→replay→fork engine runs unchanged against a document-DB
backend — proving the TraceStore port generalizes (the storage analog of the OpenAI proof).
Tested hermetically with mongomock (in-memory, pymongo-compatible)."""

from __future__ import annotations

import mongomock

import eidetic
from eidetic.store.mongo import MongoStore


def _store() -> MongoStore:
    return MongoStore(client=mongomock.MongoClient())


def test_record_replay_on_mongo_backend():
    store = _store()
    calls = {"n": 0}

    @eidetic.tool
    def add(a, b):
        calls["n"] += 1
        return a + b

    with eidetic.record("m", store=store) as rec:
        r1 = add(2, 3)
    with eidetic.replay(rec.run_id, store=store) as rep:
        r2 = add(2, 3)

    assert r1 == r2 == 5
    assert calls["n"] == 1  # replay didn't execute the tool body
    assert rep.divergences == []


def test_fork_on_mongo_backend():
    store = _store()

    @eidetic.tool
    def sensor(city):
        return 30

    @eidetic.tool
    def classify(temp):
        return "cold" if temp < 50 else "warm"

    def agent():
        temp = sensor("Paris")
        return {"temp": temp, "verdict": classify(temp)}

    with eidetic.record("w", store=store) as rec:
        assert agent() == {"temp": 30, "verdict": "cold"}

    with eidetic.fork(rec.run_id, at=0, override={"output": 72}, store=store) as br:
        assert agent() == {"temp": 72, "verdict": "warm"}  # override + live re-classify

    child = store.get_run(br.run_id)
    assert child.parent_run_id == rec.run_id and child.forked_at_seq == 0
    assert store.events(br.run_id)[0].meta.get("overridden") is True


def test_mongo_blob_dedup():
    store = _store()
    a = store.put_blob({"x": 1})
    b = store.put_blob({"x": 1})
    c = store.put_blob(b"raw-bytes")

    assert a == b and a != c
    assert store.get_blob(a) == b'{"x":1}'
    assert store.get_blob(c) == b"raw-bytes"
    assert store.blobs.count_documents({}) == 2  # the duplicate collapsed


def test_mongo_run_and_event_metadata_roundtrip():
    store = _store()
    import httpx

    canned = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"model": "claude-opus-4-8", "stop_reason": "end_turn"}
        )
    )
    with eidetic.record("meta", store=store) as rec:
        client = eidetic.http_client(inner=canned)
        client.post("https://api.anthropic.com/v1/messages", json={"model": "claude-opus-4-8"})

    ev = store.events(rec.run_id)[0]
    assert ev.kind == "llm"
    assert ev.meta["gen_ai.system"] == "anthropic"  # dotted keys survive the round-trip
    assert ev.meta["gen_ai.request.model"] == "claude-opus-4-8"
    assert [r.run_id for r in store.list_runs()] == [rec.run_id]
