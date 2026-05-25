import json

import pytest

from personagent.domain.exceptions import LLMBackendError
from personagent.infrastructure.llm.codex_streaming import CodexStreamParser


def test_parse_sse_event_returns_none_for_empty_or_done():
    parser = CodexStreamParser()
    assert parser.parse_sse_event("type", "", "model") is None
    assert parser.parse_sse_event("type", "[DONE]", "model") is None


def test_parse_sse_event_returns_none_for_invalid_json():
    parser = CodexStreamParser()
    assert parser.parse_sse_event("type", "not-json", "model") is None


def test_parse_sse_event_output_text_delta():
    parser = CodexStreamParser()
    chunk = parser.parse_sse_event(
        "response.output_text.delta",
        json.dumps({"delta": "hello"}),
        "gpt-5.5",
    )
    assert chunk is not None
    assert chunk.content == "hello"
    assert chunk.metadata == {"provider": "codex", "model": "gpt-5.5"}


def test_parse_sse_event_output_text_delta_empty_returns_none():
    parser = CodexStreamParser()
    chunk = parser.parse_sse_event(
        "response.output_text.delta",
        json.dumps({"delta": ""}),
        "gpt-5.5",
    )
    assert chunk is None


def test_parse_sse_event_reasoning_text_delta():
    parser = CodexStreamParser()
    chunk = parser.parse_sse_event(
        "response.reasoning_summary_text.delta",
        json.dumps({"delta": "thinking"}),
        "gpt-5.5",
    )
    assert chunk is not None
    assert chunk.reasoning_content == "thinking"
    assert chunk.is_thinking is True


def test_parse_sse_event_tool_call():
    parser = CodexStreamParser()
    chunk = parser.parse_sse_event(
        "response.output_item.done",
        json.dumps(
            {
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                }
            }
        ),
        "gpt-5.5",
    )
    assert chunk is not None
    assert chunk.finish_reason == "tool_calls"
    assert chunk.tool_calls is not None
    assert chunk.tool_calls[0]["id"] == "call_1"


def test_parse_sse_event_completed():
    parser = CodexStreamParser()
    chunk = parser.parse_sse_event(
        "response.completed",
        json.dumps(
            {
                "response": {
                    "model": "gpt-5.5",
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": 5,
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                }
            }
        ),
        "gpt-5.5",
    )
    assert chunk is not None
    assert chunk.finish_reason == "stop"
    assert chunk.usage is not None
    assert chunk.usage["reasoning_tokens"] == 2
    assert chunk.metadata["model"] == "gpt-5.5"


def test_parse_sse_event_raises_on_error():
    parser = CodexStreamParser()
    with pytest.raises(LLMBackendError):
        parser.parse_sse_event(
            "response.error",
            json.dumps({"error": {"message": "something broke"}}),
            "gpt-5.5",
        )


def test_tool_call_from_response_item_normalizes_arguments():
    parser = CodexStreamParser()
    result = parser.tool_call_from_response_item(
        {"id": "c1", "name": "fn", "arguments": {"key": "val"}}
    )
    assert result["function"]["arguments"] == '{"key": "val"}'


def test_normalize_usage_with_none():
    parser = CodexStreamParser()
    assert parser.normalize_usage(None) is None
    assert parser.normalize_usage("string") is None


def test_normalize_usage_computes_totals():
    parser = CodexStreamParser()
    usage = parser.normalize_usage({"input_tokens": 10, "output_tokens": 20})
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 30
