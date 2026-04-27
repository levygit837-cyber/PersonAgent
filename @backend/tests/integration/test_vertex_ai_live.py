import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from personagent.infrastructure.llm.vertex_ai_adapter import VertexAiAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

pytestmark = pytest.mark.vertex_live


def _live_enabled() -> bool:
    return os.getenv("VERTEX_LIVE_TESTS") == "1" and bool(os.getenv("GOOGLE_API_KEY"))


@pytest.fixture
def vertex_adapter() -> VertexAiAdapter:
    return VertexAiAdapter(
        api_key=os.environ["GOOGLE_API_KEY"],
        auth_mode=os.getenv("VERTEX_AUTH_MODE", "auto"),
        project_id=os.getenv("VERTEX_PROJECT_ID", ""),
        location=os.getenv("VERTEX_LOCATION", "global"),
        default_model=os.getenv("VERTEX_DEFAULT_MODEL", "gemini-3.1-flash-lite-preview"),
        default_max_tokens=512,
        timeout=float(os.getenv("VERTEX_LIVE_TIMEOUT_SECONDS", os.getenv("VERTEX_TIMEOUT_SECONDS", "240"))),
    )


@pytest.mark.skipif(not _live_enabled(), reason="Set VERTEX_LIVE_TESTS=1 and GOOGLE_API_KEY")
@pytest.mark.asyncio
async def test_vertex_flash_lite_non_stream_reports_available_content_or_thinking(
    vertex_adapter: VertexAiAdapter,
):
    try:
        result = await vertex_adapter.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": "Responda em portugues: quanto e 8 + 5? Seja breve.",
                }
            ],
            temperature=0.2,
            max_tokens=256,
            model="gemini-3.1-flash-lite-preview",
            reasoning_level="low",
        )

        assert result.model
        assert result.content.strip() or result.reasoning_content.strip()
        assert result.metadata["provider"] == "vertex"
    finally:
        await vertex_adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set VERTEX_LIVE_TESTS=1 and GOOGLE_API_KEY")
@pytest.mark.asyncio
async def test_vertex_flash_lite_stream_reports_thinking_shape_without_fabricating_reasoning(
    vertex_adapter: VertexAiAdapter,
):
    content = ""
    reasoning = ""
    saw_thought_signature = False

    try:
        async for chunk in vertex_adapter.chat_completion_stream(
            messages=[
                {
                    "role": "user",
                    "content": "Responda em portugues: escreva uma frase curta sobre testes.",
                }
            ],
            temperature=0.2,
            max_tokens=256,
            model="gemini-3.1-flash-lite-preview",
            reasoning_level="low",
        ):
            content += chunk.content
            reasoning += chunk.reasoning_content
            saw_thought_signature = saw_thought_signature or bool(
                chunk.metadata.get("vertex_thought_signatures")
            )

        thinking_shape = "part.thought" if reasoning.strip() else "thoughtSignature" if saw_thought_signature else "none"
        print(f"vertex_flash_lite_thinking_shape={thinking_shape}")
        assert content.strip() or reasoning.strip() or saw_thought_signature
    finally:
        await vertex_adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set VERTEX_LIVE_TESTS=1 and GOOGLE_API_KEY")
@pytest.mark.asyncio
async def test_vertex_flash_lite_stream_reports_tool_reasoning_shapes(
    vertex_adapter: VertexAiAdapter,
):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read a local workspace file by path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    reasoning = ""
    saw_tool_call = False
    saw_thought_signature = False
    saw_thoughts_token_count = False

    try:
        async for chunk in vertex_adapter.chat_completion_stream(
            messages=[
                {
                    "role": "user",
                    "content": "Use a ferramenta Read para ler README.md antes de responder. Depois diga apenas OK.",
                }
            ],
            temperature=0.2,
            max_tokens=512,
            tools=tools,
            tool_choice="auto",
            model="gemini-3.1-flash-lite-preview",
            reasoning_level="high",
        ):
            reasoning += chunk.reasoning_content
            saw_tool_call = saw_tool_call or bool(chunk.tool_calls)
            saw_thought_signature = saw_thought_signature or bool(
                chunk.metadata.get("vertex_thought_signatures")
            )
            saw_thoughts_token_count = saw_thoughts_token_count or bool(
                (chunk.usage or {}).get("thoughtsTokenCount")
            )

        print(
            "vertex_flash_lite_tool_thinking_shapes="
            f"thought_text={bool(reasoning.strip())},"
            f"thought_signature={saw_thought_signature},"
            f"thoughts_token_count={saw_thoughts_token_count}"
        )
        assert saw_tool_call
        assert reasoning.strip() or saw_thought_signature or saw_thoughts_token_count
    finally:
        await vertex_adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set VERTEX_LIVE_TESTS=1 and GOOGLE_API_KEY")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id",
    ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"],
)
async def test_vertex_low_cost_models_stream_visible_reasoning(
    vertex_adapter: VertexAiAdapter,
    model_id: str,
):
    content = ""
    reasoning = ""
    usage = None
    finish_reason = None

    try:
        async for chunk in vertex_adapter.chat_completion_stream(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Use reasoning interno para decidir uma estrategia de testes para uma "
                        "API FastAPI pequena. A resposta final deve ter uma frase curta."
                    ),
                }
            ],
            temperature=0.2,
            max_tokens=2048,
            model=model_id,
            reasoning_level="low",
            reasoning_budget_tokens=2048,
        ):
            content += chunk.content
            reasoning += chunk.reasoning_content
            usage = chunk.usage or usage
            finish_reason = chunk.finish_reason or finish_reason

        print(
            "vertex_low_cost_reasoning="
            f"model={model_id},"
            f"reasoning_chars={len(reasoning)},"
            f"content_chars={len(content)},"
            f"thoughts_tokens={(usage or {}).get('thoughtsTokenCount')},"
            f"finish={finish_reason}"
        )
        assert reasoning.strip()
        assert content.strip()
        assert (usage or {}).get("thoughtsTokenCount")
        assert finish_reason == "stop"
    finally:
        await vertex_adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set VERTEX_LIVE_TESTS=1 and GOOGLE_API_KEY")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id",
    ["gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"],
)
async def test_vertex_image_models_return_renderable_inline_data(
    vertex_adapter: VertexAiAdapter,
    model_id: str,
):
    try:
        result = await vertex_adapter.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": "Generate a simple 64x64 image of a solid blue square on a white background.",
                }
            ],
            temperature=0.4,
            max_tokens=256,
            model=model_id,
            reasoning_level="low",
        )

        assert result.images, f"{model_id} returned no inlineData image"
        print(f"vertex_image_model={model_id} mime_type={result.images[0].mime_type}")
        assert result.images[0].mime_type.startswith("image/")
        assert result.images[0].data
    finally:
        await vertex_adapter.close()
