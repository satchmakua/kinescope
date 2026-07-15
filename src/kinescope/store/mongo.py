"""MongoStore: a document-DB backend for the TraceStore port (DESIGN.md §6.6).

The second backend exists to prove the port generalizes — the same record/replay/branch
engine runs against it unchanged. Traces are naturally document-shaped, so Run/Event/
Snapshot map to collection documents directly; blobs are content-addressed, gzipped, and
deduplicated by `_id`. `meta` is stored as a JSON string to sidestep MongoDB's historical
dotted-field-name restriction (our `gen_ai.*` / `http.status` keys contain dots).

Requires the `mongo` extra (`pip install kinescope[mongo]`). Construct with a live
`pymongo` client/URI, or inject any pymongo-compatible client (e.g. `mongomock`) for tests.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

from ..model import Event, Run, Snapshot, canonical_bytes


class MongoStore:
    def __init__(
        self,
        client: Any = None,
        *,
        uri: str = "mongodb://localhost:27017",
        database: str = "kinescope",
    ) -> None:
        if client is None:
            from pymongo import MongoClient  # imported only for the live path

            client = MongoClient(uri)
        self.db = client[database]
        self.runs = self.db.runs
        self.events_c = self.db.events
        self.snaps_c = self.db.snapshots
        self.blobs = self.db.blobs
        self.events_c.create_index([("run_id", 1), ("seq", 1)], unique=True)
        self.snaps_c.create_index([("run_id", 1), ("after_seq", 1)], unique=True)

    # --- blobs (content-addressed, deduplicated, gzipped) --------------------

    def put_blob(self, data: bytes | Any) -> str:
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else canonical_bytes(data)
        blob_id = hashlib.blake2b(raw, digest_size=32).hexdigest()
        self.blobs.update_one(
            {"_id": blob_id},
            {"$setOnInsert": {"gz": gzip.compress(raw, mtime=0)}},
            upsert=True,
        )
        return blob_id

    def get_blob(self, blob_id: str) -> bytes:
        doc = self.blobs.find_one({"_id": blob_id})
        if doc is None:
            raise KeyError(blob_id)
        return gzip.decompress(doc["gz"])

    # --- runs ----------------------------------------------------------------

    def create_run(self, run: Run) -> None:
        self.runs.replace_one({"_id": run.run_id}, _run_doc(run), upsert=True)

    update_run = create_run  # replace_one upsert handles both

    def get_run(self, run_id: str) -> Run:
        doc = self.runs.find_one({"_id": run_id})
        if doc is None:
            raise KeyError(f"no such run: {run_id}")
        return _to_run(doc)

    def list_runs(self) -> list[Run]:
        return [_to_run(d) for d in self.runs.find().sort("created_at", -1)]

    # --- events --------------------------------------------------------------

    def append_event(self, ev: Event) -> None:
        self.events_c.replace_one(
            {"run_id": ev.run_id, "seq": ev.seq}, _event_doc(ev), upsert=True
        )

    def events(self, run_id: str) -> list[Event]:
        return [_to_event(d) for d in self.events_c.find({"run_id": run_id}).sort("seq", 1)]

    # --- snapshots -----------------------------------------------------------

    def put_snapshot(self, snap: Snapshot) -> None:
        self.snaps_c.replace_one(
            {"run_id": snap.run_id, "after_seq": snap.after_seq},
            {
                "run_id": snap.run_id,
                "after_seq": snap.after_seq,
                "state_ref": snap.state_ref,
                "label": snap.label,
            },
            upsert=True,
        )

    def snapshots(self, run_id: str) -> list[Snapshot]:
        docs = self.snaps_c.find({"run_id": run_id}).sort("after_seq", 1)
        return [Snapshot(d["run_id"], d["after_seq"], d["state_ref"], d.get("label")) for d in docs]

    def commit(self) -> None:
        """Mongo writes are durable on acknowledgement — nothing to flush."""


def _run_doc(run: Run) -> dict[str, Any]:
    return {
        "_id": run.run_id,
        "run_id": run.run_id,
        "label": run.label,
        "created_at": run.created_at,
        "status": run.status,
        "parent_run_id": run.parent_run_id,
        "forked_at_seq": run.forked_at_seq,
        "overrides": run.overrides,
        "sdk_versions": run.sdk_versions,
        "divergences": run.divergences,
        "capture": run.capture,
    }


def _to_run(doc: dict[str, Any]) -> Run:
    return Run(
        run_id=doc["run_id"],
        label=doc["label"],
        created_at=doc["created_at"],
        status=doc["status"],
        parent_run_id=doc.get("parent_run_id"),
        forked_at_seq=doc.get("forked_at_seq"),
        overrides=doc.get("overrides", []),
        sdk_versions=doc.get("sdk_versions", {}),
        divergences=doc.get("divergences", []),
        capture=doc.get("capture", []),
    )


def _event_doc(ev: Event) -> dict[str, Any]:
    return {
        "run_id": ev.run_id,
        "seq": ev.seq,
        "kind": ev.kind,
        "name": ev.name,
        "input_hash": ev.input_hash,
        "input_ref": ev.input_ref,
        "output_ref": ev.output_ref,
        "status": ev.status,
        "ts_wall": ev.ts_wall,
        "dur_ms": ev.dur_ms,
        "meta": json.dumps(ev.meta),  # JSON string: meta keys contain dots
    }


def _to_event(doc: dict[str, Any]) -> Event:
    return Event(
        run_id=doc["run_id"],
        seq=doc["seq"],
        kind=doc["kind"],
        name=doc["name"],
        input_hash=doc["input_hash"],
        input_ref=doc.get("input_ref"),
        output_ref=doc.get("output_ref"),
        status=doc.get("status", "ok"),
        ts_wall=doc.get("ts_wall", 0.0),
        dur_ms=doc.get("dur_ms", 0.0),
        meta=json.loads(doc["meta"]),
    )
