"""Export a recorded run as OpenTelemetry GenAI spans (DESIGN.md §4.3, §8 M5).

Because `Event.meta` is already aligned to the OTel `gen_ai.*` semantic conventions, a
recorded trace drops straight into any OTel-compatible backend (Phoenix, Langfuse, etc.):
one parent `eidetic.run` span with a child span per LLM (`chat {model}`) and tool
(`execute_tool {name}`) boundary, carrying the recorded timings and `gen_ai.*` attributes.
"""

from __future__ import annotations

from typing import Any

from ..model import Event
from ..store.base import TraceStore
from ..store.local import LocalStore


def _span_name(ev: Event) -> str:
    if ev.kind == "llm":
        model = ev.meta.get("gen_ai.request.model", "")
        return f"chat {model}".strip()
    return f"execute_tool {ev.name}"


def _span_attrs(ev: Event) -> dict[str, Any] | None:
    """OTel attributes for an event, or None to skip (clock/RNG aren't GenAI spans)."""
    if ev.kind == "llm":
        attrs: dict[str, Any] = {k: v for k, v in ev.meta.items() if k.startswith("gen_ai.")}
        attrs.setdefault("gen_ai.operation.name", "chat")
        attrs["eidetic.seq"] = ev.seq
        return attrs
    if ev.kind == "tool":
        return {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": ev.name,
            "eidetic.seq": ev.seq,
        }
    return None


def export_otel(
    run_id: str,
    store: TraceStore | None = None,
    tracer_provider: Any = None,
) -> int:
    """Emit GenAI spans for `run_id` to `tracer_provider` (or the global one). Returns the
    number of LLM/tool spans emitted (excluding the parent `eidetic.run` span)."""
    store = store or LocalStore()
    run = store.get_run(run_id)
    events = store.events(run_id)
    if tracer_provider is None:
        from opentelemetry import trace

        tracer_provider = trace.get_tracer_provider()
    tracer = tracer_provider.get_tracer("eidetic", "0.0.1")

    emitted = 0
    with tracer.start_as_current_span(
        "eidetic.run",
        attributes={
            "eidetic.run_id": run.run_id,
            "eidetic.label": run.label,
            "eidetic.divergence_count": len(run.divergences),
        },
    ):
        for ev in events:
            attrs = _span_attrs(ev)
            if attrs is None:
                continue
            start = int(ev.ts_wall * 1e9) if ev.ts_wall else None
            span = tracer.start_span(_span_name(ev), start_time=start, attributes=attrs)
            span.end(end_time=start + int(ev.dur_ms * 1e6) if start is not None else None)
            emitted += 1
    return emitted
