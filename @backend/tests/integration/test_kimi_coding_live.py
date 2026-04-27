import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from personagent.infrastructure.llm.kimi_coding_adapter import KimiCodingAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

pytestmark = pytest.mark.kimi_live


def _live_enabled() -> bool:
    return os.getenv("KIMI_LIVE_TESTS") == "1" and bool(os.getenv("KIMI_API_KEY"))


@pytest.mark.skipif(not _live_enabled(), reason="Set KIMI_LIVE_TESTS=1 and KIMI_API_KEY")
@pytest.mark.asyncio
async def test_kimi_coding_stream_reports_reasoning_and_final_answer():
    adapter = KimiCodingAdapter(
        api_key=os.environ["KIMI_API_KEY"],
        base_url=os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"),
        default_model=os.getenv("KIMI_DEFAULT_MODEL", "kimi-for-coding"),
        default_max_tokens=4096,
        timeout=float(os.getenv("KIMI_LIVE_TIMEOUT_SECONDS", os.getenv("KIMI_TIMEOUT_SECONDS", "240"))),
    )
    content = ""
    reasoning = ""
    signatures: list[str] = []

    try:
        async for chunk in adapter.chat_completion_stream(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Use thinking interno para calcular 17 + 25. "
                        "Depois responda em portugues com apenas: OK 42"
                    ),
                }
            ],
            max_tokens=4096,
            model="kimi-for-coding",
            reasoning_budget_tokens=2048,
        ):
            content += chunk.content
            reasoning += chunk.reasoning_content
            signatures.extend(chunk.metadata.get("kimi_thinking_signatures") or [])

        print(
            "kimi_coding_reasoning_shape="
            f"reasoning_chars={len(reasoning)},"
            f"content_chars={len(content)},"
            f"signatures={len(signatures)}"
        )
        assert content.strip()
        assert reasoning.strip()
    finally:
        await adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set KIMI_LIVE_TESTS=1 and KIMI_API_KEY")
@pytest.mark.asyncio
async def test_kimi_coding_non_stream_short_probe_returns_ok():
    adapter = KimiCodingAdapter(
        api_key=os.environ["KIMI_API_KEY"],
        base_url=os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"),
        default_model=os.getenv("KIMI_DEFAULT_MODEL", "kimi-for-coding"),
        default_max_tokens=32,
        timeout=float(os.getenv("KIMI_LIVE_TIMEOUT_SECONDS", os.getenv("KIMI_TIMEOUT_SECONDS", "240"))),
    )

    try:
        result = await adapter.chat_completion(
            messages=[{"role": "user", "content": "Hello, respond with just OK"}],
            max_tokens=32,
            model="kimi-for-coding",
            reasoning_budget_tokens=0,
        )

        assert "OK" in result.content.upper()
        assert result.metadata["provider"] == "kimi"
    finally:
        await adapter.close()


@pytest.mark.skipif(not _live_enabled(), reason="Set KIMI_LIVE_TESTS=1 and KIMI_API_KEY")
@pytest.mark.asyncio
async def test_kimi_coding_multi_tool_loop_preserves_signed_thinking_history():
    adapter = KimiCodingAdapter(
        api_key=os.environ["KIMI_API_KEY"],
        base_url=os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"),
        default_model=os.getenv("KIMI_DEFAULT_MODEL", "kimi-for-coding"),
        default_max_tokens=4096,
        timeout=float(os.getenv("KIMI_LIVE_TIMEOUT_SECONDS", os.getenv("KIMI_TIMEOUT_SECONDS", "240"))),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "TodoWrite",
                "description": "Update todos for a long running work session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                    },
                                },
                                "required": ["content", "status"],
                            },
                        }
                    },
                    "required": ["todos"],
                },
            },
        }
    ]
    messages = [
        {
            "role": "user",
            "content": (
                "Validation task: perform a 3-step work session. Step 1 call TodoWrite "
                "with three todos and first in_progress. After each tool result, call "
                "TodoWrite again to update the next step. After exactly 3 TodoWrite calls, "
                "answer FINAL DONE in Portuguese. Do not call tools after the third result."
            ),
        }
    ]
    action_count = 0
    total_reasoning_chars = 0
    final_content = ""

    try:
        for _turn in range(5):
            content = ""
            reasoning = ""
            tool_calls = None
            async for chunk in adapter.chat_completion_stream(
                messages=messages,
                tools=tools,
                tool_choice="auto",
                model="kimi-for-coding",
                max_tokens=4096,
                reasoning_budget_tokens=2048,
            ):
                content += chunk.content
                reasoning += chunk.reasoning_content
                if chunk.tool_calls:
                    tool_calls = chunk.tool_calls

            total_reasoning_chars += len(reasoning)
            if tool_calls:
                action_count += len(tool_calls)
                messages.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": f"Updated todos for action {action_count}.",
                        }
                    )
                continue

            final_content = content
            break

        print(
            "kimi_coding_multi_tool_loop="
            f"actions={action_count},"
            f"reasoning_chars={total_reasoning_chars},"
            f"final_chars={len(final_content)}"
        )
        assert action_count >= 3
        assert total_reasoning_chars > 0
        assert final_content.strip()
    finally:
        await adapter.close()
