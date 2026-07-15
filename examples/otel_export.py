"""Export a recorded Kinescope run as OpenTelemetry GenAI spans (to the console).

Because `Event.meta` already speaks the OTel `gen_ai.*` vocabulary, a recorded trace drops
into any OTel backend. Here we print the spans with the console exporter — offline, no key.

Run:  python examples/otel_export.py
"""

from __future__ import annotations

import httpx
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

import kinescope

LLM_RESPONSE = {
    "model": "claude-opus-4-8",
    "usage": {"input_tokens": 9, "output_tokens": 12},
    "stop_reason": "end_turn",
}


@kinescope.tool
def search(query: str) -> dict:
    return {"hits": [f"result for {query}"]}


def agent() -> None:
    client = kinescope.http_client(
        inner=httpx.MockTransport(lambda req: httpx.Response(200, json=LLM_RESPONSE))
    )
    client.post(
        "https://api.anthropic.com/v1/messages",
        json={"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "weather?"}]},
    )
    search("weather")


def main() -> None:
    with kinescope.record("otel-demo") as rec:
        agent()
    print(f"recorded run {rec.run_id} — exporting as OTel gen_ai spans:\n")

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    n = kinescope.export_otel(rec.run_id, tracer_provider=provider)
    provider.force_flush()
    print(f"\nexported {n} gen_ai span(s) + 1 run span")


if __name__ == "__main__":
    main()
