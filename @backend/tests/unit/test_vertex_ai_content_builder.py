"""Unit tests for VertexContentBuilder — message conversion, tool formatting, thinking config."""


from personagent.infrastructure.llm.vertex_ai.content_builder import VertexContentBuilder
from personagent.infrastructure.llm.vertex_ai.models import VERTEX_MODELS_BY_ID


def _builder(**kwargs: object) -> VertexContentBuilder:
    return VertexContentBuilder(
        default_model=str(kwargs.get("default_model", "gemini-3.1-flash-lite-preview")),
        default_max_tokens=int(kwargs.get("default_max_tokens", 65536)),
    )


def test_build_payload_returns_model_and_payload_with_system_and_user_roles():
    builder = _builder()
    payload, model = builder.build_payload(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-3.1-flash-lite-preview", "reasoning_level": "low"},
    )
    assert model == "gemini-3.1-flash-lite-preview"
    assert payload["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert payload["generationConfig"]["temperature"] == 0.2
    assert payload["generationConfig"]["maxOutputTokens"] == 512


def test_build_payload_falls_back_to_default_model_when_requested_model_is_empty():
    builder = _builder(default_model="gemini-2.5-flash")
    payload, model = builder.build_payload(
        [{"role": "user", "content": "hi"}], 0.5, 100, {}
    )
    assert model == "gemini-2.5-flash"


def test_build_payload_falls_back_to_default_model_when_local_model_marker():
    builder = _builder(default_model="gemini-3-flash-preview")
    payload, model = builder.build_payload(
        [{"role": "user", "content": "hi"}], 0.5, 100, {"model": "local-model"}
    )
    assert model == "gemini-3-flash-preview"


def test_build_payload_respects_explicit_model_override():
    builder = _builder()
    payload, model = builder.build_payload(
        [{"role": "user", "content": "hi"}], 0.3, 256, {"model": "gemini-2.5-flash-lite"}
    )
    assert model == "gemini-2.5-flash-lite"


def test_convert_messages_multiple_system_joined_by_double_newline():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-lite-preview"]
    system, contents = builder._convert_messages(
        [{"role": "system", "content": "Rule A."},
         {"role": "system", "content": "Rule B."},
         {"role": "user", "content": "ok"}],
        spec,
    )
    assert system == "Rule A.\n\nRule B."
    assert contents == [{"role": "user", "parts": [{"text": "ok"}]}]


def test_convert_messages_copes_with_empty_system_message():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-lite-preview"]
    system, contents = builder._convert_messages(
        [{"role": "system", "content": ""}, {"role": "user", "content": "yo"}],
        spec,
    )
    assert system == ""
    assert contents == [{"role": "user", "parts": [{"text": "yo"}]}]


def test_convert_messages_serializes_tool_result_as_user_function_response():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3-flash-preview"]
    _system, contents = builder._convert_messages(
        [
            {"role": "user", "content": "Search."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {"name": "Search", "arguments": '{"q":"x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-0", "content": '{"hits":1}'},
        ],
        spec,
    )
    assert contents == [
        {"role": "user", "parts": [{"text": "Search."}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {"name": "Search", "args": {"q": "x"}},
                    "thoughtSignature": "skip_thought_signature_validator",
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "Search",
                        "response": {"output": '{"hits":1}'},
                    }
                }
            ],
        },
    ]
    assert "function" not in {c["role"] for c in contents}


def test_convert_messages_replays_original_tool_call_parts_with_signatures():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3-flash-preview"]
    original_parts = [
        {"text": "Thinking...", "thought": True, "thoughtSignature": "sig-1"},
        {"functionCall": {"name": "Search", "args": {"q": "x"}}},
    ]
    _system, contents = builder._convert_messages(
        [
            {"role": "user", "content": "Find it."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {"name": "Search", "arguments": '{}'},
                        "extra_content": {
                            "google": {
                                "thought_signature": "sig-1",
                                "content_parts": original_parts,
                            }
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-0", "content": "done"},
        ],
        spec,
    )
    assert contents[1] == {"role": "model", "parts": original_parts}


def test_convert_messages_adds_skip_signature_for_unsigned_gemini_3_function_calls():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3-flash-preview"]
    _system, contents = builder._convert_messages(
        [
            {"role": "user", "content": "Search."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {"name": "Search", "arguments": '{"q":"x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-0", "content": "ok"},
        ],
        spec,
    )
    parts = contents[1]["parts"]
    assert len(parts) == 1
    assert parts[0]["thoughtSignature"] == "skip_thought_signature_validator"


def test_convert_messages_does_not_add_signature_for_non_gemini_3_models():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-2.5-flash"]
    _system, contents = builder._convert_messages(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {"name": "F", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-0", "content": "ok"},
        ],
        spec,
    )
    parts = contents[1]["parts"]
    assert "thoughtSignature" not in parts[0]


def test_convert_messages_always_produces_non_empty_contents():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-lite-preview"]
    _system, contents = builder._convert_messages([], spec)
    assert contents == [{"role": "user", "parts": [{"text": ""}]}]


def test_build_payload_uses_thinking_budget_for_gemini_2_5_models():
    builder = _builder()
    payload, model = builder.build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-2.5-flash-lite", "reasoning_level": "low", "reasoning_budget_tokens": 128},
    )
    assert model == "gemini-2.5-flash-lite"
    assert payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingBudget": 512,
    }


def test_build_payload_clamps_thinking_budget_to_model_max():
    builder = _builder()
    payload, _model = builder.build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-2.5-flash", "reasoning_level": "max", "reasoning_budget_tokens": 32768},
    )
    assert payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 24576


def test_build_payload_maps_zero_budget_to_reasoning_preset():
    builder = _builder()
    payload, _model = builder.build_payload(
        [{"role": "user", "content": "hi"}],
        0,
        1024,
        {"model": "gemini-2.5-flash-lite", "reasoning_level": "low", "reasoning_budget_tokens": 0},
    )
    assert payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 2048


def test_build_payload_uses_thinking_level_for_gemini_3_models():
    builder = _builder()
    payload, _model = builder.build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-3.1-flash-lite-preview", "reasoning_level": "medium"},
    )
    assert payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingLevel": "MEDIUM",
    }
    assert "thinkingBudget" not in payload["generationConfig"]["thinkingConfig"]


def test_build_payload_maps_high_reasoning_level_correctly():
    builder = _builder()
    for level, expected in [("high", "HIGH"), ("xhigh", "HIGH"), ("max", "HIGH"), ("low", "LOW")]:
        payload, _ = builder.build_payload(
            [{"role": "user", "content": "hi"}],
            0.2,
            512,
            {"model": "gemini-3.1-pro-preview", "reasoning_level": level},
        )
        assert payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == expected


def test_build_payload_adds_response_modalities_for_image_models():
    builder = _builder()
    payload, _model = builder.build_payload(
        [{"role": "user", "content": "render"}],
        0.4,
        -1,
        {"model": "gemini-3.1-flash-image-preview", "reasoning_level": "xhigh"},
    )
    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]


def test_build_payload_omits_thinking_config_for_non_thinking_models():
    builder = _builder()
    payload, _model = builder.build_payload(
        [{"role": "user", "content": "render"}],
        0.4,
        -1,
        {"model": "gemini-3-pro-image-preview", "reasoning_level": "high"},
    )
    assert "thinkingConfig" not in payload["generationConfig"]
    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]


def test_effective_max_tokens_clamps_to_65535_for_65536_output_models():
    builder = _builder(default_max_tokens=65536)
    spec = VERTEX_MODELS_BY_ID["gemini-2.5-flash-lite"]
    assert builder._effective_max_tokens(spec, 65536) == 65535


def test_effective_max_tokens_uses_default_when_requested_is_negative():
    builder = _builder(default_max_tokens=4096)
    spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-lite-preview"]
    assert builder._effective_max_tokens(spec, -1) == 4096


def test_effective_max_tokens_respects_requested_when_positive():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-lite-preview"]
    assert builder._effective_max_tokens(spec, 1024) == 1024


def test_function_declarations_filters_non_function_tools_and_missing_names():
    builder = _builder()
    decls = builder._function_declarations([
        {"type": "json_schema", "function": {"name": "F1"}},
        {"type": "function", "function": {"name": ""}},
        {"type": "function", "function": {}},
        {"type": "function", "function": {"name": "Search", "description": "desc", "parameters": {"type": "object"}}},
    ])
    assert len(decls) == 1
    assert decls[0] == {"name": "Search", "description": "desc", "parameters": {"type": "object"}}


def test_build_payload_includes_tools_when_model_supports_tools():
    builder = _builder()
    payload, _ = builder.build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-3-flash-preview"},
        tools=[{"type": "function", "function": {"name": "Search"}}],
    )
    assert "tools" in payload


def test_build_payload_omits_tools_for_image_only_models():
    builder = _builder()
    payload, _ = builder.build_payload(
        [{"role": "user", "content": "render"}],
        0.4,
        -1,
        {"model": "gemini-3.1-flash-image-preview"},
        tools=[{"type": "function", "function": {"name": "Search"}}],
    )
    assert "tools" not in payload


def test_json_args_parses_string_json():
    builder = _builder()
    assert builder._json_args('{"a":1}') == {"a": 1}


def test_json_args_passes_through_dict():
    builder = _builder()
    assert builder._json_args({"b": 2}) == {"b": 2}


def test_json_args_wraps_non_dict_json_in_value():
    builder = _builder()
    assert builder._json_args("hello") == {"value": "hello"}


def test_json_args_returns_empty_for_missing_input():
    builder = _builder()
    assert builder._json_args(None) == {}


def test_content_parts_from_tool_calls_returns_none_for_missing_extra_content():
    builder = _builder()
    result = builder._content_parts_from_tool_calls([{"type": "function"}])
    assert result is None


def test_content_parts_from_tool_calls_returns_normalized_parts():
    builder = _builder()
    result = builder._content_parts_from_tool_calls([
        {"extra_content": {"google": {"content_parts": [{"text": "hi"}, "bad", {"fn": True}]}}}
    ])
    assert result == [{"text": "hi"}, {"fn": True}]


def test_convert_messages_track_tool_names_for_function_response_lookup():
    builder = _builder()
    spec = VERTEX_MODELS_BY_ID["gemini-3-flash-preview"]
    _system, contents = builder._convert_messages(
        [
            {"role": "user", "content": "action"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "my-id",
                        "type": "function",
                        "function": {"name": "DoIt", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "my-id", "content": "result"},
        ],
        spec,
    )
    response = contents[2]["parts"][0]["functionResponse"]
    assert response["name"] == "DoIt"
    assert response["response"]["output"] == "result"
