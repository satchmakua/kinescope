"""OTel export: a recorded run becomes GenAI spans (`chat {model}` / `execute_tool …`)
carrying the `gen_ai.*` attributes, under one `kinescope.run` parent — verified offline with
an in-memory span exporter."""

from __future__ import annotations

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import kinescope
from kinescope.store.local import LocalStore

LLM_RESPONSE = {
    "model": "claude-opus-4-8",
    "usage": {"input_tokens": 5, "output_tokens": 7},
    "stop_reason": "end_turn",
}


@kinescope.tool
def lookup(query: str) -> dict:
    return {"hits": [query]}


def _agent(inner: httpx.MockTransport) -> None:
    client = kinescope.http_client(inner=inner)
    client.post(
        "https://api.anthropic.com/v1/messages",
        json={"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "hi"}]},
    )
    lookup("weather")


def test_export_otel_emits_gen_ai_spans(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=LLM_RESPONSE))
    with kinescope.record("r", store=store) as rec:
        _agent(canned)

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    n = kinescope.export_otel(rec.run_id, store=store, tracer_provider=provider)
    provider.force_flush()
    spans = {s.name: s for s in exporter.get_finished_spans()}

    assert n == 2  # one LLM span + one tool span (the run parent isn't counted)
    assert "kinescope.run" in spans
    assert "chat claude-opus-4-8" in spans
    assert "execute_tool lookup" in spans

    llm = dict(spans["chat claude-opus-4-8"].attributes)
    assert llm["gen_ai.system"] == "anthropic"
    assert llm["gen_ai.operation.name"] == "chat"
    assert llm["gen_ai.usage.input_tokens"] == 5
    assert llm["gen_ai.usage.output_tokens"] == 7
    assert llm["gen_ai.response.finish_reasons"] == ("end_turn",)

    tool = dict(spans["execute_tool lookup"].attributes)
    assert tool["gen_ai.operation.name"] == "execute_tool"
    assert tool["gen_ai.tool.name"] == "lookup"


def test_export_otel_uses_recorded_timing(tmp_path):
    store = LocalStore(tmp_path / ".kinescope")
    canned = httpx.MockTransport(lambda req: httpx.Response(200, json=LLM_RESPONSE))
    with kinescope.record("r", store=store) as rec:
        _agent(canned)

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    kinescope.export_otel(rec.run_id, store=store, tracer_provider=provider)
    provider.force_flush()

    llm_event = next(e for e in store.events(rec.run_id) if e.kind == "llm")
    llm_span = next(s for s in exporter.get_finished_spans() if s.name.startswith("chat "))
    assert llm_span.start_time == int(llm_event.ts_wall * 1e9)  # recorded wall time, not "now"
