from personagent.infrastructure.llm.codex_payload import CodexPayloadBuilder


def test_build_payload_uses_default_model_when_not_specified():
    builder = CodexPayloadBuilder(default_model="gpt-5.5")
    payload = builder.build_payload(
        [{"role": "user", "content": "hello"}],
        max_tokens=-1,
        extra={},
        tools=None,
        tool_choice=None,
        stream=True,
    )
    assert payload["model"] == "gpt-5.5"


def test_build_payload_uses_requested_model():
    builder = CodexPayloadBuilder(default_model="gpt-5.5")
    payload = builder.build_payload(
        [{"role": "user", "content": "hello"}],
        max_tokens=-1,
        extra={"model": "gpt-5.4-mini"},
        tools=None,
        tool_choice=None,
        stream=False,
    )
    assert payload["model"] == "gpt-5.4-mini"


def test_build_payload_falls_back_to_default_for_local_model():
    builder = CodexPayloadBuilder(default_model="gpt-5.5")
    payload = builder.build_payload(
        [{"role": "user", "content": "hello"}],
        max_tokens=-1,
        extra={"model": "local-model"},
        tools=None,
        tool_choice=None,
        stream=True,
    )
    assert payload["model"] == "gpt-5.5"


def test_build_payload_includes_reasoning_for_max_level():
    builder = CodexPayloadBuilder()
    payload = builder.build_payload(
        [{"role": "user", "content": "think hard"}],
        max_tokens=-1,
        extra={"reasoning_level": "max"},
        tools=None,
        tool_choice=None,
        stream=True,
    )
    assert payload["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert payload["include"] == ["reasoning.encrypted_content"]


def test_build_payload_includes_tools_when_provided():
    builder = CodexPayloadBuilder()
    payload = builder.build_payload(
        [{"role": "user", "content": "do it"}],
        max_tokens=-1,
        extra={},
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
        stream=True,
    )
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "strict": False,
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True


def test_convert_messages_splits_system_and_user():
    builder = CodexPayloadBuilder()
    instructions, input_items = builder.convert_messages(
        [
            {"role": "system", "content": "You are PersonAgent."},
            {"role": "user", "content": "hello"},
        ]
    )
    assert instructions == "You are PersonAgent."
    assert input_items == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]


def test_convert_messages_handles_tool_role():
    builder = CodexPayloadBuilder()
    instructions, input_items = builder.convert_messages(
        [
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        ]
    )
    assert instructions is None
    assert input_items == [
        {"type": "function_call_output", "call_id": "call_1", "output": "result"}
    ]


def test_convert_messages_handles_assistant_with_tool_calls():
    builder = CodexPayloadBuilder()
    instructions, input_items = builder.convert_messages(
        [
            {
                "role": "assistant",
                "content": "I will read it.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
        ]
    )
    assert input_items[0] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "I will read it."}],
    }
    assert input_items[1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "read_file",
        "arguments": '{"path":"README.md"}',
    }


def test_convert_tools_skips_invalid_entries():
    builder = CodexPayloadBuilder()
    result = builder.convert_tools([{"not_a_function": {}}, 123, None])
    assert result == []


def test_convert_tool_choice_dict_with_function():
    builder = CodexPayloadBuilder()
    result = builder.convert_tool_choice({"type": "function", "function": {"name": "read_file"}})
    assert result == {"type": "function", "name": "read_file"}


def test_convert_tool_choice_fallback_to_auto():
    builder = CodexPayloadBuilder()
    assert builder.convert_tool_choice("invalid") == "auto"
    assert builder.convert_tool_choice(None) == "auto"
    assert builder.convert_tool_choice("none") == "none"


def test_history_tool_call_normalizes_arguments():
    builder = CodexPayloadBuilder()
    result = builder.history_tool_call(
        {"id": "c1", "function": {"name": "fn", "arguments": {"key": "val"}}}
    )
    assert result is not None
    assert result["arguments"] == '{"key": "val"}'


def test_message_text_with_list_content():
    builder = CodexPayloadBuilder()
    assert builder.message_text([{"text": "hello"}, {"content": "world"}]) == "hello\nworld"
    assert builder.message_text(["a", "b"]) == "a\nb"


def test_message_text_with_none():
    builder = CodexPayloadBuilder()
    assert builder.message_text(None) == ""


def test_reasoning_effort_by_budget():
    builder = CodexPayloadBuilder()
    assert builder.reasoning_effort({"reasoning_budget_tokens": 100}) == "low"
    assert builder.reasoning_effort({"reasoning_budget_tokens": 5000}) == "medium"
    assert builder.reasoning_effort({"reasoning_budget_tokens": 10000}) == "high"
    assert builder.reasoning_effort({"reasoning_budget_tokens": 40000}) == "xhigh"


def test_reasoning_effort_returns_none_when_not_specified():
    builder = CodexPayloadBuilder()
    assert builder.reasoning_effort({}) is None
    assert builder.reasoning_effort({"reasoning_level": ""}) is None
