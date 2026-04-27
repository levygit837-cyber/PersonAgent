import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

pytestmark = pytest.mark.nvidia_live


def _live_enabled() -> bool:
    return os.getenv("NVIDIA_LIVE_TESTS") == "1" and bool(os.getenv("NVIDIA_API_KEY"))


@pytest.mark.skipif(not _live_enabled(), reason="Set NVIDIA_LIVE_TESTS=1 and NVIDIA_API_KEY")
@pytest.mark.asyncio
async def test_nvidia_reasoning_chat_models_stream_thinking_and_final_answer():
    adapter = NvidiaNimAdapter(
        api_key=os.environ["NVIDIA_API_KEY"],
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        default_max_tokens=512,
    )
    failures: list[str] = []

    try:
        catalog = await adapter.list_models(capability="reasoning_chat", refresh=True)
        models = [model["id"] for model in catalog["data"]]
        selected_models = _select_live_models(models)

        assert selected_models, f"NVIDIA returned no reasoning chat models: {catalog}"

        for model_id in selected_models:
            content = ""
            reasoning = ""
            try:
                async for chunk in adapter.chat_completion_stream(
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "Responda em portugues. Calcule 12 + 7 com thinking "
                                "curto e depois resposta final."
                            ),
                        }
                    ],
                    max_tokens=512,
                    temperature=0.2,
                    model=model_id,
                    reasoning_budget_tokens=128,
                ):
                    content += chunk.content
                    reasoning += chunk.reasoning_content
            except Exception as exc:
                failures.append(f"{model_id}: request failed: {exc}")
                continue

            if not reasoning.strip():
                failures.append(f"{model_id}: no reasoning_content")
            if not content.strip():
                failures.append(f"{model_id}: no final content")

        assert not failures, "\n".join(failures)
    finally:
        await adapter.close()


def _select_live_models(models: list[str]) -> list[str]:
    explicit = os.getenv("NVIDIA_LIVE_MODEL_IDS")
    if explicit:
        requested = [item.strip() for item in explicit.split(",") if item.strip()]
        return [model for model in models if model in requested]

    limit = os.getenv("NVIDIA_LIVE_MODEL_LIMIT")
    if limit:
        return models[: int(limit)]
    return models
