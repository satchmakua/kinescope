"""The honesty mechanism: when a replayed agent takes a different path than the
recording, Kinescope reports it rather than silently lying about determinism (§6.4)."""

from __future__ import annotations

import pytest

import kinescope
from kinescope.store.local import LocalStore


def _record_two_tools(store):
    @kinescope.tool
    def alpha():
        return "a"

    @kinescope.tool
    def beta():
        return "b"

    with kinescope.record("t", store=store) as rec:
        alpha()
        beta()
    return rec.run_id


def test_extra_call_beyond_recording_raises(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")

    @kinescope.tool
    def only():
        return 1

    with kinescope.record("t", store=store) as rec:
        only()
    run_id = rec.run_id

    with pytest.raises(kinescope.DivergenceError):
        with kinescope.replay(run_id, store=store):
            only()
            only()  # one more call than was recorded

    diverged = store.get_run(run_id)
    assert any(d["reason"] == "extra-call" and d["seq"] == 1 for d in diverged.divergences)


def test_missing_call_is_detected_at_finalize(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    run_id = _record_two_tools(store)

    @kinescope.tool
    def alpha():
        return "a"

    with kinescope.replay(run_id, store=store) as rep:
        alpha()  # agent stops early — never reaches the recorded second tool

    assert any(d["reason"] == "missing-call" and d["seq"] == 1 for d in rep.divergences)


def test_strict_policy_raises_on_first_divergence(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    run_id = _record_two_tools(store)

    @kinescope.tool
    def alpha():
        return "a"

    @kinescope.tool
    def gamma():
        return "g"

    with pytest.raises(kinescope.DivergenceError):
        with kinescope.replay(run_id, store=store, policy="strict"):
            alpha()
            gamma()  # wrong tool at seq 1 → input-mismatch → strict raises
