"""HTTP interception via custom httpx transports (DESIGN.md §4.4, §6.1).

This is the LLM/retrieval boundary. We wrap the real transport so we capture the exact
wire exchange — including SSE streaming bodies, which we buffer and re-materialize on
replay (chunks arrive batched: we reproduce *what* streamed, not its latency). The SDK's
own parser then rebuilds identical typed objects.

Time is imported by-value (`from time import ...`) so that a session capturing the clock
cannot intercept Eidetic's own internal timing.
"""

from __future__ import annotations

import base64
import json
from time import perf_counter
from time import time as _wall
from typing import Any

import httpx

from ..adapters import normalize_meta
from ..model import REDACT_HEADERS, Event, canon_hash
from ..session import Session

# Stored response headers that would corrupt a re-materialized body (we store the
# already-decoded content), so we drop them when reconstructing the Response.
_STRIP_RESP_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def _decode_body(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return {"__b64__": base64.b64encode(body).decode("ascii")}


def _redact(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("<redacted>" if k.lower() in REDACT_HEADERS else v) for k, v in headers.items()}


def _identity(request: httpx.Request) -> dict[str, Any]:
    """The match key for replay: method + url + body, deliberately header-free (§4.2)."""
    return {
        "method": request.method,
        "url": str(request.url),
        "body": _decode_body(request.content),
    }


def _full_payload(request: httpx.Request) -> dict[str, Any]:
    return {**_identity(request), "headers": _redact(dict(request.headers))}


def _sanitized_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _STRIP_RESP_HEADERS}


def _replay_response(
    s: Session, seq: int, request: httpx.Request, input_hash: str
) -> httpx.Response:
    ev = s.expect(seq, "llm", input_hash, name=request.url.path)
    body = s.store.get_blob(ev.output_ref) if ev.output_ref else b""
    return httpx.Response(
        ev.meta.get("http.status", 200),
        headers=ev.meta.get("resp_headers", {}),
        content=body,
        request=request,
    )


def _persist(
    s: Session,
    seq: int,
    request: httpx.Request,
    status_code: int,
    raw: bytes,
    headers: dict[str, str],
    dur_ms: float,
    input_hash: str,
) -> None:
    meta = normalize_meta(str(request.url), _decode_body(request.content), raw)
    meta["http.status"] = status_code
    meta["resp_headers"] = headers
    s.record_event(
        Event(
            run_id=s.run_id,
            seq=seq,
            kind="llm",
            name=request.url.path,
            input_hash=input_hash,
            input_ref=s.store.put_blob(_full_payload(request)),
            output_ref=s.store.put_blob(raw),
            status="ok" if status_code < 400 else "error",
            ts_wall=_wall(),
            dur_ms=dur_ms,
            meta=meta,
        )
    )


class EideticTransport(httpx.BaseTransport):
    """Sync transport shim."""

    def __init__(self, inner: httpx.BaseTransport, session: Session) -> None:
        self._inner = inner
        self._s = session

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._s.suppressed():  # nested inside a recorded tool body
            return self._inner.handle_request(request)
        seq = self._s.next_seq()
        input_hash = canon_hash(_identity(request))
        if self._s.should_replay(seq):
            return _replay_response(self._s, seq, request, input_hash)

        request.read()
        t0 = perf_counter()
        resp = self._inner.handle_request(request)
        raw = resp.read()
        dur_ms = (perf_counter() - t0) * 1000.0
        headers = _sanitized_headers(resp.headers)
        _persist(self._s, seq, request, resp.status_code, raw, headers, dur_ms, input_hash)
        return httpx.Response(resp.status_code, headers=headers, content=raw, request=request)

    def close(self) -> None:
        self._inner.close()


class EideticAsyncTransport(httpx.AsyncBaseTransport):
    """Async transport shim — mirror of EideticTransport for AsyncAnthropic / AsyncClient."""

    def __init__(self, inner: httpx.AsyncBaseTransport, session: Session) -> None:
        self._inner = inner
        self._s = session

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._s.suppressed():
            return await self._inner.handle_async_request(request)
        seq = self._s.next_seq()
        input_hash = canon_hash(_identity(request))
        if self._s.should_replay(seq):
            return _replay_response(self._s, seq, request, input_hash)

        await request.aread()
        t0 = perf_counter()
        resp = await self._inner.handle_async_request(request)
        raw = await resp.aread()
        dur_ms = (perf_counter() - t0) * 1000.0
        headers = _sanitized_headers(resp.headers)
        _persist(self._s, seq, request, resp.status_code, raw, headers, dur_ms, input_hash)
        return httpx.Response(resp.status_code, headers=headers, content=raw, request=request)

    async def aclose(self) -> None:
        await self._inner.aclose()
