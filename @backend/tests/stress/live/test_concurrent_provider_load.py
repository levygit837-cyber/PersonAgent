"""Live concurrent provider load tests.

Tests how real LLM providers handle multiple simultaneous requests.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from tests.stress.live.conftest import (
    build_adapter,
    live_concurrency,
    live_enabled,
    live_iterations,
    provider_available,
    skip_reason,
)
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, StressReport


pytestmark = pytest.mark.stress_live


def _any_provider_available() -> bool:
    if not live_enabled():
        return False
    return any(provider_available(p) for p in ["nvidia", "vertex", "kimi", "deepseek", "codex", "llama"])


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestConcurrentProviderLoad:
    """Test real provider behavior under concurrent load."""

    async def test_concurrent_streaming_completions(self):
        """N concurrent streaming completions → measure P50/P95/P99."""
        concurrency = min(live_concurrency(), 5)
        adapter = build_adapter()
        report = StressReport(f"Concurrent Streaming ({concurrency}x)")

        try:
            async def one_request():
                content = ""
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=10,
                    temperature=0.0,
                ):
                    content += chunk.content
                return content

            result = await run_concurrent(concurrency, one_request)
            print(f"\n{result.summary(f'{concurrency} Concurrent Streaming')}")

            report.custom_metrics = {
                "concurrency": concurrency,
                "successful": result.successful,
                "failed": result.failed,
                "p50_ms": round(result.p50, 1),
                "p95_ms": round(result.p95, 1),
                "p99_ms": round(result.p99, 1),
                "throughput_rps": round(result.throughput_rps, 1),
            }
            print(f"\n{report.to_markdown()}")

            assert result.successful > 0, f"All {concurrency} requests failed"
            if result.errors:
                print(f"\nErrors ({len(result.errors)}):")
                for err in result.errors[:3]:
                    print(f"  {type(err).__name__}: {err}")
        finally:
            await adapter.close()

    async def test_concurrent_non_streaming_completions(self):
        """N concurrent non-streaming completions → measure latency distribution."""
        concurrency = min(live_concurrency(), 3)  # fewer for non-streaming
        adapter = build_adapter()

        try:
            async def one_request():
                result = await adapter.chat_completion(
                    messages=[{"role": "user", "content": "What is 2 + 2?"}],
                    max_tokens=20,
                    temperature=0.0,
                )
                return result.content

            result = await run_concurrent(concurrency, one_request)
            print(f"\n{result.summary(f'{concurrency} Concurrent Non-Streaming')}")

            assert result.successful > 0
        finally:
            await adapter.close()

    async def test_sequential_vs_parallel_latency(self):
        """Compare sequential vs parallel request latency → parallelism benefit."""
        n = min(live_concurrency(), 3)
        adapter = build_adapter()

        try:
            # Sequential baseline
            seq_times: list[float] = []
            for _ in range(n):
                start = time.perf_counter()
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "Say 'hi'."}],
                    max_tokens=5,
                    temperature=0.0,
                ):
                    pass
                seq_times.append((time.perf_counter() - start) * 1000)

            seq_total = sum(seq_times)

            # Parallel run
            async def one():
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "Say 'hi'."}],
                    max_tokens=5,
                    temperature=0.0,
                ):
                    pass

            par_start = time.perf_counter()
            await asyncio.gather(*[one() for _ in range(n)])
            par_total = (time.perf_counter() - par_start) * 1000

            speedup = seq_total / par_total if par_total > 0 else 0
            print(f"\nSequential: {seq_total:.0f}ms | Parallel: {par_total:.0f}ms | Speedup: {speedup:.1f}x")
            assert speedup > 1.0, f"Parallel should be faster (got {speedup:.1f}x)"
        finally:
            await adapter.close()

    async def test_concurrent_with_tool_calls(self):
        """N concurrent requests with tool definitions → verify tool call support under load."""
        concurrency = min(live_concurrency(), 3)
        adapter = build_adapter()

        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                    },
                    "required": ["location"],
                },
            },
        }]

        try:
            async def one_request():
                content = ""
                tool_calls = []
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "What is the weather in Tokyo?"}],
                    max_tokens=100,
                    temperature=0.0,
                    tools=tools,
                ):
                    content += chunk.content
                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
                return {"content": content, "tool_calls": len(tool_calls)}

            result = await run_concurrent(concurrency, one_request)
            print(f"\n{result.summary(f'{concurrency} Concurrent Tool Calls')}")
            assert result.successful > 0
        finally:
            await adapter.close()
