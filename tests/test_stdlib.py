"""Clock / RNG / UUID capture: opt-in, replays identically, and stays off by default."""

from __future__ import annotations

import random
import time
import uuid

import kinescope
from kinescope.store.local import LocalStore


def test_clock_rng_uuid_replay_identically(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    def draws():
        return (time.time(), random.randint(1, 10_000_000), random.random(), str(uuid.uuid4()))

    with kinescope.record("t", store=store, capture="all") as rec:
        a = draws()
    with kinescope.replay(rec.run_id, store=store) as rep:
        b = draws()

    assert a == b
    assert rep.divergences == []
    assert len(rec.events) == 4  # time, randint, random, uuid4 — inner draws not double-counted


def test_uuid_roundtrips_to_uuid_type(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    with kinescope.record("t", store=store, capture=["uuid"]) as rec:
        u1 = uuid.uuid4()
    with kinescope.replay(rec.run_id, store=store) as rep:
        u2 = uuid.uuid4()

    assert isinstance(u2, uuid.UUID) and u1 == u2
    assert rep.divergences == []


def test_capture_is_off_by_default(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    with kinescope.record("t", store=store) as rec:  # no capture requested
        time.time()
        random.random()
    assert rec.events == []  # nothing patched, nothing recorded
