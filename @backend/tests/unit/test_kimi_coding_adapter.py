import json

import pytest

from personagent.infrastructure.llm.kimi_coding_adapter import (
    DEFAULT_MODEL,
    KimiCodingAdapter,
    _AnthropicStreamState,
)


def test_kimi_adapter_sets_anthropic_headers_without_exposing_key():
    adapter = KimiCodingAdapter(api_key="sk-kimi-test-secret")

    assert adapter.headers["Authorization"] == "Bearer sk-kimi-test-secret"
    assert adapter.headers["anthropic-version"] == "2023-06-01"
    assert "sk-kimi-test-secret" not in repr(adapter)


def test_kimi_payload_uses_messages_endpoint_shape_and_reasoning_budget():
    adapter = KimiCodingAdapter(api_key="key")

    payload = adapter._build_payload(
        [
            {"role": "system", "content": "You are PersonAgent."},
            {"role": "user", "content": "Hello"},
        ],
        0.7,
        65536,
        True,
        {
            "model": "kimi-for-coding",
            "reasoning_budget_tokens": 2048,
        },
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                    "strict": True,
                },
            }
        ],
        tool_choice="auto",
    )

    assert payload["model"] == "kimi-for-coding"
    assert payload["stream"] is True
    assert payload["max_tokens"] == 32768
    assert payload["system"] == "You are PersonAgent."
    assert payload["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
    ]
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert payload["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]
    assert payload["tool_choice"] == {"type": "auto"}
    assert "temperature" not in payload
    assert "top_p" not in payload


def test_kimi_payload_disables_thinking_when_budget_is_zero():
    adapter = KimiCodingAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.7,
        10,
        False,
        {"reasoning_budget_tokens": 0},
    )

    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 10


def test_kimi_payload_converts_tool_call_history_to_anthropic_blocks():
    adapter = KimiCodingAdapter(api_key="key")

    payload = adapter._build_payload(
        [
            {
                "role": "assistant",
                "content": "I will inspect it.",
                "tool_calls": [
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "toolu_1",
                "content": "README content",
            },
        ],
        0.7,
        -1,
        False,
        {"model": DEFAULT_MODEL},
    )

    assert payload["messages"] == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will inspect it."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "README content",
                }
            ],
        },
    ]


def test_kimi_non_stream_parser_splits_thinking_text_and_tool_calls():
    adapter = KimiCodingAdapter(api_key="key")

    result = adapter._parse_message_response(
        {
            "model": "kimi-for-coding",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 7, "output_tokens": 11},
            "content": [
                {"type": "thinking", "thinking": "private reasoning", "signature": "sig-1"},
                {"type": "text", "text": "Visible answer"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
            ],
        },
        "kimi-for-coding",
    )

    assert result.content == "Visible answer"
    assert result.reasoning_content == "private reasoning"
    assert result.finish_reason == "tool_calls"
    assert result.metadata["provider"] == "kimi"
    assert result.metadata["kimi_thinking_signatures"] == ["sig-1"]
    assert result.tool_calls is not None
    assert json.loads(result.tool_calls[0]["function"]["arguments"]) == {"path": "README.md"}


def test_kimi_stream_parser_splits_thinking_signature_and_final_text():
    adapter = KimiCodingAdapter(api_key="key")
    state = _AnthropicStreamState(model="kimi-for-coding")

    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "hidden"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "sig-stream"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": " final"},
        },
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]

    chunks = [adapter._parse_stream_event(event, state)[0] for event in events]

    assert chunks[1].reasoning_content == "hidden"
    assert chunks[1].is_thinking is True
    assert chunks[2].metadata["kimi_thinking_signatures"] == ["sig-stream"]
    assert chunks[5].content == " final"
    assert chunks[6].finish_reason == "stop"


def test_kimi_stream_parser_finalizes_tool_use_from_input_json_delta():
    adapter = KimiCodingAdapter(api_key="key")
    state = _AnthropicStreamState(model="kimi-for-coding")

    adapter._parse_stream_event(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}},
        },
        state,
    )
    adapter._parse_stream_event(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":"'},
        },
        state,
    )
    adapter._parse_stream_event(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": 'README.md"}'},
        },
        state,
    )

    stopped, done = adapter._parse_stream_event({"type": "content_block_stop", "index": 0}, state)
    chunk, done = adapter._parse_stream_event(
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        state,
    )

    assert stopped.is_empty
    assert done is False
    assert chunk.finish_reason == "tool_calls"
    assert chunk.tool_calls is not None
    call = chunk.tool_calls[0]
    assert call["id"] == "toolu_1"
    assert call["function"]["name"] == "read_file"
    assert json.loads(call["function"]["arguments"]) == {"path": "README.md"}


def test_kimi_stream_parser_preserves_signed_thinking_for_tool_replay():
    adapter = KimiCodingAdapter(api_key="key")
    state = _AnthropicStreamState(model="kimi-for-coding")

    events = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "need a tool"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "sig-tool"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "TodoWrite", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"todos":[]}'},
        },
        {"type": "content_block_stop", "index": 1},
    ]
    for event in events:
        adapter._parse_stream_event(event, state)

    chunk, _ = adapter._parse_stream_event(
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        state,
    )

    assert chunk.tool_calls is not None
    extra = chunk.tool_calls[0]["extra_content"]["anthropic"]
    assert extra["content_blocks"] == [
        {"type": "thinking", "thinking": "need a tool", "signature": "sig-tool"},
        {"type": "tool_use", "id": "toolu_1", "name": "TodoWrite", "input": {"todos": []}},
    ]

    replay_payload = adapter._build_payload(
        [
            {"role": "user", "content": "Use TodoWrite."},
            {"role": "assistant", "content": "", "tool_calls": chunk.tool_calls},
            {"role": "tool", "tool_call_id": "toolu_1", "content": "Updated 0 todos."},
        ],
        0.7,
        4096,
        True,
        {"model": "kimi-for-coding", "reasoning_budget_tokens": 2048},
    )

    assert replay_payload["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "need a tool", "signature": "sig-tool"},
            {"type": "tool_use", "id": "toolu_1", "name": "TodoWrite", "input": {"todos": []}},
        ],
    }


@pytest.mark.asyncio
async def test_kimi_catalog_supports_capability_filtering():
    adapter = KimiCodingAdapter(api_key="key")

    catalog = await adapter.list_models(capability="reasoning_chat")

    assert catalog["provider"] == "kimi"
    assert catalog["data"][0]["id"] == "kimi-for-coding"
    assert catalog["data"][0]["supports_reasoning"] is True
