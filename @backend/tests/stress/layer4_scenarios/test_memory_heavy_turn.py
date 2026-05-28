"""Full agent scenario: memory-heavy turn with capture and recall.

Simulates a turn where operational memory capture and recall are active,
testing the full memory pipeline impact on agent performance.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.services.operational_memory.capture import OperationalMemoryCapture
from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
)
from personagent.domain.tools import ToolCall, ToolUseContext

from tests.stress.conftest import make_mock_tool
from tests.stress.mock_embedding import MockEmbeddingAdapter
from tests.stress.mock_llm import MockLLMAdapter, make_tool_call_payload
from tests.stress.metrics import LatencyDistribution, StressReport, measure


def _make_memory_service(embedding_adapter):
    repository = MagicMock()
    repository.record_event = AsyncMock()
    repository.record_chunks = AsyncMock(side_effect=lambda chunks: chunks)
    repository.record_structured_items = AsyncMock()
    repository.record_embeddings = AsyncMock()
    repository.mark_chunks_failed = AsyncMock()
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(deque)

    return OperationalMemoryCapture(
        repository=repository,
        redactor=OperationalMemoryRedactor(),
        chunker=OperationalMemoryChunker(),
        extractor=MagicMock(structured_items_from_event=MagicMock(return_value=[])),
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embedding_adapter is not None,
        embedding_model="mock-embed",
        capture_tools_enabled=True,
        max_capture_chars=24_000,
        queue=None,
        queue_enabled=False,
        queue_fallback_sync=True,
        hot_cache=hot_cache,
    )


@pytest.mark.stress
class TestMemoryHeavyTurn:
    """Simulate a memory-heavy agent turn end-to-end."""

    @pytest.fixture
    def setup(self, tmp_path: Path):
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=4)
        context = ToolUseContext(
            conversation_id="memory-heavy-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
        return registry, config, context

    async def test_turn_with_memory_capture_per_tool(self, setup):
        """Each tool result triggers memory capture → measure cumulative overhead."""
        registry, config, context = setup
        mock_embed = MockEmbeddingAdapter(latency_ms=10, dimensions=1024)
        memory_service = _make_memory_service(mock_embed)

        tool_sequence = [
            [
                make_tool_call_payload("read_file", {"path": "src/main.py"}),
                make_tool_call_payload("read_file", {"path": "src/utils.py"}),
            ],
            [
                make_tool_call_payload("shell", {"command": "pytest"}),
            ],
        ]

        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="Analysis complete.",
        )

        dist = LatencyDistribution("memory_capture_per_tool")
        report = StressReport("Memory-Heavy Turn")

        for _ in range(10):
            llm.reset()
            orch = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Analyze the codebase"}]
            start = time.perf_counter()

            iteration = 0
            while True:
                tool_calls = []
                async for chunk in llm.chat_completion_stream(messages):
                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
                if not tool_calls:
                    break

                calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                results = await orch.execute_collect(calls, context)

                # Capture each tool result to memory
                for call, result in zip(calls, results):
                    await memory_service.capture_tool_result(
                        project_slug="test-project",
                        workspace_root=str(context.workspace_root),
                        conversation_id=context.conversation_id,
                        call=call,
                        result=result,
                        context=context,
                    )

                messages.append({
                    "role": "assistant", "content": None, "tool_calls": tool_calls,
                })
                for result in results:
                    messages.append({
                        "role": "tool", "tool_call_id": result.tool_call_id, "content": result.content,
                    })
                iteration += 1
                if iteration >= 10:
                    break

            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)

        report.add_distribution(dist)
        report.custom_metrics = {
            "embedding_calls": mock_embed.call_count,
            "texts_embedded": mock_embed.total_texts_embedded,
        }

        assert dist.p95 < 1000  # should be under 1s with mock embedding

    async def test_turn_with_user_message_capture(self, setup):
        """Capture user message + assistant response → measure overhead."""
        registry, config, context = setup
        mock_embed = MockEmbeddingAdapter(latency_ms=10, dimensions=1024)
        memory_service = _make_memory_service(mock_embed)

        llm = MockLLMAdapter(latency_ms=5, final_response="Detailed analysis of the codebase architecture.")

        dist = LatencyDistribution("user_assistant_capture")
        for _ in range(20):
            llm.reset()
            messages = [{"role": "user", "content": "Explain the architecture"}]

            async with measure("turn", dist):
                # Capture user message
                await memory_service.capture_user_message(
                    project_slug="test-project",
                    workspace_root=str(context.workspace_root),
                    conversation_id=context.conversation_id,
                    message="Explain the architecture",
                )

                # Get LLM response
                response_content = ""
                async for chunk in llm.chat_completion_stream(messages):
                    if chunk.content:
                        response_content += chunk.content

                # Capture assistant response
                await memory_service.capture_assistant_message(
                    project_slug="test-project",
                    workspace_root=str(context.workspace_root),
                    conversation_id=context.conversation_id,
                    content=response_content,
                )

        assert dist.p50 < 200

    async def test_concurrent_turns_with_memory(self, setup):
        """3 concurrent turns, each with memory capture → measure contention."""
        registry, config, context = setup
        mock_embed = MockEmbeddingAdapter(latency_ms=15, dimensions=1024)

        async def run_turn(i: int):
            memory_service = _make_memory_service(mock_embed)
            llm = MockLLMAdapter(latency_ms=5, final_response=f"Response {i}")
            messages = [{"role": "user", "content": f"Task {i}"}]

            await memory_service.capture_user_message(
                project_slug="test-project",
                workspace_root=str(context.workspace_root),
                conversation_id=f"conv-{i}",
                message=f"Task {i}",
            )

            content = ""
            async for chunk in llm.chat_completion_stream(messages):
                if chunk.content:
                    content += chunk.content

            await memory_service.capture_assistant_message(
                project_slug="test-project",
                workspace_root=str(context.workspace_root),
                conversation_id=f"conv-{i}",
                content=content,
            )

        dist = LatencyDistribution("3_concurrent_memory_turns")
        for _ in range(10):
            start = time.perf_counter()
            await asyncio.gather(*[run_turn(i) for i in range(3)])
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)

        assert dist.p95 < 1000
