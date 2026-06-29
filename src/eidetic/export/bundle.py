"""Shareable trace bundles (DESIGN.md §8 M5).

Package a recorded run — its Run row, events, snapshots, and every referenced blob — into a
single portable zip, so a failing run can be handed to someone else who can replay and fork
it. Import drops it into any TraceStore; because blobs are content-addressed, the event/
snapshot references stay valid. Stdlib-only (`zipfile`), so this lives in the core.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path

from ..model import Event, Run, Snapshot
from ..store.base import TraceStore
from ..store.local import LocalStore

BUNDLE_VERSION = 1


def export_bundle(run_id: str, path: str | Path, store: TraceStore | None = None) -> Path:
    """Write `run_id` (events + snapshots + referenced blobs) to a zip bundle at `path`."""
    store = store or LocalStore()
    run = store.get_run(run_id)
    events = store.events(run_id)
    snaps = store.snapshots(run_id)

    blob_ids: set[str] = set()
    for ev in events:
        blob_ids.update(ref for ref in (ev.input_ref, ev.output_ref) if ref)
    blob_ids.update(s.state_ref for s in snaps)

    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "run": asdict(run),
        "events": [asdict(e) for e in events],
        "snapshots": [asdict(s) for s in snaps],
    }
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for blob_id in sorted(blob_ids):
            z.writestr(f"blobs/{blob_id}", store.get_blob(blob_id))
    return path


def import_bundle(path: str | Path, store: TraceStore | None = None) -> str:
    """Load a bundle into `store` and return the run id. Blobs are re-stored by content, so
    their ids must match the manifest's references."""
    store = store or LocalStore()
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("bundle_version") != BUNDLE_VERSION:
            raise ValueError(f"unsupported bundle_version: {manifest.get('bundle_version')}")
        for name in z.namelist():
            if name.startswith("blobs/"):
                blob_id = name.split("/", 1)[1]
                restored = store.put_blob(z.read(name))
                if restored != blob_id:
                    raise ValueError(f"blob id mismatch on import: {blob_id} != {restored}")

    store.create_run(Run(**manifest["run"]))
    for ev in manifest["events"]:
        store.append_event(Event(**ev))
    for snap in manifest["snapshots"]:
        store.put_snapshot(Snapshot(**snap))
    store.commit()
    return str(manifest["run"]["run_id"])
