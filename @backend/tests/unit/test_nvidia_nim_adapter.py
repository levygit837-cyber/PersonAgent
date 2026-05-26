import json

from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
from personagent.infrastructure.llm.shared.openai_compatible_parser import (
    ThinkingTagState,
    normalize_message_content,
)


def test_nvidia_adapter_sets_bearer_header_without_exposing_key():
    adapter = NvidiaNimAdapter(api_key="nvapi_test_secret")

    assert adapter.headers["Authorization"] == "Bearer nvapi_test_secret"
    assert "nvapi_test_secret" not in repr(adapter)


def test_nvidia_payload_uses_reasoning_chat_template_and_supported_budget():
    adapter = NvidiaNimAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        256,
        True,
        {
            "model": "nvidia/nemotron-3-nano-30b-a3b",
            "reasoning_budget_tokens": 128,
        },
    )

    assert payload["model"] == "nvidia/nemotron-3-nano-30b-a3b"
    assert payload["stream"] is True
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert payload["nvext"] == {"max_thinking_tokens": 128}
    assert payload["max_tokens"] == 4096


def test_nvidia_payload_defaults_to_64k_output_and_caps_reasoning_budget():
    adapter = NvidiaNimAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        -1,
        True,
        {
            "model": "nvidia/nemotron-3-nano-30b-a3b",
            "reasoning_budget_tokens": 50000,
        },
    )

    assert payload["max_tokens"] == 65536
    assert payload["nvext"] == {"max_thinking_tokens": 32768}


def test_nvidia_stream_read_timeout_is_disabled_by_default():
    adapter = NvidiaNimAdapter(api_key="key")

    timeout = adapter._stream_timeout_config()

    assert timeout.read is None
    assert timeout.connect == 30.0
    assert timeout.write == 120.0
    assert timeout.pool == 30.0
    assert adapter._stream_timeout_label() == "read timeout disabled"


def test_nvidia_stream_read_timeout_can_be_configured():
    adapter = NvidiaNimAdapter(
        api_key="key",
        timeout=45.0,
        stream_read_timeout=300.0,
    )

    timeout = adapter._stream_timeout_config()

    assert timeout.read == 300.0
    assert timeout.connect == 30.0
    assert timeout.write == 45.0
    assert timeout.pool == 30.0
    assert adapter._stream_timeout_label() == "read timeout 300.0s"


def test_nvidia_payload_ignores_budget_for_models_without_budget_support():
    adapter = NvidiaNimAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        256,
        False,
        {
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "reasoning_budget_tokens": 128,
        },
    )

    assert "nvext" not in payload


def test_nvidia_payload_omits_thinking_template_for_unsupported_models():
    adapter = NvidiaNimAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        256,
        False,
        {
            "model": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "reasoning_budget_tokens": 128,
        },
    )

    assert "chat_template_kwargs" not in payload
    assert "nvext" not in payload


def test_nvidia_payload_enables_qwen_thinking_template_without_nemotron_budget():
    adapter = NvidiaNimAdapter(api_key="key")

    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        256,
        True,
        {
            "model": "qwen/qwen3.5-397b-a17b",
            "reasoning_budget_tokens": 128,
        },
    )

    assert payload["model"] == "qwen/qwen3.5-397b-a17b"
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert "nvext" not in payload


def test_parser_separates_reasoning_fields_and_think_tags():
    content, reasoning = normalize_message_content(
        {
            "content": "<think>internal path</think>Final answer",
            "reasoning_content": "field reasoning ",
        }
    )

    assert content == "Final answer"
    assert reasoning == "field reasoning internal path"


def test_parser_accepts_qwen_reasoning_content_without_visible_think_tags():
    content, reasoning = normalize_message_content(
        {
            "content": "```json\n{\"approve\": false}\n```",
            "reasoning_content": "Let me analyze this voting scenario carefully.",
        }
    )

    assert content == "```json\n{\"approve\": false}\n```"
    assert reasoning == "Let me analyze this voting scenario carefully."


def test_parser_handles_qwen_text_when_opening_think_tag_was_in_prompt():
    content, reasoning = normalize_message_content(
        {
            "content": "Let me analyze this scenario.</think>\n\nFinal answer",
        }
    )

    assert content == "\n\nFinal answer"
    assert reasoning == "Let me analyze this scenario."


def test_parser_accepts_additional_thinking_tag_names():
    content, reasoning = normalize_message_content(
        {
            "content": "<thinking>hidden path</thinking>Visible answer",
            "thinking_content": "field thinking ",
        }
    )

    assert content == "Visible answer"
    assert reasoning == "field thinking hidden path"


def test_stream_parser_supports_think_tags_split_between_chunks():
    adapter = NvidiaNimAdapter(api_key="key")
    state = ThinkingTagState()

    chunk_1 = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {"content": "<thi"},
                    "finish_reason": None,
                }
            ]
        },
        "nvidia/nemotron-3-nano-30b-a3b",
        thinking_state=state,
    )
    chunk_2 = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {"content": "nk>hidden</think>visible"},
                    "finish_reason": "stop",
                }
            ],
            "model": "nvidia/nemotron-3-nano-30b-a3b",
        },
        "nvidia/nemotron-3-nano-30b-a3b",
        thinking_state=state,
    )

    assert chunk_1.is_empty
    assert chunk_2.reasoning_content == "hidden"
    assert chunk_2.content == "visible"
    assert chunk_2.is_thinking is False
    assert chunk_2.metadata["provider"] == "nvidia"


def test_nvidia_stream_parser_keeps_kimi_mixed_content_visible():
    adapter = NvidiaNimAdapter(api_key="key")

    chunk = adapter._parse_stream_chunk(
        {
            "model": "moonshotai/kimi-k2.6",
            "choices": [
                {
                    "delta": {
                        "content": " OK",
                        "reasoning": ".",
                    },
                    "finish_reason": "stop",
                }
            ],
        },
        "moonshotai/kimi-k2.6",
    )

    assert chunk.content == " OK"
    assert chunk.reasoning_content == "."
    assert chunk.is_thinking is False


def test_nvidia_stream_tool_call_parsing_stays_open_until_finish():
    adapter = NvidiaNimAdapter(api_key="key")
    accumulator = {}

    first = adapter._parse_stream_chunk(
        {
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
                                    "arguments": '{"path":"',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        "nvidia/nemotron-3-nano-30b-a3b",
        accumulator,
    )
    second = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": 'README.md"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        "nvidia/nemotron-3-nano-30b-a3b",
        accumulator,
    )

    assert first.is_empty
    assert second.tool_calls is not None
    assert json.loads(second.tool_calls[0]["function"]["arguments"]) == {"path": "README.md"}


def test_nvidia_stream_tool_call_parser_handles_repeated_full_function_name():
    adapter = NvidiaNimAdapter(api_key="key")
    accumulator = {}

    first = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": None,
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        "minimaxai/minimax-m2.5",
        accumulator,
    )
    second = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command": "pwd"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        "minimaxai/minimax-m2.5",
        accumulator,
    )

    assert first.is_empty
    assert second.tool_calls is not None
    call = second.tool_calls[0]
    assert call["function"]["name"] == "shell"
    assert json.loads(call["function"]["arguments"]) == {"command": "pwd"}


def test_nvidia_model_catalog_filters_reasoning_chat_models():
    adapter = NvidiaNimAdapter(api_key="key")
    catalog = adapter._normalize_model_response(
        {
            "data": [
                {"id": "deepseek-ai/deepseek-v4-flash"},
                {"id": "deepseek-ai/deepseek-v4-pro"},
                {"id": "nvidia/nemotron-3-nano-30b-a3b"},
                {"id": "nvidia/llama-nemotron-embed-1b-v2"},
                {"id": "nvidia/nemotron-3-content-safety"},
                {"id": "moonshotai/kimi-k2.6"},
            ]
        }
    )

    filtered = adapter._filter_model_response(catalog, "reasoning_chat")
    ids = [model["id"] for model in filtered["data"]]

    assert ids == [
        "deepseek-ai/deepseek-v4-flash",
        "deepseek-ai/deepseek-v4-pro",
        "nvidia/nemotron-3-nano-30b-a3b",
        "moonshotai/kimi-k2.6",
    ]
    assert filtered["data"][0]["supports_streaming"] is True
    assert filtered["data"][0]["supports_reasoning"] is True
