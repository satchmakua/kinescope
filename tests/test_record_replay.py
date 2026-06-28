"""The headline guarantee: record → replay is deterministic, offline, and honest
about divergence. These exercise the engine at the httpx boundary (no anthropic dep).
"""

from __future__ import annotations

import httpx
import pytest

import eidetic
from eidetic.store.local import LocalStore


def _canned(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "path": request.url.path})


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay")


def _call(path: str = "/v1/messages", inner: httpx.MockTransport | None = None) -> dict:
    client = eidetic.http_client(inner=inner or httpx.MockTransport(_canned))
    return client.get("https://api.anthropic.com" + path).json()


def test_record_then_replay_is_deterministic_and_offline(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")
    with eidetic.record("t", store=store) as rec:
        out1 = _call("/v1/messages")
    run_id = rec.run_id

    with eidetic.replay(run_id, store=store) as rep:
        out2 = _call("/v1/messages", inner=httpx.MockTransport(_forbidden))

    assert out1 == out2 == {"ok": True, "path": "/v1/messages"}
    assert rep.divergences == []
    assert len(rep.events) == 1
    assert rep.events[0].kind == "llm"


def test_divergence_is_detected_on_input_mismatch(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")
    with eidetic.record("t", store=store) as rec:
        _call("/a")
    run_id = rec.run_id

    with eidetic.replay(run_id, store=store, policy="warn") as rep:
        out = _call("/b", inner=httpx.MockTransport(_forbidden))  # different identity

    assert out == {"ok": True, "path": "/a"}  # warn → recorded output returned by position
    assert rep.divergences and rep.divergences[0]["seq"] == 0
    assert rep.divergences[0]["reason"] == "input-mismatch"


def test_strict_policy_raises_on_divergence(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")
    with eidetic.record("t", store=store) as rec:
        _call("/a")
    run_id = rec.run_id

    with pytest.raises(eidetic.DivergenceError):
        with eidetic.replay(run_id, store=store, policy="strict"):
            _call("/b", inner=httpx.MockTransport(_forbidden))


def test_http_client_requires_active_session():
    with pytest.raises(RuntimeError):
        eidetic.http_client()
