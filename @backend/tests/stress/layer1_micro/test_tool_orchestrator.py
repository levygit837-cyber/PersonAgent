"""Micro-benchmarks for ToolOrchestrator partitioning and execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolUseContext

from tests.stress.conftest import make_mock_tool, make_tool_call
from tests.stress.concurrent_runner import run_concurrent


@pytest.mark.stress
class TestPartitionBenchmarks:
    """Benchmark the _partition method under various call patterns."""

    def _make_orchestrator(
        self,
        tmp_path: Path,
        tools: list | None = None,
        max_concurrency: int = 4,
    ) -> ToolOrchestrator:
        registry = ToolRegistry()
        for tool in (tools or []):
            registry.register(tool)
        config = ToolRuntimeConfig.from_values(
            workspace_root=str(tmp_path),
            max_concurrency=max_concurrency,
        )
        return ToolOrchestrator(registry, config)

    def test_partition_10_concurrent_safe(self, benchmark, tmp_path):
        """10 concurrency-safe calls with max_concurrency=10 → 1 batch."""
        safe_tool = make_mock_tool("read_file", concurrency_safe=True)
        orchestrator = self._make_orchestrator(tmp_path, [safe_tool], max_concurrency=10)
        calls = [make_tool_call("read_file", call_id=f"call_{i}") for i in range(10)]

        result = benchmark(lambda: orchestrator._partition(calls))
        assert len(result) == 1
        assert result[0].concurrency_safe is True
        assert len(result[0].calls) == 10

    def test_partition_10_serial(self, benchmark, tmp_path):
        """10 non-concurrent-safe calls → should form 10 individual batches."""
        serial_tool = make_mock_tool("shell", concurrency_safe=False)
        orchestrator = self._make_orchestrator(tmp_path, [serial_tool])
        calls = [make_tool_call("shell", call_id=f"call_{i}") for i in range(10)]

        result = benchmark(lambda: orchestrator._partition(calls))
        assert len(result) == 10
        assert all(not batch.concurrency_safe for batch in result)

    def test_partition_mixed_safety(self, benchmark, tmp_path):
        """[safe, safe, unsafe, safe, safe] → 3 batches."""
        safe = make_mock_tool("read_file", concurrency_safe=True)
        unsafe = make_mock_tool("shell", concurrency_safe=False)
        orchestrator = self._make_orchestrator(tmp_path, [safe, unsafe])

        calls = [
            make_tool_call("read_file", call_id="c0"),
            make_tool_call("read_file", call_id="c1"),
            make_tool_call("shell", call_id="c2"),
            make_tool_call("read_file", call_id="c3"),
            make_tool_call("read_file", call_id="c4"),
        ]

        result = benchmark(lambda: orchestrator._partition(calls))
        assert len(result) == 3
        assert result[0].concurrency_safe is True and len(result[0].calls) == 2
        assert result[1].concurrency_safe is False and len(result[1].calls) == 1
        assert result[2].concurrency_safe is True and len(result[2].calls) == 2

    def test_partition_50_calls_with_max_concurrency_4(self, benchmark, tmp_path):
        """50 safe calls with max_concurrency=4 → batches of max 4 each."""
        safe_tool = make_mock_tool("read_file", concurrency_safe=True)
        orchestrator = self._make_orchestrator(tmp_path, [safe_tool], max_concurrency=4)
        calls = [make_tool_call("read_file", call_id=f"call_{i}") for i in range(50)]

        result = benchmark(lambda: orchestrator._partition(calls))
        batch_sizes = [len(b.calls) for b in result]
        assert all(size <= 4 for size in batch_sizes)
        assert sum(batch_sizes) == 50
        assert len(result) == 13  # 12×4 + 1×2


@pytest.mark.stress
class TestExecuteBenchmarks:
    """Benchmark tool execution throughput."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> ToolUseContext:
        return ToolUseContext(
            conversation_id="bench-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )

    async def test_execute_10_parallel_safe_tools(self, tmp_path, context):
        """10 concurrency-safe tools → parallel execution."""
        safe_tool = make_mock_tool("read_file", concurrency_safe=True, latency_ms=5)
        registry = ToolRegistry()
        registry.register(safe_tool)
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        calls = [make_tool_call("read_file", call_id=f"call_{i}") for i in range(10)]
        results = await orchestrator.execute_collect(calls, context)
        assert len(results) == 10
        assert all(r.content == "ok" for r in results)

    async def test_execute_10_serial_tools(self, tmp_path, context):
        """10 non-concurrent tools → sequential execution."""
        serial_tool = make_mock_tool("shell", concurrency_safe=False, latency_ms=2)
        registry = ToolRegistry()
        registry.register(serial_tool)
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        calls = [make_tool_call("shell", call_id=f"call_{i}") for i in range(10)]
        results = await orchestrator.execute_collect(calls, context)
        assert len(results) == 10

    async def test_execute_mixed_parallelism(self, tmp_path, context):
        """Mixed safe/unsafe tools → correct batching and execution."""
        safe = make_mock_tool("read_file", concurrency_safe=True, latency_ms=2)
        unsafe = make_mock_tool("shell", concurrency_safe=False, latency_ms=2)
        registry = ToolRegistry()
        registry.register(safe)
        registry.register(unsafe)
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orchestrator = ToolOrchestrator(registry, config)

        calls = [
            make_tool_call("read_file", call_id="c0"),
            make_tool_call("read_file", call_id="c1"),
            make_tool_call("shell", call_id="c2"),
            make_tool_call("read_file", call_id="c3"),
        ]
        results = await orchestrator.execute_collect(calls, context)
        assert len(results) == 4
        assert results[0].tool_call_id == "c0"
        assert results[1].tool_call_id == "c1"
        assert results[2].tool_call_id == "c2"
        assert results[3].tool_call_id == "c3"

    async def test_concurrent_tool_orchestrator_throughput(self, tmp_path, context):
        """5 concurrent orchestrator runs, each with 6 tools."""
        safe = make_mock_tool("read_file", concurrency_safe=True, latency_ms=3)
        registry = ToolRegistry()
        registry.register(safe)
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))

        async def run_batch():
            orch = ToolOrchestrator(registry, config)
            calls = [make_tool_call("read_file", call_id=f"batch_{id(orch)}_{i}") for i in range(6)]
            return await orch.execute_collect(calls, context)

        result = await run_concurrent(5, run_batch, semaphore=5)
        assert result.successful == 5
        assert result.p95 < 500
