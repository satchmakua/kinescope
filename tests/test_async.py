"""Async transport: record→replay is deterministic and offline through AsyncClient."""

from __future__ import annotations

import asyncio

import httpx

import eidetic
from eidetic.store.local import LocalStore


def _canned(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "path": request.url.path})


def _forbidden(request: httpx.Request) -> httpx.Response:
    raise AssertionError("network hit during replay")


async def _call(inner: httpx.MockTransport) -> dict:
    client = eidetic.async_http_client(inner=inner)
    try:
        resp = await client.get("https://api.anthropic.com/v1/messages")
        return resp.json()
    finally:
        await client.aclose()


def test_async_record_replay_is_deterministic(tmp_path):
    store = LocalStore(tmp_path / ".eidetic")

    async def do_record():
        with eidetic.record("a", store=store) as rec:
            out = await _call(httpx.MockTransport(_canned))
        return rec.run_id, out

    run_id, out1 = asyncio.run(do_record())

    async def do_replay():
        with eidetic.replay(run_id, store=store) as rep:
            out = await _call(httpx.MockTransport(_forbidden))
        return out, list(rep.divergences)

    out2, divergences = asyncio.run(do_replay())

    assert out1 == out2 == {"ok": True, "path": "/v1/messages"}
    assert divergences == []
