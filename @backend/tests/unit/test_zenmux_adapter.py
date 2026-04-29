import json

from personagent.infrastructure.llm.zenmux_adapter import ZenMuxAdapter


def test_zenmux_payload_uses_chat_completions_reasoning_contract():
    adapter = ZenMuxAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.7,
        256,
        True,
        {
            "model": "deepseek/deepseek-v4-flash-free",
            "reasoning_level": "high",
            "reasoning_budget_tokens": 2048,
        },
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice="auto",
    )

    assert payload["model"] == "deepseek/deepseek-v4-flash-free"
    assert payload["stream"] is True
    assert payload["reasoning"] == {"enabled": True, "effort": "high", "max_tokens": 2048}
    assert payload["max_tokens"] == 4096
    assert payload["tool_choice"] == "auto"
    assert "temperature" not in payload


def test_zenmux_chat_parser_prioritizes_reasoning_details_and_visible_content():
    adapter = ZenMuxAdapter(api_key="key")

    result = adapter._parse_chat_response(
        {
            "model": "deepseek/deepseek-v4-pro-free",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "reasoning_details": [
                            {"type": "reasoning.text", "text": "detailed thought"},
                            {"type": "reasoning.text", "signature": "opaque-only"},
                        ],
                        "reasoning": " brief thought",
                        "content": "<think>tagged</think>Final answer",
                    },
                }
            ],
            "usage": {"completion_tokens": 9},
        },
        "deepseek/deepseek-v4-pro-free",
    )

    assert result.content == "Final answer"
    assert result.reasoning_content == "detailed thought brief thoughttagged"
    assert result.metadata["provider"] == "zenmux"
    assert result.metadata["zenmux_reasoning_details"][0]["text"] == "detailed thought"


def test_zenmux_stream_parser_separates_reasoning_details_content_and_tool_calls():
    adapter = ZenMuxAdapter(api_key="key")
    accumulator = {}

    thinking = adapter._parse_stream_chunk(
        {
            "model": "deepseek/deepseek-v4-flash-free",
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {"type": "reasoning.text", "text": "inspect first"}
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        "deepseek/deepseek-v4-flash-free",
        accumulator,
    )
    tool_call = adapter._parse_stream_chunk(
        {
            "model": "deepseek/deepseek-v4-flash-free",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
        "deepseek/deepseek-v4-flash-free",
        accumulator,
    )

    assert thinking.reasoning_content == "inspect first"
    assert thinking.is_thinking is True
    assert thinking.metadata["zenmux_reasoning_details"][0]["text"] == "inspect first"
    assert tool_call.tool_calls is not None
    assert json.loads(tool_call.tool_calls[0]["function"]["arguments"]) == {
        "path": "README.md"
    }


def test_zenmux_responses_parser_maps_reasoning_and_output_text():
    adapter = ZenMuxAdapter(api_key="key")

    result = adapter._parse_responses_response(
        {
            "model": "deepseek/deepseek-v4-pro-free",
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "reasoning summary"}],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Final answer"}],
                },
            ],
            "usage": {"output_tokens": 12},
        },
        "deepseek/deepseek-v4-pro-free",
    )

    assert result.reasoning_content == "reasoning summary"
    assert result.content == "Final answer"
    assert result.finish_reason == "completed"
    assert result.metadata["zenmux_responses_reasoning"][0]["type"] == "reasoning"


def test_zenmux_model_catalog_marks_deepseek_free_models_as_reasoning_chat():
    adapter = ZenMuxAdapter(api_key="key")

    catalog = adapter._normalize_model_response(
        {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash-free",
                    "owned_by": "deepseek",
                    "capabilities": {"reasoning": True},
                    "context_length": 1_000_000,
                },
                {
                    "id": "deepseek/deepseek-v4-pro-free",
                    "owned_by": "deepseek",
                    "capabilities": {"reasoning": True},
                    "context_length": 1_000_000,
                },
            ]
        }
    )

    filtered = adapter._filter_model_response(catalog, "reasoning_chat")

    assert catalog["provider"] == "zenmux"
    assert [model["id"] for model in filtered["data"]] == [
        "deepseek/deepseek-v4-flash-free",
        "deepseek/deepseek-v4-pro-free",
    ]
    assert filtered["data"][0]["context_length"] == 1_000_000
    assert filtered["data"][0]["supports_tools"] is True


def test_zenmux_payload_preserves_reasoning_history_for_tool_replay():
    adapter = ZenMuxAdapter(api_key="key")

    payload = adapter._build_payload(
        [
            {
                "role": "assistant",
                "content": "",
                "metadata": {
                    "reasoning_content": "Need a file read.",
                    "zenmux_reasoning_details": [
                        {"type": "reasoning.text", "text": "Need a file read."}
                    ],
                },
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "README"},
        ],
        0.7,
        -1,
        False,
        {"model": "deepseek/deepseek-v4-flash-free"},
    )

    assistant = payload["messages"][0]
    assert assistant["reasoning_content"] == "Need a file read."
    assert assistant["reasoning_details"][0]["text"] == "Need a file read."
