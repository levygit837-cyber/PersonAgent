import json

from personagent.infrastructure.llm.deepseek_adapter import DeepSeekAdapter


def test_deepseek_payload_uses_official_v4_thinking_contract():
    adapter = DeepSeekAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.7,
        256,
        True,
        {
            "model": "deepseek-v4-pro",
            "reasoning_level": "xhigh",
        },
    )

    assert payload["model"] == "deepseek-v4-pro"
    assert payload["stream"] is True
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["max_tokens"] == 4096
    assert "temperature" not in payload


def test_deepseek_payload_preserves_reasoning_content_for_tool_history():
    adapter = DeepSeekAdapter(api_key="key")
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "Need a file read.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "README"},
    ]

    payload = adapter._build_payload(messages, 0.7, -1, False, {"model": "deepseek-v4-flash"})

    assert payload["messages"][0]["reasoning_content"] == "Need a file read."
    assert payload["messages"][0]["tool_calls"][0]["id"] == "call_1"


def test_deepseek_stream_parser_separates_reasoning_content_and_tool_calls():
    adapter = DeepSeekAdapter(api_key="key")
    accumulator = {}

    thinking = adapter._parse_stream_chunk(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "delta": {"reasoning_content": "I should inspect the file."},
                    "finish_reason": None,
                }
            ],
        },
        "deepseek-v4-flash",
        accumulator,
    )
    tool_call = adapter._parse_stream_chunk(
        {
            "model": "deepseek-v4-flash",
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
        "deepseek-v4-flash",
        accumulator,
    )

    assert thinking.reasoning_content == "I should inspect the file."
    assert thinking.content == ""
    assert thinking.is_thinking is True
    assert thinking.metadata["provider"] == "deepseek"
    assert tool_call.tool_calls is not None
    assert tool_call.tool_calls[0]["function"]["name"] == "read_file"
    assert json.loads(tool_call.tool_calls[0]["function"]["arguments"]) == {
        "path": "README.md"
    }


def test_deepseek_model_catalog_marks_v4_models_as_reasoning_chat():
    adapter = DeepSeekAdapter(api_key="key")

    catalog = adapter._normalize_model_response(
        {
            "data": [
                {"id": "deepseek-v4-flash", "owned_by": "deepseek"},
                {"id": "deepseek-v4-pro", "owned_by": "deepseek"},
            ]
        }
    )

    filtered = adapter._filter_model_response(catalog, "reasoning_chat")

    assert catalog["provider"] == "deepseek"
    assert [model["id"] for model in filtered["data"]] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert filtered["data"][0]["context_length"] == 1_000_000
