# 2. Interception at the httpx transport; local-first pluggable storage

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

Eidetic must capture the LLM boundary of an agent and replay it deterministically.
Two foundational choices shape everything downstream: **how** we intercept the LLM
call, and **where** traces are stored. Both are hard to reverse once adapters and the
on-disk format exist.

Interception options considered: (a) monkeypatch the SDK's `messages.create`;
(b) wrap the client object's methods; (c) intercept at the HTTP transport layer.
Storage options considered: flat JSONL files; a required document DB (MongoDB);
local SQLite + content-addressed blobs behind an interface.

The Anthropic SDK (0.112, verified 2026-06-28) is built on **httpx** and accepts a
caller-supplied `http_client` — a public, documented seam.

## Decision

**Intercept at the httpx transport** (`EideticTransport` wrapping the real transport),
not by monkeypatching SDK methods. The user passes `http_client=eidetic.http_client()`.
This captures the exact wire request/response (and, in M1, the SSE stream as raw bytes),
is robust to SDK version churn, and is provider-agnostic. The replay match key is the
canonicalized call *identity* — `method + url + body`, deliberately excluding volatile
headers (auth, request ids, user-agent). Clock/RNG/UUID — which aren't HTTP — are the
only monkeypatch surface, scoped to the active session.

**Store local-first behind a `TraceStore` port.** The default `LocalStore` is SQLite
(WAL) for the event index plus content-addressed, gzipped, deduplicated blob files under
`.eidetic/`. The core engine depends on **httpx only**; `anthropic`, CLI, TUI, and Mongo
are optional extras. A `MongoStore` adapter can drop in later without touching the engine.

## Consequences

- **Easy:** adding a second provider (OpenAI) — same transport, a new normalizing adapter;
  capturing the true exchange incl. streaming; swapping the storage backend; zero-friction
  adoption (`pip install eidetic` needs only httpx); no secrets on disk (headers redacted
  before `put_blob`).
- **Hard / accepted trade-offs:** the `anthropic[aiohttp]` transport bypasses the httpx
  seam (surfaced by the divergence detector, not captured); replayed SSE arrives batched,
  not time-paced (we reproduce *what*, not *when*); we must strip
  `content-encoding`/`content-length` from stored response headers because we persist the
  already-decoded body.
- Supersedes the foundational doc's lean toward a document DB as the *primary* store: it
  becomes an optional adapter, chosen for adoption over stack-affinity.
