"""Concurrency tests for mock LLM adapter pool behavior.

Tests how concurrent LLM calls behave when sharing an adapter instance,
simulating the singleton pattern used in the real DI container.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.stress.mock_llm import MockLLMAdapter
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, measure


@pytest.mark.stress
class TestLLMAdapterPool:
    """Test concurrent access to shared LLM adapter instances."""

    async def test_10_concurrent_calls_same_adapter(self):
        """10 concurrent calls to the same adapter instance."""
        shared_adapter = MockLLMAdapter(latency_ms=10, final_response="OK")

        async def call_one():
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in shared_adapter.chat_completion_stream(messages):
                pass

        result = await run_concurrent(10, call_one)
        assert result.successful == 10
        assert result.p95 < 200

    async def test_50_concurrent_calls_same_adapter(self):
        """50 concurrent calls to the same adapter → stress test."""
        shared_adapter = MockLLMAdapter(latency_ms=5, final_response="OK")

        async def call_one():
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in shared_adapter.chat_completion_stream(messages):
                pass

        result = await run_concurrent(50, call_one)
        assert result.successful == 50
        assert result.throughput_rps > 50

    async def test_multi_provider_concurrent(self):
        """10 calls each to 3 different adapters → multi-provider load."""
        adapters = [
            MockLLMAdapter(latency_ms=10, final_response=f"Provider {i} response")
            for i in range(3)
        ]

        async def call_provider(adapter):
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in adapter.chat_completion_stream(messages):
                pass

        all_tasks = []
        for adapter in adapters:
            all_tasks.extend([call_provider(adapter) for _ in range(10)])

        wall_start = asyncio.get_event_loop().time()
        await asyncio.gather(*all_tasks)
        wall_ms = (asyncio.get_event_loop().time() - wall_start) * 1000

        # 30 calls across 3 adapters, 10ms each → should complete in ~15-30ms
        assert wall_ms < 200

    async def test_adapter_call_count_tracking(self):
        """Verify adapter correctly tracks call counts under concurrent load."""
        adapter = MockLLMAdapter(latency_ms=5, final_response="OK")

        async def call_one():
            messages = [{"role": "user", "content": "Test"}]
            async for chunk in adapter.chat_completion_stream(messages):
                pass

        result = await run_concurrent(20, call_one)
        assert result.successful == 20
        assert adapter.call_count == 20
