"""Pipeline benchmarks for tool execution with increasing complexity."""

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
from tests.stress.metrics import LatencyDistribution, measure


@pytest.mark.stress
class TestToolComplexityScaling:
    """Measure how tool execution scales with increasing complexity."""

    @pytest.fixture
    def context(self, tmp_path: Path) -> ToolUseContext:
        return ToolUseContext(
            conversation_id="scale-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )

    async def test_1_tool(self, tmp_path, context):
        """Baseline: 1 tool."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
        orch = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("1_tool")
        for _ in range(100):
            async with measure("exec", dist):
                await orch.execute_collect([make_tool_call("read_file")], context)
        assert dist.p95 < 20

    async def test_5_tools(self, tmp_path, context):
        """5 parallel-safe tools."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=5)
        orch = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("5_tools")
        for _ in range(100):
            calls = [make_tool_call("read_file", call_id=f"c_{i}") for i in range(5)]
            async with measure("exec", dist):
                await orch.execute_collect(calls, context)
        assert dist.p95 < 30

    async def test_10_tools(self, tmp_path, context):
        """10 parallel-safe tools."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=10)
        orch = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("10_tools")
        for _ in range(100):
            calls = [make_tool_call("read_file", call_id=f"c_{i}") for i in range(10)]
            async with measure("exec", dist):
                await orch.execute_collect(calls, context)
        assert dist.p95 < 40

    async def test_20_tools(self, tmp_path, context):
        """20 parallel-safe tools → measure scaling."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=20)
        orch = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("20_tools")
        for _ in range(50):
            calls = [make_tool_call("read_file", call_id=f"c_{i}") for i in range(20)]
            async with measure("exec", dist):
                await orch.execute_collect(calls, context)
        assert dist.p95 < 80

    async def test_serial_barrier_impact(self, tmp_path, context):
        """[safe×3, unsafe×1, safe×3] → serial barrier delays last 3 tools."""
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=4)
        orch = ToolOrchestrator(registry, config)

        dist = LatencyDistribution("serial_barrier")
        for _ in range(50):
            calls = [
                make_tool_call("read_file", call_id="r0"),
                make_tool_call("read_file", call_id="r1"),
                make_tool_call("read_file", call_id="r2"),
                make_tool_call("shell", call_id="s0"),      # serial barrier
                make_tool_call("read_file", call_id="r3"),
                make_tool_call("read_file", call_id="r4"),
                make_tool_call("read_file", call_id="r5"),
            ]
            async with measure("exec", dist):
                results = await orch.execute_collect(calls, context)
            assert len(results) == 7

        # Should be slower than pure parallel due to serial barrier
        assert dist.p95 < 100
