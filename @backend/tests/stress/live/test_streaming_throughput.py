"""Live streaming throughput and chunk analysis.

Measures chunk delivery patterns, inter-chunk gaps, and content accumulation
from real LLM providers.
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
    provider_available,
    skip_reason,
)
from tests.stress.metrics import LatencyDistribution, StressReport


pytestmark = pytest.mark.stress_live


def _any_provider_available() -> bool:
    if not live_enabled():
        return False
    return any(provider_available(p) for p in ["nvidia", "vertex", "kimi", "deepseek", "codex", "llama"])


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestStreamingThroughput:
    """Analyze streaming chunk delivery patterns from real providers."""

    async def test_chunk_delivery_pattern(self):
        """Analyze inter-chunk gap distribution."""
        adapter = build_adapter()
        iterations = min(live_iterations(), 5)

        try:
            all_gaps: list[float] = []
            all_chunk_counts: list[int] = []

            for _ in range(iterations):
                chunk_times: list[float] = []
                start = time.perf_counter()
                async for chunk in adapter.chat_completion_stream(
                    messages=[{
                        "role": "user",
                        "content": "List 5 programming languages with one sentence each.",
                    }],
                    max_tokens=200,
                    temperature=0.3,
                ):
                    chunk_times.append(time.perf_counter())

                all_chunk_counts.append(len(chunk_times))
                for i in range(1, len(chunk_times)):
                    gap_ms = (chunk_times[i] - chunk_times[i - 1]) * 1000
                    all_gaps.append(gap_ms)

            if all_gaps:
                gap_dist = LatencyDistribution("inter_chunk_gap_ms")
                gap_dist.samples = all_gaps

                report = StressReport("Chunk Delivery Pattern")
                report.add_distribution(gap_dist)
                report.custom_metrics = {
                    "total_chunks": sum(all_chunk_counts),
                    "avg_chunks_per_response": sum(all_chunk_counts) / len(all_chunk_counts),
                    "max_inter_chunk_gap_ms": max(all_gaps),
                }
                print(f"\n{report.to_markdown()}")
            else:
                print("\nNo chunks received")
        finally:
            await adapter.close()

    async def test_content_accumulation_rate(self):
        """Measure how fast content accumulates during streaming."""
        adapter = build_adapter()

        try:
            samples: list[tuple[float, int]] = []  # (elapsed_ms, content_chars)
            start = time.perf_counter()
            total_content = ""
            async for chunk in adapter.chat_completion_stream(
                messages=[{
                    "role": "user",
                    "content": "Write a detailed paragraph about async programming in Python.",
                }],
                max_tokens=300,
                temperature=0.5,
            ):
                total_content += chunk.content
                elapsed_ms = (time.perf_counter() - start) * 1000
                samples.append((elapsed_ms, len(total_content)))

            if samples:
                final_time, final_chars = samples[-1]
                chars_per_sec = (final_chars / (final_time / 1000)) if final_time > 0 else 0
                print(f"\nContent: {final_chars} chars in {final_time:.0f}ms")
                print(f"Rate: {chars_per_sec:.0f} chars/sec")
                print(f"Chunks: {len(samples)}")

                # Verify content is non-trivial
                assert final_chars > 10, f"Too little content: {final_chars} chars"
        finally:
            await adapter.close()

    async def test_reasoning_content_presence(self):
        """Check if the provider emits reasoning_content (thinking tokens)."""
        adapter = build_adapter()

        try:
            content = ""
            reasoning = ""
            async for chunk in adapter.chat_completion_stream(
                messages=[{
                    "role": "user",
                    "content": "Think step by step: what is 15 * 17?",
                }],
                max_tokens=300,
                temperature=0.0,
            ):
                content += chunk.content
                reasoning += chunk.reasoning_content

            has_content = bool(content.strip())
            has_reasoning = bool(reasoning.strip())
            print(f"\nContent: {len(content)} chars, Reasoning: {len(reasoning)} chars")
            print(f"Thinking support: {'yes' if has_reasoning else 'no'}")
            assert has_content or has_reasoning, "No content or reasoning received"
        finally:
            await adapter.close()
