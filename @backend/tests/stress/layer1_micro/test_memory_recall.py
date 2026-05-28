"""Micro-benchmarks for operational memory recall pipeline."""

from __future__ import annotations

import time
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.services.operational_memory.recall import (
    OperationalMemoryRecall,
    _should_recall_operational_memory,
    _normalize_query,
    _query_tokens,
)
from personagent.domain.memory.models.operational import (
    RecallFinding,
    StructuredMemoryPackage,
)
from personagent.domain.memory.services.operational_memory import OperationalMemoryRedactor

from tests.stress.mock_embedding import MockEmbeddingAdapter


def _make_recall_service(
    embedding_adapter: Any = None,
    embeddings_enabled: bool = True,
    recall_enabled: bool = True,
) -> OperationalMemoryRecall:
    """Build recall service with mocked repository."""
    repository = MagicMock()
    repository.record_recall_skip = AsyncMock()
    repository.recall_structured_package = AsyncMock(
        return_value=StructuredMemoryPackage(
            formatted="[memory] test finding",
            items=[],
            filters_applied={},
            budget_used=100,
            budget_tokens=100,
            omitted_count=0,
            latency_ms=5.0,
        )
    )

    hot_cache: dict[str, deque[RecallFinding]] = {}
    redactor = OperationalMemoryRedactor()

    return OperationalMemoryRecall(
        repository=repository,
        redactor=redactor,
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embeddings_enabled,
        recall_enabled=recall_enabled,
        recall_top_k=10,
        context_budget_tokens=4000,
        semantic_candidate_limit=80,
        recent_candidate_limit=40,
        hot_cache=hot_cache,
    )


@pytest.mark.stress
class TestMemoryRecallBenchmarks:

    async def test_recall_with_embedding(self, benchmark):
        """Full recall pipeline with mock embedding → measure latency."""
        mock_embed = MockEmbeddingAdapter(latency_ms=10, dimensions=1024)
        service = _make_recall_service(embedding_adapter=mock_embed)

        async def _run():
            await service.recall_for_prompt(
                project_slug="test-project",
                query="how does the tool orchestrator handle parallel execution",
            )

        await _run()  # warmup
        benchmark(lambda: _run.__wrapped__ if hasattr(_run, '__wrapped__') else None)

        # Manual timing for async correctness
        samples = []
        for _ in range(50):
            start = time.perf_counter()
            await _run()
            samples.append((time.perf_counter() - start) * 1000)
        assert len(samples) == 50
        p50 = sorted(samples)[25]
        assert p50 < 200  # should be under 200ms with mock

    async def test_recall_skipped_meta_query(self, benchmark):
        """Meta-query → intent gate skips recall entirely."""
        service = _make_recall_service()

        samples = []
        for _ in range(100):
            start = time.perf_counter()
            await service.recall_for_prompt(
                project_slug="test-project",
                query="what memories do you have about this",
            )
            samples.append((time.perf_counter() - start) * 1000)
        p50 = sorted(samples)[50]
        assert p50 < 10  # gate skip should be near-instant

    async def test_recall_disabled(self, benchmark):
        """Recall disabled → early return."""
        service = _make_recall_service(recall_enabled=False)

        samples = []
        for _ in range(100):
            start = time.perf_counter()
            await service.recall_for_prompt(
                project_slug="test-project",
                query="how does the backend authentication work",
            )
            samples.append((time.perf_counter() - start) * 1000)
        p50 = sorted(samples)[50]
        assert p50 < 10

    async def test_recall_no_embedding(self, benchmark):
        """Recall without embedding adapter → skip query embedding."""
        service = _make_recall_service(embedding_adapter=None, embeddings_enabled=False)

        samples = []
        for _ in range(50):
            start = time.perf_counter()
            await service.recall_for_prompt(
                project_slug="test-project",
                query="how does the tool orchestrator handle parallel execution",
            )
            samples.append((time.perf_counter() - start) * 1000)
        p50 = sorted(samples)[25]
        assert p50 < 50  # no embedding → fast


@pytest.mark.stress
class TestRecallHelpersBenchmarks:

    def test_should_recall_code_anchor(self, benchmark):
        """Query with backtick code → always recalls."""
        result = benchmark(
            lambda: _should_recall_operational_memory("how does `ToolOrchestrator._partition` work")
        )
        assert result is True

    def test_should_recall_operational_term(self, benchmark):
        """Query with operational anchor term → recalls."""
        result = benchmark(
            lambda: _should_recall_operational_memory("explain the backend authentication flow")
        )
        assert result is True

    def test_should_not_recall_meta(self, benchmark):
        """Meta memory query → skips recall."""
        result = benchmark(
            lambda: _should_recall_operational_memory("what memories do you have")
        )
        assert result is False

    def test_normalize_query_ascii(self, benchmark):
        """Normalize query with accented chars."""
        result = benchmark(lambda: _normalize_query("como funciona a autenticação do backend"))
        assert "autenticacao" in result

    def test_query_tokens_complex(self, benchmark):
        """Extract tokens from a complex query."""
        result = benchmark(
            lambda: _query_tokens("how does tool_orchestrator._partition handle mixed safety")
        )
        assert isinstance(result, set)
