"""Unit tests for VertexStreamingHandler — response parsing, delta accumulation, tool call assembly."""

import pytest

from personagent.domain.llm_backend.models import GeneratedImage
from personagent.infrastructure.llm.vertex_ai.streaming import VertexStreamingHandler


def _handler(**kwargs: object) -> VertexStreamingHandler:
    return VertexStreamingHandler(
        timeout=float(kwargs.get("timeout", 240.0)),
        stream_read_timeout=kwargs.get("stream_read_timeout", 0.0),  # type: ignore[arg-type]
        auth_mode=str(kwargs.get("auth_mode", "api_key")),
    )


# -- parse_inference_result ---------------------------------------------------

def test_parse_inference_result_splits_thought_text_final_text_and_preserves_signature():
    handler = _handler()
    result = handler.parse_inference_result(
        {
            "modelVersion": "gemini-3.1-flash-lite-preview",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": "I should solve this privately.", "thought": True, "thoughtSignature": "sig-123"},
                            {"text": "Final answer."},
                        ]
                    },
                }
            ],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 5},
        },
        "fallback-model",
    )
    assert result.reasoning_content == "I should solve this privately."
    assert result.content == "Final answer."
    assert result.finish_reason == "stop"
    assert result.metadata["vertex_thought_signatures"] == ["sig-123"]


def test_parse_inference_result_accepts_string_thought_marker():
    handler = _handler()
    result = handler.parse_inference_result(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "reasoning", "thought": "true"},
                            {"text": "answer"},
                        ]
                    },
                }
            ],
        },
        "gemini-3.1-flash-lite-preview",
    )
    assert result.reasoning_content == "reasoning"
    assert result.content == "answer"


def test_parse_inference_result_extracts_inline_data_as_generated_image():
    handler = _handler()
    result = handler.parse_inference_result(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Rendered image:"},
                            {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}},
                        ]
                    }
                }
            ]
        },
        "gemini-3.1-flash-image-preview",
    )
    assert result.content == "Rendered image:"
    assert len(result.images) == 1
    assert result.images[0].mime_type == "image/png"
    assert result.images[0].data == "iVBORw0KGgo="
    assert result.images[0].to_dict() == {"mime_type": "image/png", "data": "iVBORw0KGgo=", "alt": "Generated image"}


def test_parse_inference_result_includes_tool_calls():
    handler = _handler()
    result = handler.parse_inference_result(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "Search", "args": {"query": "test"}}}
                        ]
                    },
                }
            ],
        },
        "gemini-3-flash-preview",
    )
    assert result.tool_calls is not None
    assert result.tool_calls[0]["function"]["name"] == "Search"
    assert result.finish_reason == "tool_calls"


# -- stream_chunks_from_data --------------------------------------------------

def test_stream_chunks_emits_reasoning_content_and_images_in_order():
    handler = _handler()
    chunks, signatures = handler.stream_chunks_from_data(
        {
            "modelVersion": "gemini-3.1-flash-image-preview",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": "thinking", "thought": True, "thoughtSignature": "sig-stream"},
                            {"text": "answer"},
                            {"inlineData": {"mimeType": "image/jpeg", "data": "/9j/4AAQSkZJRg=="}},
                        ]
                    },
                }
            ],
        },
        "fallback-model",
    )
    assert signatures == ["sig-stream"]
    assert chunks[0].reasoning_content == "thinking"
    assert chunks[0].is_thinking is True
    assert chunks[1].content == "answer"
    assert chunks[2].images[0].mime_type == "image/jpeg"
    assert chunks[3].finish_reason == "stop"
    assert chunks[3].metadata["vertex_thought_signatures"] == ["sig-stream"]


def test_stream_chunks_keeps_original_tool_call_parts_for_replay():
    handler = _handler()
    chunks, _signatures = handler.stream_chunks_from_data(
        {
            "modelVersion": "gemini-3-flash-preview",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {"text": "Investigating", "thought": True, "thoughtSignature": "sig-text-part"},
                            {"functionCall": {"name": "BrowserSearch", "args": {"query": "x"}}},
                        ]
                    },
                }
            ],
        },
        "fallback-model",
    )
    tool_chunk = next(chunk for chunk in chunks if chunk.tool_calls)
    google = tool_chunk.tool_calls[0]["extra_content"]["google"]
    assert google["thought_signature"] == "sig-text-part"
    assert len(google["content_parts"]) == 2


def test_stream_chunks_returns_empty_for_no_candidates():
    handler = _handler()
    chunks, signatures = handler.stream_chunks_from_data({"candidates": []}, "fallback")
    assert chunks == []
    assert signatures == []


def test_stream_chunks_handles_missing_content():
    handler = _handler()
    chunks, signatures = handler.stream_chunks_from_data(
        {"candidates": [{"finishReason": "STOP"}]}, "gemini-3-flash-preview"
    )
    assert len(chunks) == 1
    assert chunks[0].finish_reason == "stop"


def test_stream_chunks_maps_finish_reason_length():
    handler = _handler()
    chunks, _ = handler.stream_chunks_from_data(
        {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "cut"}]}}]},
        "model",
    )
    assert chunks[-1].finish_reason == "length"


def test_stream_chunks_maps_safety_to_content_filter():
    handler = _handler()
    chunks, _ = handler.stream_chunks_from_data(
        {"candidates": [{"finishReason": "SAFETY", "content": {}}]},
        "model",
    )
    assert chunks[-1].finish_reason == "content_filter"


# -- metadata -----------------------------------------------------------------

def test_metadata_includes_provider_model_and_auth_mode():
    handler = _handler(auth_mode="adc")
    meta = handler.metadata("gemini-3-flash-preview")
    assert meta["provider"] == "vertex"
    assert meta["model"] == "gemini-3-flash-preview"
    assert meta["vertex_auth_mode"] == "adc"
    assert "vertex_thought_signatures" not in meta


def test_metadata_includes_thought_signatures_when_present():
    handler = _handler()
    meta = handler.metadata("gemini-2.5-flash", thought_signatures=["sig-a", "", "sig-b"])
    assert meta["vertex_thought_signatures"] == ["sig-a", "sig-b"]


# -- tool_call_from_part ------------------------------------------------------

def test_tool_call_from_part_serializes_function_call():
    handler = _handler()
    call = handler._tool_call_from_part(
        {"functionCall": {"name": "DoIt", "args": {"key": "val"}}}, 3
    )
    assert call["id"] == "vertex-call-3"
    assert call["type"] == "function"
    assert call["function"]["name"] == "DoIt"
    assert call["function"]["arguments"] == '{"key": "val"}'


def test_tool_call_from_part_attaches_thought_signature():
    handler = _handler()
    call = handler._tool_call_from_part(
        {"functionCall": {"name": "F"}, "thoughtSignature": "sig-42"}, 0
    )
    assert call["extra_content"]["google"]["thought_signature"] == "sig-42"


# -- image_from_part ----------------------------------------------------------

def test_image_from_part_extracts_inline_data():
    handler = _handler()
    image = handler._image_from_part({"inlineData": {"mimeType": "image/webp", "data": "abc123"}})
    assert isinstance(image, GeneratedImage)
    assert image.mime_type == "image/webp"
    assert image.data == "abc123"


def test_image_from_part_handles_snake_case_key():
    handler = _handler()
    image = handler._image_from_part({"inline_data": {"mime_type": "image/gif", "data": "R0lGODlh"}})
    assert isinstance(image, GeneratedImage)
    assert image.mime_type == "image/gif"


def test_image_from_part_returns_none_for_non_image():
    handler = _handler()
    assert handler._image_from_part({"text": "hello"}) is None


# -- stream events ------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_events_parse_incremental_json_array_responses():
    handler = _handler()

    class FakeResponse:
        headers = {"content-type": "application/json; charset=UTF-8"}

        async def aiter_text(self):
            for part in [
                '[{"candidates":[{"content":{"parts":[{"text":"hel',
                'lo"}]}}]},',
                '{"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":""}]}}]}',
                "]",
            ]:
                yield part

    events = [event async for event in handler.stream_events(FakeResponse())]
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "hello"
    assert events[1]["candidates"][0]["finishReason"] == "STOP"


def test_stream_data_from_line_extracts_data_prefix():
    handler = _handler()
    assert handler._stream_data_from_line("data: {\"key\":\"val\"}") == '{"key":"val"}'


def test_stream_data_from_line_passes_bare_json():
    handler = _handler()
    assert handler._stream_data_from_line('{"a":1}') == '{"a":1}'


def test_stream_data_from_line_ignores_empty_and_unknown_prefix():
    handler = _handler()
    assert handler._stream_data_from_line("") == ""
    assert handler._stream_data_from_line("event: ping") == ""


# -- finish_reason ------------------------------------------------------------

def test_finish_reason_tool_calls_overrides_all():
    handler = _handler()
    assert handler._finish_reason("STOP", True) == "tool_calls"


def test_finish_reason_none_and_unspecified_return_none():
    handler = _handler()
    assert handler._finish_reason(None, False) is None
    assert handler._finish_reason("FINISH_REASON_UNSPECIFIED", False) is None
