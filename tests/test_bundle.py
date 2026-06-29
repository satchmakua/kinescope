"""Trace bundles: a recorded run exports to a portable zip and imports into a *different*
store — where it remains replayable and forkable. Content-addressed blobs keep the event
references valid across the move."""

from __future__ import annotations

import eidetic
from eidetic.store.local import LocalStore


@eidetic.tool
def add(a, b):
    return a + b


def _agent():
    state = {"acc": 0}
    eidetic.snapshot(state, "start")
    x = add(2, 3)
    state["acc"] = x
    eidetic.snapshot(state, "after")
    return x


def test_bundle_roundtrips_into_a_fresh_store_and_replays(tmp_path):
    src = LocalStore(tmp_path / "src")
    with eidetic.record("b", store=src) as rec:
        out1 = _agent()

    bundle = tmp_path / "run.zip"
    eidetic.export_bundle(rec.run_id, bundle, store=src)
    assert bundle.exists() and bundle.stat().st_size > 0

    dst = LocalStore(tmp_path / "dst")  # a clean, separate store
    run_id = eidetic.import_bundle(bundle, store=dst)

    assert run_id == rec.run_id
    assert len(dst.events(run_id)) == len(src.events(rec.run_id))
    assert len(dst.snapshots(run_id)) == len(src.snapshots(rec.run_id))

    # the imported run replays deterministically from the fresh store
    with eidetic.replay(run_id, store=dst) as rep:
        out2 = _agent()
    assert out1 == out2 == 5
    assert rep.divergences == []


def test_imported_bundle_is_forkable(tmp_path):
    src = LocalStore(tmp_path / "src")

    @eidetic.tool
    def classify(temp):
        return "cold" if temp < 50 else "warm"

    def agent():
        return classify(add(10, 20))  # add → 30 → "cold"

    with eidetic.record("f", store=src) as rec:
        assert agent() == "cold"

    bundle = tmp_path / "run.zip"
    eidetic.export_bundle(rec.run_id, bundle, store=src)
    dst = LocalStore(tmp_path / "dst")
    run_id = eidetic.import_bundle(bundle, store=dst)

    # fork the imported run: override add's result so classify flips
    with eidetic.fork(run_id, at=0, override={"output": 99}, store=dst) as br:
        assert agent() == "warm"
    assert dst.get_run(br.run_id).parent_run_id == run_id


def test_bundle_rejects_unknown_version(tmp_path):
    import zipfile

    import pytest

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", '{"bundle_version": 999, "run": {}, "events": []}')
    with pytest.raises(ValueError):
        eidetic.import_bundle(bad, store=LocalStore(tmp_path / "dst"))
