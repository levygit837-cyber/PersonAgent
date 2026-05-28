"""Pipeline benchmarks for tool orchestrator end-to-end execution.

Tests the full path: ToolOrchestrator.execute() → partition → parallel/serial → results.
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
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, measure


@pytest.mark.stress
class TestToolLoopPipeline:
    """Test the tool execution loop under various iteration/tool patterns."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> ToolUseContext:
        return ToolUseContext(
            conversation_id="pipeline-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )

    async def test_single_tool_execution_baseline(self, tmp_path, context):
        """1 tool call → baseline execution latency."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=1))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("single_tool")
        for _ in range(100):
            calls = [make_tool_call("read_file")]
            async with measure("exec", dist):
                results = await orchestrator.execute_collect(calls, context)
            assert len(results) == 1

        assert dist.p95 < 50  # should be well under 50ms

    async def test_10_parallel_safe_tools(self, tmp_path, context):
        """10 parallel-safe tools → measure batch execution throughput."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=10)
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("10_parallel_tools")
        for _ in range(50):
            calls = [make_tool_call("read_file", call_id=f"call_{i}") for i in range(10)]
            async with measure("exec", dist):
                results = await orchestrator.execute_collect(calls, context)
            assert len(results) == 10

        # 10 parallel 5ms tools should complete in ~10-20ms (not 50ms)
        assert dist.p95 < 100

    async def test_10_serial_tools(self, tmp_path, context):
        """10 serial tools → measure sequential baseline."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("10_serial_tools")
        for _ in range(50):
            calls = [make_tool_call("shell", call_id=f"call_{i}") for i in range(10)]
            async with measure("exec", dist):
                results = await orchestrator.execute_collect(calls, context)
            assert len(results) == 10

        # 10 serial 2ms tools → ~20-40ms
        assert dist.p95 < 100

    async def test_mixed_safety_5_iterations(self, tmp_path, context):
        """5 iterations of mixed safe/unsafe tools → realistic agent turn."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        registry.register(make_mock_tool("glob", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("5_iterations_mixed")
        for _ in range(20):
            # Simulate 5 iterations of tool calls
            for iteration in range(5):
                calls = [
                    make_tool_call("read_file", call_id=f"r_{iteration}"),
                    make_tool_call("glob", call_id=f"g_{iteration}"),
                    make_tool_call("shell", call_id=f"s_{iteration}"),
                ]
                async with measure("iteration", dist):
                    results = await orchestrator.execute_collect(calls, context)
                assert len(results) == 3

    async def test_concurrent_orchestrator_runs(self, tmp_path, context):
        """5 concurrent orchestrator batches → measure contention."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=4)

        async def run_batch():
            orch = ToolOrchestrator(registry, config)
            calls = [make_tool_call("read_file", call_id=f"batch_{id(orch)}_{i}") for i in range(6)]
            return await orch.execute_collect(calls, context)

        result = await run_concurrent(5, run_batch, semaphore=5)
        assert result.successful == 5
        assert result.p95 < 500


@pytest.mark.stress
class TestToolResultOrdering:
    """Verify that results maintain original call order even with parallel execution."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> ToolUseContext:
        return ToolUseContext(
            conversation_id="order-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )

    async def test_order_preserved_10_parallel(self, tmp_path, context):
        """10 parallel tools → results match original call order."""
        def make_ordered_tool(name: str):
            async def handler(args, ctx, call):
                # Variable latency to test ordering
                delay = int(call.id.split("_")[-1]) % 5
                await asyncio.sleep(delay * 0.001)
                return make_tool_result(call.id, call.name)
            from personagent.domain.tools import ToolResult, ToolExecutionStatus, ToolDefinition, build_tool
            return build_tool(
                definition=ToolDefinition(
                    name=name, description=name,
                    input_schema={"type": "object", "properties": {}},
                    is_concurrency_safe=True,
                ),
                handler=handler,
                is_concurrency_safe=lambda args: True,
            )

        def make_tool_result(call_id, tool_name):
            from personagent.domain.tools import ToolResult, ToolExecutionStatus
            return ToolResult(
                tool_call_id=call_id, tool_name=tool_name,
                content=call_id, status=ToolExecutionStatus.COMPLETED,
            )

        registry = ToolRegistry()
        registry.register(make_ordered_tool("read_file"))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=10)
        orchestrator = ToolOrchestrator(registry, config)

        calls = [make_tool_call("read_file", call_id=f"call_{i}") for i in range(10)]
        results = await orchestrator.execute_collect(calls, context)

        assert len(results) == 10
        for i, result in enumerate(results):
            assert result.tool_call_id == f"call_{i}"
