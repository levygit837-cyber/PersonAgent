"""Unit tests for Google Vertex AI models and configurations."""

from dataclasses import is_dataclass

import pytest

from personagent.infrastructure.llm.vertex_ai.models import (
    DEFAULT_OUTPUT_TOKENS,
    DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STREAM_POOL_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    GOOGLE_CLOUD_SCOPE,
    SKIP_THOUGHT_SIGNATURE_VALIDATOR,
    VERTEX_MODELS,
    VERTEX_MODELS_BY_ID,
    VertexModelSpec,
)


def test_vertex_model_spec_is_dataclass():
    """Verify that VertexModelSpec is a frozen dataclass with expected attributes."""
    assert is_dataclass(VertexModelSpec)

    spec = VertexModelSpec(
        id="test-model",
        label="Test Model",
        input_tokens=1000,
        output_tokens=500,
    )

    assert spec.id == "test-model"
    assert spec.label == "Test Model"
    assert spec.input_tokens == 1000
    assert spec.output_tokens == 500

    # Verify that it is frozen
    with pytest.raises(AttributeError):
        spec.id = "new-id"  # type: ignore


def test_vertex_model_spec_defaults():
    """Verify default values for VertexModelSpec optional fields."""
    spec = VertexModelSpec(
        id="test-model",
        label="Test Model",
        input_tokens=100,
        output_tokens=50,
    )

    assert spec.image_output is False
    assert spec.supports_thinking is True
    assert spec.thinking_control == "level"
    assert spec.thinking_budget_min is None
    assert spec.thinking_budget_max is None
    assert spec.supports_tools is True
    assert spec.supports_code_execution is True
    assert spec.supports_context_cache is True
    assert spec.launch_stage == "public_preview"


def test_vertex_models_registry_completeness():
    """Verify that the model list is populated with correct VertexModelSpec elements."""
    assert len(VERTEX_MODELS) > 0
    for model in VERTEX_MODELS:
        assert isinstance(model, VertexModelSpec)
        assert model.id
        assert model.label
        assert model.input_tokens > 0
        assert model.output_tokens > 0


def test_vertex_models_by_id_mapping():
    """Verify VERTEX_MODELS_BY_ID correctly indexes all models."""
    assert len(VERTEX_MODELS_BY_ID) == len(VERTEX_MODELS)
    for model in VERTEX_MODELS:
        assert VERTEX_MODELS_BY_ID[model.id] is model


def test_vertex_models_constants_values():
    """Verify that all extracted config constants are present and match their spec values."""
    assert DEFAULT_TIMEOUT_SECONDS == 240.0
    assert DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS == 30.0
    assert DEFAULT_STREAM_POOL_TIMEOUT_SECONDS == 30.0
    assert DEFAULT_OUTPUT_TOKENS == 65536
    assert GOOGLE_CLOUD_SCOPE == "https://www.googleapis.com/auth/cloud-platform"
    assert SKIP_THOUGHT_SIGNATURE_VALIDATOR == "skip_thought_signature_validator"


def test_vertex_models_specific_attributes():
    """Verify specific traits on selected models in the registry."""
    # Gemini 2.5 Flash Lite
    lite_spec = VERTEX_MODELS_BY_ID["gemini-2.5-flash-lite"]
    assert lite_spec.thinking_control == "budget"
    assert lite_spec.thinking_budget_min == 512
    assert lite_spec.thinking_budget_max == 24576
    assert lite_spec.launch_stage == "ga"

    # Gemini 3.1 Flash Image
    image_spec = VERTEX_MODELS_BY_ID["gemini-3.1-flash-image-preview"]
    assert image_spec.image_output is True
    assert image_spec.supports_tools is False
    assert image_spec.supports_code_execution is False
    assert image_spec.supports_context_cache is False
