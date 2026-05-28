"""Full agent scenario: tool-heavy turn with multiple iterations and mixed tool types.

Simulates a realistic agent turn where the LLM makes multiple tool-call iterations
with a mix of concurrency-safe and serial tools.
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

from tests.stress.conftest import make_mock_tool
from tests.stress.mock_llm import MockLLMAdapter, make_tool_call_payload
from tests.stress.metrics import LatencyDistribution, StressReport, measure


@pytest.mark.stress
class TestToolHeavyTurn:
    """Simulate a tool-heavy agent turn end-to-end."""

    @pytest.fixture
    def setup(self, tmp_path: Path):
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        registry.register(make_mock_tool("glob", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("grep", concurrency_safe=True, latency_ms=5))
        registry.register(make_mock_tool("write_file", concurrency_safe=False, latency_ms=4))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=8))
        registry.register(make_mock_tool("edit_file", concurrency_safe=False, latency_ms=3))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=4)
        context = ToolUseContext(
            conversation_id="heavy-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
        return registry, config, context

    async def test_5_iterations_3_tools_each(self, setup):
        """5 iterations × 3 tools (mixed safety) → 15 tool calls + 6 LLM calls."""
        registry, config, context = setup

        tool_sequence = [
            [
                make_tool_call_payload("read_file", {"path": "src/main.py"}, call_id="tc_0_0"),
                make_tool_call_payload("glob", {"pattern": "*.py"}, call_id="tc_0_1"),
                make_tool_call_payload("grep", {"pattern": "import"}, call_id="tc_0_2"),
            ],
            [
                make_tool_call_payload("read_file", {"path": "src/utils.py"}, call_id="tc_1_0"),
                make_tool_call_payload("read_file", {"path": "src/models.py"}, call_id="tc_1_1"),
                make_tool_call_payload("shell", {"command": "pytest tests/"}, call_id="tc_1_2"),
            ],
            [
                make_tool_call_payload("edit_file", {"path": "src/main.py", "diff": "..."}, call_id="tc_2_0"),
                make_tool_call_payload("read_file", {"path": "src/main.py"}, call_id="tc_2_1"),
                make_tool_call_payload("write_file", {"path": "tests/test_new.py", "content": "..."}, call_id="tc_2_2"),
            ],
            [
                make_tool_call_payload("shell", {"command": "pytest tests/test_new.py"}, call_id="tc_3_0"),
                make_tool_call_payload("glob", {"pattern": "tests/*.py"}, call_id="tc_3_1"),
                make_tool_call_payload("grep", {"pattern": "assert"}, call_id="tc_3_2"),
            ],
            [
                make_tool_call_payload("read_file", {"path": "src/main.py"}, call_id="tc_4_0"),
                make_tool_call_payload("shell", {"command": "pytest --cov"}, call_id="tc_4_1"),
                make_tool_call_payload("edit_file", {"path": "src/main.py", "diff": "..."}, call_id="tc_4_2"),
            ],
        ]

        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="Implementation complete. All tests pass with 95% coverage.",
        )

        dist = LatencyDistribution("5_iterations_3_tools")
        report = StressReport("Tool-Heavy Turn")

        for _ in range(5):
            llm.reset()
            orch = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Implement the new feature and write tests"}]

            total_tools = 0
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
                total_tools += len(results)

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
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
            assert total_tools == 15

        report.add_distribution(dist)
        report.custom_metrics = {
            "total_tool_calls": 15,
            "total_llm_calls": 6,
            "iterations": 5,
        }
        assert dist.p50 < 500

    async def test_shell_serial_barrier_scenario(self, setup):
        """Multiple shell commands in a row → serial execution barrier."""
        registry, config, context = setup

        tool_sequence = [
            [
                make_tool_call_payload("shell", {"command": "npm install"}),
                make_tool_call_payload("shell", {"command": "npm run build"}),
                make_tool_call_payload("shell", {"command": "npm test"}),
            ],
        ]

        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="Build and tests completed.",
        )

        dist = LatencyDistribution("shell_serial_barrier")
        for _ in range(20):
            llm.reset()
            orch = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Build and test"}]

            async with measure("turn", dist):
                async for chunk in llm.chat_completion_stream(messages):
                    if chunk.tool_calls:
                        calls = [ToolCall.from_openai(tc) for tc in chunk.tool_calls]
                        results = await orch.execute_collect(calls, context)
                        assert len(results) == 3

        # 3 serial 8ms shell tools → ~25-40ms + 5ms LLM
        assert dist.p95 < 100

    async def test_read_parallel_then_write_serial(self, setup):
        """Read 5 files in parallel → write 1 file serial → realistic pattern."""
        registry, config, context = setup

        tool_sequence = [
            [
                make_tool_call_payload("read_file", {"path": f"src/file_{i}.py"}, call_id=f"r_{i}")
                for i in range(5)
            ],
            [
                make_tool_call_payload("write_file", {"path": "src/output.py", "content": "..."}, call_id="w_0"),
            ],
        ]

        llm = MockLLMAdapter(
            latency_ms=5,
            tool_call_sequence=tool_sequence,
            final_response="Files read and output written.",
        )

        dist = LatencyDistribution("read_parallel_write_serial")
        for _ in range(20):
            llm.reset()
            orch = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Read files and write output"}]
            total_tools = 0

            async with measure("turn", dist):
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
                    total_tools += len(results)
                    messages.append({
                        "role": "assistant", "content": None, "tool_calls": tool_calls,
                    })
                    for r in results:
                        messages.append({
                            "role": "tool", "tool_call_id": r.tool_call_id, "content": r.content,
                        })
                    iteration += 1
                    if iteration >= 10:
                        break

            assert total_tools == 6  # 5 reads + 1 write

        assert dist.p95 < 200
