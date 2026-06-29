"""LocalStore: the default zero-dependency backend (DESIGN.md §6.6).

Layout (everything under `.eidetic/`):
    index.db                          SQLite (WAL): runs, events, snapshots
    blobs/<aa>/<blake2b-hex>.gz       content-addressed, gzipped, deduplicated payloads
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ..model import Event, Run, Snapshot, canonical_bytes

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    created_at    REAL NOT NULL,
    status        TEXT NOT NULL,
    parent_run_id TEXT,
    forked_at_seq INTEGER,
    overrides     TEXT NOT NULL DEFAULT '[]',
    sdk_versions  TEXT NOT NULL DEFAULT '{}',
    divergences   TEXT NOT NULL DEFAULT '[]',
    capture       TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    input_ref  TEXT,
    output_ref TEXT,
    status     TEXT NOT NULL,
    ts_wall    REAL NOT NULL,
    dur_ms     REAL NOT NULL,
    meta       TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id    TEXT NOT NULL,
    after_seq INTEGER NOT NULL,
    state_ref TEXT NOT NULL,
    label     TEXT,
    PRIMARY KEY (run_id, after_seq)
);
"""


class LocalStore:
    def __init__(self, root: str | Path = ".eidetic") -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "index.db")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # --- blobs (content-addressed, deduplicated, gzipped) ---------------------

    def put_blob(self, data: bytes | Any) -> str:
        raw = data if isinstance(data, (bytes, bytearray)) else canonical_bytes(data)
        raw = bytes(raw)
        blob_id = hashlib.blake2b(raw, digest_size=32).hexdigest()
        path = self.blobs / blob_id[:2] / f"{blob_id}.gz"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # mtime=0: deterministic header AND never calls time.time() (which a session
            # capturing the clock would otherwise intercept — Eidetic must not trip its
            # own patches, and identical content must yield identical bytes for dedup).
            path.write_bytes(gzip.compress(raw, mtime=0))
        return blob_id

    def get_blob(self, blob_id: str) -> bytes:
        path = self.blobs / blob_id[:2] / f"{blob_id}.gz"
        return gzip.decompress(path.read_bytes())

    # --- runs ----------------------------------------------------------------

    def create_run(self, run: Run) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                run.label,
                run.created_at,
                run.status,
                run.parent_run_id,
                run.forked_at_seq,
                json.dumps(run.overrides),
                json.dumps(run.sdk_versions),
                json.dumps(run.divergences),
                json.dumps(run.capture),
            ),
        )
        self.db.commit()

    update_run = create_run  # INSERT OR REPLACE handles both

    def get_run(self, run_id: str) -> Run:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no such run: {run_id}")
        return _row_to_run(row)

    def list_runs(self) -> list[Run]:
        rows = self.db.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [_row_to_run(r) for r in rows]

    # --- events --------------------------------------------------------------

    def append_event(self, ev: Event) -> None:
        # No per-event commit: it's the hot path (one fsync per boundary throttled record
        # to ~700/s). Events are buffered on the connection and flushed by commit(), which
        # the engine calls when the session closes. A crashed recording loses its in-flight
        # tail — acceptable for a debugger; the win is ~10–50× record throughput.
        self.db.execute(
            "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.run_id,
                ev.seq,
                ev.kind,
                ev.name,
                ev.input_hash,
                ev.input_ref,
                ev.output_ref,
                ev.status,
                ev.ts_wall,
                ev.dur_ms,
                json.dumps(ev.meta),
            ),
        )

    def commit(self) -> None:
        self.db.commit()

    def events(self, run_id: str) -> list[Event]:
        rows = self.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    # --- snapshots -----------------------------------------------------------

    def put_snapshot(self, snap: Snapshot) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
            (snap.run_id, snap.after_seq, snap.state_ref, snap.label),
        )

    def snapshots(self, run_id: str) -> list[Snapshot]:
        rows = self.db.execute(
            "SELECT * FROM snapshots WHERE run_id=? ORDER BY after_seq", (run_id,)
        ).fetchall()
        return [Snapshot(r["run_id"], r["after_seq"], r["state_ref"], r["label"]) for r in rows]


def _row_to_run(r: sqlite3.Row) -> Run:
    return Run(
        run_id=r["run_id"],
        label=r["label"],
        created_at=r["created_at"],
        status=r["status"],
        parent_run_id=r["parent_run_id"],
        forked_at_seq=r["forked_at_seq"],
        overrides=json.loads(r["overrides"]),
        sdk_versions=json.loads(r["sdk_versions"]),
        divergences=json.loads(r["divergences"]),
        capture=json.loads(r["capture"]),
    )


def _row_to_event(r: sqlite3.Row) -> Event:
    return Event(
        run_id=r["run_id"],
        seq=r["seq"],
        kind=r["kind"],
        name=r["name"],
        input_hash=r["input_hash"],
        input_ref=r["input_ref"],
        output_ref=r["output_ref"],
        status=r["status"],
        ts_wall=r["ts_wall"],
        dur_ms=r["dur_ms"],
        meta=json.loads(r["meta"]),
    )
