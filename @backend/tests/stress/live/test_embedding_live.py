"""Live embedding server benchmarks.

Tests the real GGUF embedding server (Qwen3-Embedding-8B) for latency,
throughput, and batch processing performance.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from tests.stress.live.conftest import live_enabled, skip_reason
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, StressReport


pytestmark = pytest.mark.stress_live


def _embedding_available() -> bool:
    if not live_enabled():
        return False
    import httpx
    url = os.getenv("EMBEDDING_SERVER_URL", "http://localhost:8081/v1")
    try:
        resp = httpx.get(f"{url}/models", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def real_embedding():
    """Real embedding adapter connected to the local GGUF server."""
    from personagent.infrastructure.llm.shared.embedding_adapter import OpenAICompatibleEmbeddingAdapter
    url = os.getenv("EMBEDDING_SERVER_URL", "http://localhost:8081/v1")
    return OpenAICompatibleEmbeddingAdapter(
        base_url=url,
        api_key="local",
        model=os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-8B-Q4_K_M.gguf"),
        timeout=float(os.getenv("EMBEDDING_TIMEOUT", "60")),
    )


@pytest.mark.skipif(not _embedding_available(), reason="Embedding server not running at localhost:8081")
class TestEmbeddingLive:
    """Benchmark the real embedding server."""

    async def test_single_text_latency(self, real_embedding):
        """Single text embedding → baseline latency."""
        dist = LatencyDistribution("single_embed")

        for _ in range(20):
            start = time.perf_counter()
            vectors = await real_embedding.embed(["This is a test sentence for embedding."])
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)
            assert len(vectors) == 1
            assert len(vectors[0]) > 0

        report = StressReport("Single Embedding Latency")
        report.add_distribution(dist)
        print(f"\n{report.to_markdown()}")
        assert dist.p95 < 5000  # should be under 5s even on CPU

    async def test_batch_embedding_throughput(self, real_embedding):
        """Batch of 10 texts → measure throughput."""
        texts = [f"This is test sentence number {i} for batch embedding benchmark." for i in range(10)]
        dist = LatencyDistribution("batch_10_embed")

        for _ in range(10):
            start = time.perf_counter()
            vectors = await real_embedding.embed(texts)
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)
            assert len(vectors) == 10

        report = StressReport("Batch Embedding (10 texts)")
        report.add_distribution(dist)
        report.custom_metrics = {"batch_size": 10, "dimensions": len(vectors[0]) if vectors else 0}
        print(f"\n{report.to_markdown()}")

    async def test_embedding_dimensions(self, real_embedding):
        """Verify embedding dimensions match configuration."""
        vectors = await real_embedding.embed(["Test"])
        assert len(vectors) == 1
        dim = len(vectors[0])
        print(f"\nEmbedding dimensions: {dim}")
        assert dim >= 256, f"Expected >= 256 dimensions, got {dim}"

    async def test_concurrent_embedding_requests(self, real_embedding):
        """5 concurrent embedding requests → measure backpressure."""
        async def embed_one():
            return await real_embedding.embed(["Concurrent embedding test."])

        result = await run_concurrent(5, embed_one)
        print(f"\n{result.summary('5 Concurrent Embeddings')}")
        assert result.successful > 0
        # With parallel=1, expect sequential execution
        print(f"Note: embedding server uses parallel=1, so expect sequential execution")

    async def test_embedding_stability(self, real_embedding):
        """10 sequential embeddings → verify consistent dimensions and no errors."""
        dim_dist = LatencyDistribution("embedding_stability")
        expected_dim = None

        for i in range(10):
            start = time.perf_counter()
            vectors = await real_embedding.embed([f"Stability test {i}"])
            elapsed = (time.perf_counter() - start) * 1000
            dim_dist.record(elapsed)

            assert len(vectors) == 1
            dim = len(vectors[0])
            if expected_dim is None:
                expected_dim = dim
            assert dim == expected_dim, f"Dimension mismatch: {dim} != {expected_dim}"

        report = StressReport("Embedding Stability")
        report.add_distribution(dim_dist)
        report.custom_metrics = {"dimensions": expected_dim, "runs": 10}
        print(f"\n{report.to_markdown()}")

    async def test_large_text_embedding(self, real_embedding):
        """Large text (10KB) → measure latency scaling."""
        large_text = "word " * 2500  # ~10KB

        dist = LatencyDistribution("large_text_embed")
        for _ in range(5):
            start = time.perf_counter()
            vectors = await real_embedding.embed([large_text])
            elapsed = (time.perf_counter() - start) * 1000
            dist.record(elapsed)
            assert len(vectors) == 1

        report = StressReport("Large Text Embedding (10KB)")
        report.add_distribution(dist)
        print(f"\n{report.to_markdown()}")
