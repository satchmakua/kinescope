"""Provider normalization: Anthropic and OpenAI wire shapes both map to `gen_ai.*`,
and the engine stays provider-agnostic (dispatch by host, JSON-only, never raises)."""

from __future__ import annotations

from kinescope.adapters import normalize_meta


def test_anthropic_normalization():
    meta = normalize_meta(
        "https://api.anthropic.com/v1/messages",
        {"model": "claude-opus-4-8"},
        b'{"model":"claude-opus-4-8","usage":{"input_tokens":5,"output_tokens":7},"stop_reason":"end_turn"}',
    )
    assert meta["gen_ai.system"] == "anthropic"
    assert meta["gen_ai.request.model"] == "claude-opus-4-8"
    assert meta["gen_ai.usage.input_tokens"] == 5
    assert meta["gen_ai.usage.output_tokens"] == 7
    assert meta["gen_ai.response.finish_reasons"] == ["end_turn"]


def test_openai_normalization():
    meta = normalize_meta(
        "https://api.openai.com/v1/chat/completions",
        {"model": "gpt-4o-mini"},
        b'{"usage":{"prompt_tokens":11,"completion_tokens":8},"choices":[{"finish_reason":"stop"}]}',
    )
    assert meta["gen_ai.system"] == "openai"
    assert meta["gen_ai.usage.input_tokens"] == 11
    assert meta["gen_ai.usage.output_tokens"] == 8
    assert meta["gen_ai.response.finish_reasons"] == ["stop"]


def test_gemini_normalization_reads_model_from_url():
    meta = normalize_meta(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},  # no model in the body
        b'{"candidates":[{"finishReason":"STOP"}],'
        b'"usageMetadata":{"promptTokenCount":7,"candidatesTokenCount":2}}',
    )
    assert meta["gen_ai.system"] == "gcp.gemini"
    assert meta["gen_ai.request.model"] == "gemini-2.5-flash"  # pulled from the URL, not the body
    assert meta["gen_ai.usage.input_tokens"] == 7
    assert meta["gen_ai.usage.output_tokens"] == 2
    assert meta["gen_ai.response.finish_reasons"] == ["STOP"]


def test_ollama_dispatches_by_port_and_reuses_openai_parsing():
    meta = normalize_meta(
        "http://localhost:11434/v1/chat/completions",  # localhost — identified by Ollama's port
        {"model": "qwen2.5:1.5b-instruct"},
        b'{"usage":{"prompt_tokens":40,"completion_tokens":3},"choices":[{"finish_reason":"stop"}]}',
    )
    assert meta["gen_ai.system"] == "ollama"  # not "openai", despite the compatible wire
    assert meta["gen_ai.request.model"] == "qwen2.5:1.5b-instruct"
    assert meta["gen_ai.usage.input_tokens"] == 40
    assert meta["gen_ai.usage.output_tokens"] == 3
    assert meta["gen_ai.response.finish_reasons"] == ["stop"]


def test_unknown_host_is_best_effort_not_an_error():
    meta = normalize_meta("https://llm.example.com/v1/generate", {"model": "foo-1"}, b"not json")
    assert meta["gen_ai.system"] == "llm.example.com"
    assert meta["gen_ai.request.model"] == "foo-1"


def test_streaming_body_still_yields_system_and_model():
    # An SSE body isn't parseable as a single JSON object — model still comes from the request.
    meta = normalize_meta(
        "https://api.openai.com/v1/chat/completions", {"model": "gpt-4o"}, b"data: {}\n\n"
    )
    assert meta["gen_ai.system"] == "openai"
    assert meta["gen_ai.request.model"] == "gpt-4o"
