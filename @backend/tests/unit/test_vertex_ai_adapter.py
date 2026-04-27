import pytest

from personagent.domain.exceptions import LLMBackendConnectionError
from personagent.infrastructure.llm.vertex_ai_adapter import VERTEX_MODELS, VertexAiAdapter


def test_vertex_catalog_contains_curated_gemini_3_models_without_deprecated_pro():
    adapter = VertexAiAdapter(api_key="google-test-key")

    catalog_items = [adapter._model_to_catalog_item(model) for model in VERTEX_MODELS]
    ids = {item["id"] for item in catalog_items}

    assert ids == {
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
