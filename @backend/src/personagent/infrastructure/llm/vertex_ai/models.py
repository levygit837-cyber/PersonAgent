"""Google Vertex AI models and configurations."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS = 30.0
DEFAULT_STREAM_POOL_TIMEOUT_SECONDS = 30.0
DEFAULT_OUTPUT_TOKENS = 65536
GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
SKIP_THOUGHT_SIGNATURE_VALIDATOR = "skip_thought_signature_validator"


@dataclass(frozen=True, slots=True)
class VertexModelSpec:
    id: str
    label: str
    input_tokens: int
    output_tokens: int
    image_output: bool = False
    supports_thinking: bool = True
    thinking_control: str = "level"
    thinking_budget_min: int | None = None
    thinking_budget_max: int | None = None
    supports_tools: bool = True
    supports_code_execution: bool = True
    supports_context_cache: bool = True
    launch_stage: str = "public_preview"


VERTEX_MODELS: tuple[VertexModelSpec, ...] = (
    VertexModelSpec(
        id="gemini-2.5-flash-lite",
        label="Gemini 2.5 Flash-Lite",
        input_tokens=1_048_576,
        output_tokens=65_535,
        thinking_control="budget",
        thinking_budget_min=512,
        thinking_budget_max=24_576,
        launch_stage="ga",
    ),
    VertexModelSpec(
        id="gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        input_tokens=1_048_576,
        output_tokens=65_535,
        thinking_control="budget",
        thinking_budget_min=1,
        thinking_budget_max=24_576,
        launch_stage="ga",
    ),
    VertexModelSpec(
        id="gemini-3.1-pro-preview",
        label="Gemini 3.1 Pro",
        input_tokens=1_048_576,
        output_tokens=65_536,
    ),
    VertexModelSpec(
        id="gemini-3.1-pro-preview-customtools",
        label="Gemini 3.1 Pro Custom Tools",
        input_tokens=1_048_576,
        output_tokens=65_536,
    ),
    VertexModelSpec(
        id="gemini-3.1-flash-lite-preview",
        label="Gemini 3.1 Flash-Lite",
        input_tokens=1_048_576,
        output_tokens=65_535,
    ),
    VertexModelSpec(
        id="gemini-3.1-flash-image-preview",
        label="Gemini 3.1 Flash Image",
        input_tokens=131_072,
        output_tokens=32_768,
        image_output=True,
        supports_tools=False,
        supports_code_execution=False,
        supports_context_cache=False,
    ),
    VertexModelSpec(
        id="gemini-3-flash-preview",
        label="Gemini 3 Flash",
        input_tokens=1_048_576,
        output_tokens=65_536,
    ),
    VertexModelSpec(
        id="gemini-3-pro-image-preview",
        label="Gemini 3 Pro Image",
        input_tokens=65_536,
        output_tokens=32_768,
        image_output=True,
        supports_thinking=False,
        supports_tools=False,
        supports_code_execution=False,
        supports_context_cache=False,
    ),
)

VERTEX_MODELS_BY_ID = {model.id: model for model in VERTEX_MODELS}
