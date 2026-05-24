import httpx
import pytest

from personagent.domain.exceptions import LLMBackendConnectionError
from personagent.infrastructure.llm.vertex_ai import VERTEX_MODELS, VertexAiAdapter


def test_vertex_catalog_contains_curated_gemini_models_without_deprecated_pro():
    adapter = VertexAiAdapter(api_key="google-test-key")

    catalog_items = [adapter._model_to_catalog_item(model) for model in VERTEX_MODELS]
    ids = {item["id"] for item in catalog_items}

    assert ids == {
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview-customtools",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-3-flash-preview",
        "gemini-3-pro-image-preview",
    }
    assert "gemini-3-pro-preview" not in ids
    assert all("chat" in item["capabilities"] for item in catalog_items)
    assert all("image_input" in item["capabilities"] for item in catalog_items)
    assert "thinking" in {capability for item in catalog_items for capability in item["capabilities"]}
    catalog = {str(item["id"]): item for item in catalog_items}
    assert "thinking" not in catalog["gemini-3-pro-image-preview"]["capabilities"]
    assert catalog["gemini-2.5-flash-lite"]["launch_stage"] == "ga"
    assert catalog["gemini-2.5-flash"]["launch_stage"] == "ga"


def test_vertex_catalog_marks_image_output_and_tool_capabilities():
    adapter = VertexAiAdapter(api_key="google-test-key")

    catalog = {model["id"]: model for model in [adapter._model_to_catalog_item(item) for item in VERTEX_MODELS]}

    assert "image_output" in catalog["gemini-3.1-flash-image-preview"]["capabilities"]
    assert "image_generation" in catalog["gemini-3-pro-image-preview"]["capabilities"]
    assert "tools" not in catalog["gemini-3.1-flash-image-preview"]["capabilities"]
    assert "tools" in catalog["gemini-3.1-pro-preview-customtools"]["capabilities"]


def test_vertex_payload_uses_include_thoughts_and_reasoning_level_mapping():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)

    payload, model = adapter._build_payload(
        [{"role": "system", "content": "You are concise."}, {"role": "user", "content": "hi"}],
        0.2,
        512,
        {"model": "gemini-3.1-flash-lite-preview", "reasoning_level": "medium"},
    )

    assert model == "gemini-3.1-flash-lite-preview"
    assert payload["systemInstruction"] == {"parts": [{"text": "You are concise."}]}
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]
    assert payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingLevel": "MEDIUM",
    }
    assert payload["generationConfig"]["maxOutputTokens"] == 512
    assert "responseModalities" not in payload["generationConfig"]


def test_vertex_payload_serializes_tool_result_as_user_function_response():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)

    payload, _model = adapter._build_payload(
        [
            {"role": "user", "content": "Search LangChain."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "vertex-call-0",
                        "type": "function",
                        "function": {
                            "name": "BrowserSearch",
                            "arguments": '{"query":"LangChain"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "vertex-call-0",
                "content": '{"results":[{"title":"LangChain"}]}',
            },
        ],
        0.2,
        512,
        {"model": "gemini-3-flash-preview", "reasoning_level": "low"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "BrowserSearch",
                    "description": "Search the web.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
    )

    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "Search LangChain."}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": "BrowserSearch",
                        "args": {"query": "LangChain"},
                    },
                    "thoughtSignature": "skip_thought_signature_validator",
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "BrowserSearch",
                        "response": {"output": '{"results":[{"title":"LangChain"}]}'},
                    }
                }
            ],
        },
    ]
    assert "function" not in {content["role"] for content in payload["contents"]}


def test_vertex_payload_replays_original_tool_call_parts_with_thought_signatures():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)
    original_parts = [
        {
            "text": "Investigating LangChain Framework",
            "thought": True,
            "thoughtSignature": "sig-text-part",
        },
        {
            "functionCall": {
                "name": "BrowserSearch",
                "args": {"query": "o que é o framework langchain"},
            }
        },
    ]

    payload, _model = adapter._build_payload(
        [
            {"role": "user", "content": "Search LangChain."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "vertex-call-0",
                        "type": "function",
                        "function": {
                            "name": "BrowserSearch",
                            "arguments": '{"query":"LangChain"}',
                        },
                        "extra_content": {
                            "google": {
                                "thought_signature": "sig-text-part",
                                "content_parts": original_parts,
                            }
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "vertex-call-0",
                "content": '{"results":[{"title":"LangChain"}]}',
            },
        ],
        0.2,
        512,
        {"model": "gemini-3-flash-preview", "reasoning_level": "low"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "BrowserSearch",
                    "description": "Search the web.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
    )

    assert payload["contents"][1] == {"role": "model", "parts": original_parts}


def test_vertex_payload_adds_skip_signature_when_gemini_3_returns_unsigned_function_call():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)
    original_parts = [
        {
            "functionCall": {
                "name": "BrowserSearch",
                "args": {"query": "o que é o framework langchain"},
            }
        },
    ]

    payload, _model = adapter._build_payload(
        [
            {"role": "user", "content": "Search LangChain."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "vertex-call-0",
                        "type": "function",
                        "function": {
                            "name": "BrowserSearch",
                            "arguments": '{"query":"LangChain"}',
                        },
                        "extra_content": {"google": {"content_parts": original_parts}},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "vertex-call-0",
                "content": '{"results":[{"title":"LangChain"}]}',
            },
        ],
        0.2,
        512,
        {"model": "gemini-3-flash-preview", "reasoning_level": "low"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "BrowserSearch",
                    "description": "Search the web.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
    )

    assert payload["contents"][1]["parts"] == [
        {
            "functionCall": {
                "name": "BrowserSearch",
                "args": {"query": "o que é o framework langchain"},
            },
            "thoughtSignature": "skip_thought_signature_validator",
        }
    ]


def test_vertex_stream_parser_keeps_original_tool_call_parts_for_replay():
    adapter = VertexAiAdapter(api_key="google-test-key")

    chunks, _signatures = adapter._stream_chunks_from_data(
        {
            "modelVersion": "gemini-3-flash-preview",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "text": "Investigating LangChain Framework",
                                "thought": True,
                                "thoughtSignature": "sig-text-part",
                            },
                            {
                                "functionCall": {
                                    "name": "BrowserSearch",
                                    "args": {"query": "o que é o framework langchain"},
                                }
                            },
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
    assert google["content_parts"] == [
        {
            "text": "Investigating LangChain Framework",
            "thought": True,
            "thoughtSignature": "sig-text-part",
        },
        {
            "functionCall": {
                "name": "BrowserSearch",
                "args": {"query": "o que é o framework langchain"},
            }
        },
    ]


def test_vertex_payload_uses_thinking_budget_for_gemini_25_models():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)

    flash_lite_payload, _model = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {
            "model": "gemini-2.5-flash-lite",
            "reasoning_level": "low",
            "reasoning_budget_tokens": 128,
        },
    )
    flash_payload, _model = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.2,
        512,
        {
            "model": "gemini-2.5-flash",
            "reasoning_level": "max",
            "reasoning_budget_tokens": 32768,
        },
    )

    assert flash_lite_payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingBudget": 512,
    }
    assert flash_payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingBudget": 24576,
    }
    assert "thinkingLevel" not in flash_lite_payload["generationConfig"]["thinkingConfig"]
    assert "thinkingLevel" not in flash_payload["generationConfig"]["thinkingConfig"]


def test_vertex_payload_maps_zero_budget_to_reasoning_preset_for_gemini_25_models():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=2048)

    payload, _model = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0,
        1024,
        {
            "model": "gemini-2.5-flash-lite",
            "reasoning_level": "low",
            "reasoning_budget_tokens": 0,
        },
    )

    assert payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingBudget": 2048,
    }


def test_vertex_payload_clamps_exclusive_65536_output_bound():
    adapter = VertexAiAdapter(api_key="google-test-key", default_max_tokens=65536)

    payload, _model = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0,
        65536,
        {
            "model": "gemini-2.5-flash-lite",
            "reasoning_level": "low",
            "reasoning_budget_tokens": 2048,
        },
    )

    assert payload["generationConfig"]["maxOutputTokens"] == 65535


def test_vertex_payload_enables_text_and_image_response_modalities_for_image_models():
    adapter = VertexAiAdapter(api_key="google-test-key")

    payload, _model = adapter._build_payload(
        [{"role": "user", "content": "generate a small image"}],
        0.4,
        -1,
        {"model": "gemini-3.1-flash-image-preview", "reasoning_level": "xhigh"},
    )

    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "HIGH"


def test_vertex_payload_omits_thinking_config_for_pro_image_model():
    adapter = VertexAiAdapter(api_key="google-test-key")

    payload, _model = adapter._build_payload(
        [{"role": "user", "content": "generate a small image"}],
        0.4,
        -1,
        {"model": "gemini-3-pro-image-preview", "reasoning_level": "high"},
    )

    assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert "thinkingConfig" not in payload["generationConfig"]


def test_vertex_parser_splits_thought_text_final_text_and_preserves_signature():
    adapter = VertexAiAdapter(api_key="google-test-key")

    result = adapter._parse_inference_result(
        {
            "modelVersion": "gemini-3.1-flash-lite-preview",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "text": "I should solve this privately.",
                                "thought": True,
                                "thoughtSignature": "sig-123",
                            },
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


def test_vertex_parser_accepts_string_thought_marker():
    adapter = VertexAiAdapter(api_key="google-test-key")

    result = adapter._parse_inference_result(
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


def test_vertex_parser_extracts_inline_data_as_generated_image():
    adapter = VertexAiAdapter(api_key="google-test-key")

    result = adapter._parse_inference_result(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Rendered image:"},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": "iVBORw0KGgo=",
                                }
                            },
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
    assert result.images[0].to_dict() == {
        "mime_type": "image/png",
        "data": "iVBORw0KGgo=",
        "alt": "Generated image",
    }


def test_vertex_stream_parser_emits_reasoning_content_and_images_in_order():
    adapter = VertexAiAdapter(api_key="google-test-key")

    chunks, signatures = adapter._stream_chunks_from_data(
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


@pytest.mark.asyncio
async def test_vertex_stream_events_parse_incremental_json_array_responses():
    adapter = VertexAiAdapter(api_key="google-test-key")

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

    events = [event async for event in adapter._stream_events(FakeResponse())]

    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "hello"
    assert events[1]["candidates"][0]["finishReason"] == "STOP"


def test_vertex_auth_strategy_prefers_api_key_in_auto_mode_and_builds_express_path():
    adapter = VertexAiAdapter(api_key="google-test-key", auth_mode="auto")

    assert adapter._auth_strategy() == "api_key"
    assert adapter._base_url() == "https://aiplatform.googleapis.com/v1"
    assert (
        adapter._request_path("gemini-3.1-flash-lite-preview", stream=False)
        == "/publishers/google/models/gemini-3.1-flash-lite-preview:generateContent"
    )


def test_vertex_auth_strategy_uses_adc_path_when_forced():
    adapter = VertexAiAdapter(
        api_key="google-test-key",
        auth_mode="adc",
        project_id="project-a",
        location="us-central1",
    )

    assert adapter._auth_strategy() == "adc"
    assert adapter._base_url() == "https://us-central1-aiplatform.googleapis.com/v1"
    assert (
        adapter._request_path("gemini-3.1-flash-lite-preview", stream=True)
        == "/projects/project-a/locations/us-central1/publishers/google/"
        "models/gemini-3.1-flash-lite-preview:streamGenerateContent"
    )


def test_vertex_auth_strategy_requires_api_key_when_express_mode_is_forced():
    adapter = VertexAiAdapter(api_key="", auth_mode="express")

    with pytest.raises(LLMBackendConnectionError, match="GOOGLE_API_KEY"):
        adapter._auth_strategy()


def test_vertex_http_error_extracts_json_array_error_body():
    adapter = VertexAiAdapter(api_key="google-test-key")
    request = httpx.Request("POST", "https://aiplatform.googleapis.com/v1/test")
    response = httpx.Response(
        400,
        json=[
            {
                "error": {
                    "code": 400,
                    "message": "Unable to submit request because maxOutputTokens is invalid.",
                    "status": "INVALID_ARGUMENT",
                }
            }
        ],
        request=request,
    )
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    error = adapter._http_error(exc)

    assert str(error) == (
        "Vertex AI HTTP 400: Unable to submit request because maxOutputTokens is invalid."
    )
