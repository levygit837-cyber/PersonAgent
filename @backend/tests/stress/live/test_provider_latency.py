"""Live provider latency benchmarks — TTFT, streaming throughput, non-streaming latency.

Measures real-world latency characteristics of each LLM provider.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from tests.stress.live.conftest import (
    build_adapter,
    live_enabled,
    live_iterations,
    live_timeout,
    provider_available,
    skip_reason,
)
from tests.stress.metrics import LatencyDistribution, StressReport


pytestmark = pytest.mark.stress_live


def _any_provider_available() -> bool:
    if not live_enabled():
        return False
    return any(
        provider_available(p)
        for p in ["nvidia", "vertex", "kimi", "deepseek", "codex", "llama"]
    )


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestProviderLatency:
    """Measure TTFT and total latency for each configured provider."""

    async def test_streaming_ttft(self):
        """Measure time-to-first-token for streaming completion."""
        adapter = build_adapter()
        dist = LatencyDistribution("streaming_ttft")
        iterations = live_iterations()

        try:
            for _ in range(iterations):
                start = time.perf_counter()
                first_chunk_time = None
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "Say 'hello' in one word."}],
                    max_tokens=10,
                    temperature=0.0,
                ):
                    if first_chunk_time is None and chunk.content:
                        first_chunk_time = time.perf_counter()
                if first_chunk_time is not None:
                    ttft = (first_chunk_time - start) * 1000
                    dist.record(ttft)

            report = StressReport("Streaming TTFT")
            report.add_distribution(dist)
            report.custom_metrics = {"iterations": iterations, "max_tokens": 10}
            print(f"\n{report.to_markdown()}")
            assert dist.count > 0, "No chunks received"
        finally:
            await adapter.close()

    async def test_streaming_total_latency(self):
        """Measure total streaming completion time."""
        adapter = build_adapter()
        dist = LatencyDistribution("streaming_total")
        iterations = live_iterations()

        try:
            for _ in range(iterations):
                start = time.perf_counter()
                content = ""
                async for chunk in adapter.chat_completion_stream(
                    messages=[{"role": "user", "content": "Count from 1 to 10, one number per line."}],
                    max_tokens=100,
                    temperature=0.0,
                ):
                    content += chunk.content
                elapsed = (time.perf_counter() - start) * 1000
                dist.record(elapsed)

            report = StressReport("Streaming Total")
            report.add_distribution(dist)
            report.custom_metrics = {"iterations": iterations, "max_tokens": 100}
            print(f"\n{report.to_markdown()}")
            assert dist.count > 0
        finally:
            await adapter.close()

    async def test_non_streaming_latency(self):
        """Measure non-streaming completion latency."""
        adapter = build_adapter()
        dist = LatencyDistribution("non_streaming_total")
        iterations = min(live_iterations(), 5)  # fewer for non-streaming

        try:
            for _ in range(iterations):
                start = time.perf_counter()
                result = await adapter.chat_completion(
                    messages=[{"role": "user", "content": "What is 2 + 2?"}],
                    max_tokens=50,
                    temperature=0.0,
                )
                elapsed = (time.perf_counter() - start) * 1000
                dist.record(elapsed)
                assert result.content.strip(), "Empty response"

            report = StressReport("Non-Streaming Total")
            report.add_distribution(dist)
            report.custom_metrics = {"iterations": iterations}
            print(f"\n{report.to_markdown()}")
        finally:
            await adapter.close()

    async def test_streaming_tokens_per_second(self):
        """Estimate tokens/sec from streaming chunks."""
        adapter = build_adapter()
        iterations = live_iterations()

        try:
            total_tokens = 0
            total_time_s = 0.0
            for _ in range(iterations):
                start = time.perf_counter()
                chunk_count = 0
                content_len = 0
                async for chunk in adapter.chat_completion_stream(
                    messages=[{
                        "role": "user",
                        "content": "Write a 5-sentence paragraph about Python programming.",
                    }],
                    max_tokens=300,
                    temperature=0.7,
                ):
                    chunk_count += 1
                    content_len += len(chunk.content)
                elapsed_s = time.perf_counter() - start
                # Rough token estimate: ~4 chars per token
                estimated_tokens = content_len / 4
                total_tokens += estimated_tokens
                total_time_s += elapsed_s

            avg_tps = total_tokens / total_time_s if total_time_s > 0 else 0
            print(f"\nEstimated tokens/sec: {avg_tps:.1f} (across {iterations} runs)")
            assert avg_tps > 0
        finally:
            await adapter.close()


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestProviderHealthCheck:
    """Verify provider health endpoints respond correctly."""

    async def test_health_check(self):
        """Health check should return healthy status."""
        adapter = build_adapter()
        try:
            health = await adapter.health_check()
            print(f"\nHealth: {health}")
            assert health.get("status") in ("healthy", "ok", "available")
        finally:
            await adapter.close()

    async def test_model_info(self):
        """Model info should return model details."""
        adapter = build_adapter()
        try:
            info = await adapter.get_model_info()
            print(f"\nModel info: {info}")
            assert info, "Empty model info"
        finally:
            await adapter.close()
