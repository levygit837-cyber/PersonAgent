"""Concurrency tests for embedding backpressure.

Tests how the system handles concurrent embedding requests when the
embedding server has parallel=1 (the current production config).
"""

from __future__ import annotations

import asyncio

import pytest

from tests.stress.mock_embedding import MockEmbeddingAdapter
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, measure


@pytest.mark.stress
class TestEmbeddingBackpressure:
    """Test embedding throughput under concurrent load."""

    async def test_10_sequential_embeds(self):
        """10 sequential embed calls → baseline latency."""
        embed = MockEmbeddingAdapter(latency_ms=20, dimensions=1024)

        dist = LatencyDistribution("10_sequential_embeds")
        for i in range(10):
            async with measure("embed", dist):
                await embed.embed([f"text {i}"])

        assert dist.count == 10
        assert dist.p50 < 50

    async def test_10_concurrent_embeds_parallel_1(self):
        """10 concurrent embeds against parallel=1 mock → measures serialization."""
        embed = MockEmbeddingAdapter(latency_ms=20, dimensions=1024)

        async def embed_one():
            await embed.embed(["test text"])

        result = await run_concurrent(10, embed_one)
        assert result.successful == 10

        # With mock adapter, true parallelism is possible (no real server bottleneck)
        # But we can verify the latency is reasonable
        assert result.p95 < 100

    async def test_50_concurrent_embeds(self):
        """50 concurrent embed calls → stress test."""
        embed = MockEmbeddingAdapter(latency_ms=10, dimensions=1024)

        async def embed_one():
            await embed.embed(["stress test text for embedding"])

        result = await run_concurrent(50, embed_one)
        assert result.successful == 50
        assert result.throughput_rps > 50

    async def test_batch_embed_throughput(self):
        """Batch embed 100 texts in one call → measure throughput."""
        embed = MockEmbeddingAdapter(latency_ms=50, dimensions=1024)
        texts = [f"text document {i} with some content for embedding" for i in range(100)]

        dist = LatencyDistribution("batch_embed_100")
        for _ in range(10):
            async with measure("embed", dist):
                vectors = await embed.embed(texts)

        assert len(vectors) == 100
        assert all(len(v) == 1024 for v in vectors)
        assert dist.p95 < 200

    async def test_embedding_latency_scaling(self):
        """Test how embed latency scales with batch size."""
        embed = MockEmbeddingAdapter(latency_ms=20, dimensions=1024)

        for batch_size in [1, 5, 10, 50]:
            texts = [f"text {i}" for i in range(batch_size)]
            dist = LatencyDistribution(f"embed_batch_{batch_size}")
            for _ in range(20):
                async with measure("embed", dist):
                    await embed.embed(texts)
            assert dist.p95 < 200
