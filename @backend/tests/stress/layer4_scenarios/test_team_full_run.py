"""Full agent scenario: simulated multi-agent team run.

Simulates the team chat orchestration pattern: multiple agents running in parallel,
each doing LLM calls + tool execution, with a coordinator phase.
Does NOT test the actual team chat code (which requires full DI container),
but simulates the same async patterns.
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
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, StressReport, measure


@pytest.mark.stress
class TestTeamFullRun:
    """Simulate a full multi-agent team run end-to-end."""

    @pytest.fixture
    def setup(self, tmp_path: Path):
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=3))
        registry.register(make_mock_tool("grep", concurrency_safe=True, latency_ms=2))
        registry.register(make_mock_tool("shell", concurrency_safe=False, latency_ms=5))
        config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path), max_concurrency=4)
        context = ToolUseContext(
            conversation_id="team-run-conv",
            workspace_root=tmp_path,
            cwd=tmp_path,
            allowed_roots=(tmp_path,),
        )
        return registry, config, context

    async def test_team_4_agents_3_rounds(self, setup):
        """4 agents × 3 rounds → full team simulation."""
        registry, config, context = setup

        agent_configs = [
            {"name": "analyst", "tool": "read_file", "latency_ms": 10},
            {"name": "critic", "tool": "grep", "latency_ms": 8},
            {"name": "builder", "tool": "read_file", "latency_ms": 12},
            {"name": "reviewer", "tool": "grep", "latency_ms": 8},
        ]

        report = StressReport("Team 4-Agent 3-Round Run")
        round_dist = LatencyDistribution("round_duration")
        contract_dist = LatencyDistribution("contract_phase")
        synthesis_dist = LatencyDistribution("synthesis_phase")
        vote_dist = LatencyDistribution("vote_phase")

        for _ in range(3):
            # Phase 0: Execution Contract (coordinator)
            coordinator = MockLLMAdapter(
                latency_ms=15,
                final_response='{"summary": "analysis task", "subproblems": []}',
            )
            async with measure("contract", contract_dist):
                messages = [{"role": "user", "content": "Coordinate team"}]
                async for chunk in coordinator.chat_completion_stream(messages):
                    pass

            # Phase 1-3: Rounds
            for round_num in range(3):
                async with measure("round", round_dist):
                    # All agents run in parallel (like _run_agent_turns_parallel)
                    async def run_agent(agent_cfg):
                        agent_llm = MockLLMAdapter(
                            latency_ms=agent_cfg["latency_ms"],
                            tool_call_sequence=[
                                [make_tool_call_payload(agent_cfg["tool"], {"path": "src/main.py"})],
                            ],
                            final_response=f"{agent_cfg['name']} analysis complete.",
                        )
                        orch = ToolOrchestrator(registry, config)
                        messages = [{"role": "user", "content": f"Round {round_num}"}]
                        iteration = 0
                        while True:
                            tool_calls = []
                            async for chunk in agent_llm.chat_completion_stream(messages):
                                if chunk.tool_calls:
                                    tool_calls.extend(chunk.tool_calls)
                            if not tool_calls:
                                break
                            calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                            await orch.execute_collect(calls, context)
                            iteration += 1
                            if iteration >= 5:
                                break

                    await asyncio.gather(*[run_agent(cfg) for cfg in agent_configs])

                # Vote phase (parallel)
                if round_num % 2 == 1 or round_num == 2:
                    vote_llms = [
                        MockLLMAdapter(latency_ms=5, final_response='{"approve": true, "confidence": 0.9}')
                        for _ in range(4)
                    ]
                    async with measure("vote", vote_dist):
                        async def cast_vote(llm):
                            messages = [{"role": "user", "content": "Vote"}]
                            async for chunk in llm.chat_completion_stream(messages):
                                pass
                        await asyncio.gather(*[cast_vote(llm) for llm in vote_llms])

            # Final synthesis (coordinator)
            synthesis_llm = MockLLMAdapter(
                latency_ms=15,
                final_response="Final synthesized answer from all agents.",
            )
            async with measure("synthesis", synthesis_dist):
                messages = [{"role": "user", "content": "Synthesize"}]
                async for chunk in synthesis_llm.chat_completion_stream(messages):
                    pass

        report.add_distribution(contract_dist)
        report.add_distribution(round_dist)
        report.add_distribution(vote_dist)
        report.add_distribution(synthesis_dist)
        report.custom_metrics = {
            "agents": 4,
            "rounds": 3,
            "votes": 3,  # 3 vote phases per run
        }

        assert contract_dist.p50 < 100
        assert round_dist.p50 < 200
        assert vote_dist.p50 < 50
        assert synthesis_dist.p50 < 100

    async def test_team_parallelism_efficiency(self, setup):
        """Compare sequential vs parallel agent execution → efficiency ratio."""
        registry, config, context = setup

        agent_cfgs = [
            {"name": f"agent_{i}", "tool": "read_file", "latency_ms": 15}
            for i in range(4)
        ]

        async def run_agent(cfg):
            llm = MockLLMAdapter(
                latency_ms=cfg["latency_ms"],
                tool_call_sequence=[
                    [make_tool_call_payload(cfg["tool"], {"path": "file.py"})],
                ],
                final_response=f"{cfg['name']} done.",
            )
            orch = ToolOrchestrator(registry, config)
            messages = [{"role": "user", "content": "Analyze"}]
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

        # Sequential baseline
        seq_dist = LatencyDistribution("sequential_agents")
        for _ in range(5):
            start = time.perf_counter()
            for cfg in agent_cfgs:
                await run_agent(cfg)
            seq_dist.record((time.perf_counter() - start) * 1000)

        # Parallel run
        par_dist = LatencyDistribution("parallel_agents")
        for _ in range(5):
            start = time.perf_counter()
            await asyncio.gather(*[run_agent(cfg) for cfg in agent_cfgs])
            par_dist.record((time.perf_counter() - start) * 1000)

        efficiency = seq_dist.p50 / par_dist.p50 if par_dist.p50 > 0 else 0
        assert efficiency > 2  # at least 2x speedup with 4 agents
