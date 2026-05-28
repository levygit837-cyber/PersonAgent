"""Concurrency tests for parallel streaming requests.

Tests how the system handles multiple simultaneous LLM + tool execution streams.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolUseContext

from tests.stress.conftest import make_mock_tool, make_tool_call
from tests.stress.mock_llm import MockLLMAdapter, make_tool_call_payload
from tests.stress.concurrent_runner import run_concurrent, ConcurrentResult
from tests.stress.metrics import LatencyDistribution, StressReport, measure


@pytest.mark.stress
class TestParallelRequests:
    """Test concurrent streaming turn simulations."""

    @pytest.fixture
    def setup(self, tmp_path: Path):
        """Common setup for parallel request tests."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        context = ToolUseContext(
            conversation_id="parallel-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
        return registry, config, context

    async def test_10_concurrent_simple_completions(self, setup):
        """10 concurrent simple completions (no tools) → measure throughput."""
        async def run_one():
            llm = MockLLMAdapter(latency_ms=10, final_response="Response.")
            messages = [{"role": "user", "content": "Hello"}]
            chunks = []
            async for chunk in llm.chat_completion_stream(messages):
                chunks.append(chunk)
            return len(chunks)

        result = await run_concurrent(10, run_one)
        assert result.successful == 10
        assert result.p95 < 200  # 10ms LLM + overhead

    async def test_10_concurrent_streaming_with_tools(self, setup):
        """10 concurrent turns with tool calls → measure contention."""
        registry, config, context = setup

        async def run_one():
            llm = MockLLMAdapter(
                latency_ms=5,
                tool_call_sequence=[
                    [make_tool_call_payload("read_file", {"path": "src/main.py"})],
                ],
                final_response="Done.",
            )
            orchestrator = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Read file"}]

            iteration = 0
            while True:
                tool_calls = []
                async for chunk in llm.chat_completion_stream(messages):
                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
                if not tool_calls:
                    break
                calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                await orchestrator.execute_collect(calls, context)
                iteration += 1
                if iteration >= 5:
                    break

        result = await run_concurrent(10, run_one)
        assert result.successful == 10
        assert result.p95 < 500

    async def test_50_concurrent_simple_completions(self, setup):
        """50 concurrent completions → stress test."""
        async def run_one():
            llm = MockLLMAdapter(latency_ms=5, final_response="OK.")
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in llm.chat_completion_stream(messages):
                pass

        result = await run_concurrent(50, run_one)
        assert result.successful == 50
        assert result.throughput_rps > 50  # should handle 50+ req/s with mock

    async def test_100_concurrent_simple_completions(self, setup):
        """100 concurrent completions → high stress."""
        async def run_one():
            llm = MockLLMAdapter(latency_ms=3, final_response="OK.")
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in llm.chat_completion_stream(messages):
                pass

        result = await run_concurrent(100, run_one)
        assert result.successful == 100
        assert result.throughput_rps > 100  # should handle 100+ req/s with mock


@pytest.mark.stress
class TestParallelWithSemaphore:
    """Test parallel execution with different concurrency limits."""

    async def test_10_requests_semaphore_5(self):
        """10 requests with semaphore=5 → measures queuing overhead."""
        async def run_one():
            await asyncio.sleep(0.01)  # 10ms simulated work

        result = await run_concurrent(10, run_one, semaphore=5)
        assert result.successful == 10
        # With semaphore=5, should take ~2 batches × 10ms = ~20-30ms
        assert result.wall_time_ms < 100

    async def test_20_requests_semaphore_4(self):
        """20 requests with semaphore=4 → 5 batches."""
        async def run_one():
            await asyncio.sleep(0.005)  # 5ms simulated work

        result = await run_concurrent(20, run_one, semaphore=4)
        assert result.successful == 20
        # 5 batches × 5ms = ~25-35ms
        assert result.wall_time_ms < 100

    async def test_parallelism_efficiency_ratio(self):
        """Measure parallelism efficiency: sum(individual) / wall_time."""
        async def run_one():
            await asyncio.sleep(0.01)  # 10ms

        # Sequential baseline
        sequential_start = time.perf_counter()
        for _ in range(10):
            await run_one()
        sequential_ms = (time.perf_counter() - sequential_start) * 1000

        # Parallel run
        result = await run_concurrent(10, run_one)
        efficiency = sequential_ms / result.wall_time_ms if result.wall_time_ms > 0 else 0

        # Should be close to 10x speedup with 10 parallel tasks
        assert efficiency > 5  # at least 5x speedup
