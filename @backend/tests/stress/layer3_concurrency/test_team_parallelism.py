"""Concurrency tests simulating multi-agent team parallelism.

Tests the asyncio.create_task / asyncio.gather patterns used in team chat
without requiring the full team chat orchestrator setup.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, measure
from tests.stress.mock_llm import MockLLMAdapter


@pytest.mark.stress
class TestTeamParallelism:
    """Test parallel agent execution patterns used in team chat."""

    async def test_3_agents_parallel(self):
        """3 agents running in parallel via asyncio.create_task → measure efficiency."""
        agents = [
            MockLLMAdapter(latency_ms=20, final_response=f"Agent {i} analysis complete.")
            for i in range(3)
        ]

        async def run_agent(agent: MockLLMAdapter, agent_id: int):
            messages = [{"role": "user", "content": f"Analyze topic {agent_id}"}]
            chunks = []
            async for chunk in agent.chat_completion_stream(messages):
                chunks.append(chunk)
            return "".join(c.content for c in chunks if c.content)

        dist = LatencyDistribution("3_agents_parallel")
        for _ in range(20):
            start = time.perf_counter()
            results = await asyncio.gather(
                *[run_agent(agent, i) for i, agent in enumerate(agents)]
            )
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)
            assert len(results) == 3

        # 3 agents with 20ms each should complete in ~25-40ms (not 60ms)
        assert dist.p50 < 80

    async def test_5_agents_parallel(self):
        """5 agents in parallel → measures scaling."""
        agents = [
            MockLLMAdapter(latency_ms=15, final_response=f"Agent {i} result")
            for i in range(5)
        ]

        async def run_agent(agent, i):
            messages = [{"role": "user", "content": f"Task {i}"}]
            async for chunk in agent.chat_completion_stream(messages):
                pass

        dist = LatencyDistribution("5_agents_parallel")
        for _ in range(20):
            start = time.perf_counter()
            await asyncio.gather(*[run_agent(a, i) for i, a in enumerate(agents)])
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)

        assert dist.p50 < 80

    async def test_parallel_efficiency_ratio(self):
        """Measure parallelism efficiency: sum(individual) / wall_time."""
        agent_latency_ms = 20

        # Sequential baseline
        sequential_dist = LatencyDistribution("sequential_3_agents")
        for _ in range(10):
            start = time.perf_counter()
            for i in range(3):
                agent = MockLLMAdapter(latency_ms=agent_latency_ms, final_response=f"Result {i}")
                messages = [{"role": "user", "content": f"Task {i}"}]
                async for chunk in agent.chat_completion_stream(messages):
                    pass
            elapsed = (time.perf_counter() - start) * 1000
            sequential_dist.record(elapsed)

        # Parallel run
        parallel_dist = LatencyDistribution("parallel_3_agents")
        for _ in range(10):
            agents = [
                MockLLMAdapter(latency_ms=agent_latency_ms, final_response=f"Result {i}")
                for i in range(3)
            ]
            start = time.perf_counter()
            await asyncio.gather(*[
                _run_mock_agent(a) for a in agents
            ])
            elapsed = (time.perf_counter() - start) * 1000
            parallel_dist.record(elapsed)

        efficiency = sequential_dist.p50 / parallel_dist.p50 if parallel_dist.p50 > 0 else 0
        # Should be ~2-3x speedup
        assert efficiency > 1.5

    async def test_agent_with_tool_calls_parallel(self):
        """3 agents each doing tool calls in parallel → team simulation."""
        from personagent.application.tools.orchestrator import ToolOrchestrator
        from personagent.application.tools.registry import ToolRegistry
        from personagent.application.tools.runtime_config import ToolRuntimeConfig
        from personagent.domain.tools import ToolCall, ToolUseContext
        from tests.stress.conftest import make_mock_tool
        from tests.stress.mock_llm import make_tool_call_payload
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            tmp_path = Path(tmp)
            registry = ToolRegistry()
            registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=2))
            config = ToolRuntimeConfig.from_values(workspace_root=str(tmp))
            context = ToolUseContext(
                conversation_id="team-conv",
                workspace_root=tmp_path,
                cwd=tmp_path,
                allowed_roots=(tmp_path,),
            )

            async def run_agent(i: int):
                llm = MockLLMAdapter(
                    latency_ms=5,
                    tool_call_sequence=[
                        [make_tool_call_payload("read_file", {"path": f"file_{i}.py"})],
                    ],
                    final_response=f"Agent {i} done.",
                )
                orch = ToolOrchestrator(registry, config)
                messages = [{"role": "user", "content": f"Analyze file {i}"}]
                iteration = 0
                while True:
                    tool_calls = []
                    async for chunk in llm.chat_completion_stream(messages):
                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)
                    if not tool_calls:
                        break
                    calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                    await orch.execute_collect(calls, context)
                    iteration += 1
                    if iteration >= 5:
                        break

            dist = LatencyDistribution("3_agents_with_tools")
            for _ in range(10):
                start = time.perf_counter()
                await asyncio.gather(*[run_agent(i) for i in range(3)])
                elapsed = (time.perf_counter() - start) * 1000
                dist.record(elapsed)

            assert dist.p95 < 200


async def _run_mock_agent(agent: MockLLMAdapter):
    messages = [{"role": "user", "content": "Task"}]
    async for chunk in agent.chat_completion_stream(messages):
        pass
