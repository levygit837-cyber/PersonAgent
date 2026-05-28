"""Pipeline benchmarks for memory capture and embedding throughput."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.services.operational_memory.capture import OperationalMemoryCapture
from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
)

from tests.stress.mock_embedding import MockEmbeddingAdapter
from tests.stress.concurrent_runner import run_concurrent
from tests.stress.metrics import LatencyDistribution, measure


def _make_capture_service(embedding_adapter, *, latency_ms: float = 50):
    from collections import defaultdict

    repository = MagicMock()
    repository.record_event = AsyncMock()
    repository.record_chunks = AsyncMock(side_effect=lambda chunks: chunks)
    repository.record_structured_items = AsyncMock()
    repository.record_embeddings = AsyncMock()
    repository.mark_chunks_failed = AsyncMock()
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(deque)

    return OperationalMemoryCapture(
        repository=repository,
        redactor=OperationalMemoryRedactor(),
        chunker=OperationalMemoryChunker(),
        extractor=MagicMock(structured_items_from_event=MagicMock(return_value=[])),
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embedding_adapter is not None,
        embedding_model="mock-embed",
        capture_tools_enabled=True,
        max_capture_chars=24_000,
        queue=None,
        queue_enabled=False,
        queue_fallback_sync=True,
        hot_cache=hot_cache,
    )


@pytest.mark.stress
class TestMemoryPipelineBenchmarks:

    async def test_full_capture_cycle_small(self):
        """Small message → capture + chunk + embed + store."""
        mock_embed = MockEmbeddingAdapter(latency_ms=10, dimensions=1024)
        service = _make_capture_service(mock_embed)

        dist = LatencyDistribution("capture_small")
        for i in range(50):
            async with measure("capture", dist):
                await service.capture_user_message(
                    project_slug="test-project",
                    workspace_root="/tmp/test",
                    conversation_id=f"conv-{i}",
                    message=f"Test message {i} for benchmarking.",
                )

        assert dist.p50 < 100
        assert mock_embed.call_count == 50

    async def test_full_capture_cycle_large(self):
        """Large 50KB message → many chunks → batch embed."""
        mock_embed = MockEmbeddingAdapter(latency_ms=20, dimensions=1024)
        service = _make_capture_service(mock_embed)
        large_message = "word " * 10000  # ~50KB

        dist = LatencyDistribution("capture_large")
        for i in range(10):
            async with measure("capture", dist):
                await service.capture_user_message(
                    project_slug="test-project",
                    workspace_root="/tmp/test",
                    conversation_id=f"conv-{i}",
                    message=large_message,
                )

        # Should generate multiple chunks per message
        assert mock_embed.total_texts_embedded > 10

    async def test_sequential_10_captures_throughput(self):
        """10 sequential captures → measure throughput."""
        mock_embed = MockEmbeddingAdapter(latency_ms=5, dimensions=1024)
        service = _make_capture_service(mock_embed)

        dist = LatencyDistribution("10_sequential_captures")
        async with measure("batch", dist):
            for i in range(10):
                await service.capture_user_message(
                    project_slug="test-project",
                    workspace_root="/tmp/test",
                    conversation_id="conv-1",
                    message=f"Message {i}: " + "content " * 100,
                )

        assert dist.count == 1
        assert dist.samples[0] < 1000  # 10 captures under 1s

    async def test_concurrent_captures_backpressure(self):
        """5 concurrent capture operations → measure backpressure on embedding."""
        # With parallel=1 embedding mock, captures should serialize on embedding
        mock_embed = MockEmbeddingAdapter(latency_ms=30, dimensions=1024)

        async def capture_one(i: int):
            service = _make_capture_service(mock_embed)
            await service.capture_user_message(
                project_slug="test-project",
                workspace_root="/tmp/test",
                conversation_id=f"conv-{i}",
                message=f"Concurrent message {i} with some content.",
            )

        result = await run_concurrent(5, lambda: capture_one(0))
        assert result.successful == 5

    async def test_embedding_only_latency(self):
        """Isolate embedding latency from capture overhead."""
        mock_embed = MockEmbeddingAdapter(latency_ms=50, dimensions=1024)

        dist = LatencyDistribution("embedding_only")
        for _ in range(50):
            texts = [f"chunk text {i}" for i in range(3)]
            async with measure("embed", dist):
                await mock_embed.embed(texts)

        assert dist.p50 < 100
        assert dist.p95 < 200

    async def test_chunking_throughput_large_content(self):
        """Chunk 100KB content → measure pure chunking speed (no embed)."""
        chunker = OperationalMemoryChunker()
        content = "x " * 50000  # ~100KB

        dist = LatencyDistribution("chunking_100kb")
        for _ in range(100):
            async with measure("chunk", dist):
                chunks = chunker.chunk_text(
                    project_slug="test",
                    source_type="user_message",
                    source_id="test-id",
                    content=content,
                )

        assert dist.p95 < 50  # chunking should be fast
