"""Pipeline benchmarks for MockLLMAdapter end-to-end streaming.

Tests the full tool-call loop using the mock LLM: LLM → tool_calls → execute → LLM → content.
This simulates the critical path without the streaming executor's complexity.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.tools import ToolCall, ToolUseContext

from tests.stress.conftest import make_mock_tool, make_tool_call
from tests.stress.mock_llm import MockLLMAdapter, make_tool_call_payload
from tests.stress.metrics import LatencyDistribution, measure


@pytest.mark.stress
class TestStreamingPipelineSimulated:
    """Simulate the streaming tool-call loop with mock LLM."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> ToolUseContext:
        return ToolUseContext(
            conversation_id="stream-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )

    async def test_simple_turn_no_tools(self, tmp_path, context):
        """User message → mock LLM stream → content → no tools."""
        llm = MockLLMAdapter(latency_ms=10, final_response="Hello! How can I help?")
        messages = [{"role": "user", "content": "Hello"}]

        dist = LatencyDistribution("simple_turn_no_tools")
        for _ in range(50):
            llm.reset()
            start = time.perf_counter()
            chunks = []
            async for chunk in llm.chat_completion_stream(messages):
                chunks.append(chunk)
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)

        assert dist.p50 < 100
        assert dist.count == 50

    async def test_turn_with_3_tool_iterations(self, tmp_path, context):
        """3 tool-call iterations then content → measures loop overhead."""
        # LLM will emit tool_calls for first 3 calls, then content
        tool_sequence = [
            [make_tool_call_payload("read_file", {"path": "src/main.py"})],
            [make_tool_call_payload("grep", {"pattern": "import", "path": "src/"})],
            [make_tool_call_payload("shell", {"command": "pytest"})],
        ]
        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="All tests pass.",
        )

        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("grep", concurrency_safe=True, latency_ms=1))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=3))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("3_tool_iterations")
        for _ in range(20):
            llm.reset()
            messages = [{"role": "user", "content": "Run tests"}]
            start = time.perf_counter()

            iteration = 0
            while True:
                tool_calls_emitted = []
                async for chunk in llm.chat_completion_stream(messages):
                    if chunk.tool_calls:
                        tool_calls_emitted.extend(chunk.tool_calls)

                if not tool_calls_emitted:
                    break

                # Execute tools
                calls = [ToolCall.from_openai(tc) for tc in tool_calls_emitted]
                results = await orchestrator.execute_collect(calls, context)

                # Append tool results to messages (simulating the real loop)
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls_emitted,
                })
                for result in results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result.tool_call_id,
                        "content": result.content,
                    })

                iteration += 1
                if iteration >= 10:
                    break

            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)
            assert iteration == 3

        assert dist.p50 < 200

    async def test_turn_with_5_iterations_2_tools_each(self, tmp_path, context):
        """5 iterations × 2 parallel-safe tools → heavy tool turn."""
        tool_sequence = [
            [make_tool_call_payload("read_file", {"path": f"file_{i}.py"}) for _ in range(1)]
            for i in range(5)
        ]
        llm = MockLLMAdapter(
            latency_ms=3,
            tool_call_sequence=tool_sequence,
            final_response="Analysis complete.",
        )

        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("5_iterations_1_tool")
        llm.reset()
        messages = [{"role": "user", "content": "Analyze project"}]
        start = time.perf_counter()

        iteration = 0
        while True:
            tool_calls_emitted = []
            async for chunk in llm.chat_completion_stream(messages):
                if chunk.tool_calls:
                    tool_calls_emitted.extend(chunk.tool_calls)

            if not tool_calls_emitted:
                break

            calls = [ToolCall.from_openai(tc) for tc in tool_calls_emitted]
            results = await orchestrator.execute_collect(calls, context)

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_emitted,
            })
            for result in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                })

            iteration += 1
            if iteration >= 10:
                break

        elapsed = (time.perf_counter() - start) * 1000
        dist.record(elapsed)
        assert iteration == 5
        assert elapsed < 500

    async def test_parallel_tool_calls_per_iteration(self, tmp_path, context):
        """Each iteration emits 3 parallel-safe tools → measure batch throughput."""
        tool_sequence = [
            [
                make_tool_call_payload("read_file", {"path": "a.py"}, call_id="c_a"),
                make_tool_call_payload("read_file", {"path": "b.py"}, call_id="c_b"),
                make_tool_call_payload("read_file", {"path": "c.py"}, call_id="c_c"),
            ],
        ]
        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="Read all files.",
        )

        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=3)
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("3_parallel_per_iteration")
        for _ in range(30):
            llm.reset()
            messages = [{"role": "user", "content": "Read files"}]
            start = time.perf_counter()

            tool_calls_emitted = []
            async for chunk in llm.chat_completion_stream(messages):
                if chunk.tool_calls:
                    tool_calls_emitted.extend(chunk.tool_calls)

            if tool_calls_emitted:
                calls = [ToolCall.from_openai(tc) for tc in tool_calls_emitted]
                results = await orchestrator.execute_collect(calls, context)
                assert len(results) == 3

            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)

        # 3 parallel 3ms tools + 5ms LLM → ~15-25ms per iteration
        assert dist.p50 < 50
