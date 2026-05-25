"""Tests for :class:`OperationalMemoryRecall`.

Pins the operational-memory recall surface that was previously
three methods on :class:`OperationalMemoryService`.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from personagent.application.services.operational_memory.recall import (
    OperationalMemoryRecall,
    _empty_structured_package,
    _is_memory_capability_query,
    _normalize_query,
    _query_tokens,
    _should_recall_operational_memory,
)
from personagent.domain.memory.models.operational import (
    MemoryContextBudget,
    RecallFinding,
    StructuredMemoryPackage,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RedactorStub:
    def redact_text(self, text: str) -> str:
        return text


class _EmbeddingAdapterStub:
    def __init__(self, vectors: list[list[float]] | None = None, exc: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._vectors = vectors
        self._exc = exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self._exc is not None:
            raise self._exc
        return self._vectors or [[0.1] * 10] * len(texts)

    async def health_check(self) -> dict[str, Any]:
        return {"status": "ok"}


class _RepositoryStub:
    def __init__(
        self,
        package: StructuredMemoryPackage | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.record_recall_skip_calls: list[dict[str, Any]] = []
        self.recall_structured_package_calls: list[dict[str, Any]] = []
        self._package = package or _empty_structured_package()
        self._exc = exc

    async def record_recall_skip(self, **kwargs: Any) -> None:
        self.record_recall_skip_calls.append(kwargs)

    async def recall_structured_package(self, **kwargs: Any) -> StructuredMemoryPackage:
        self.recall_structured_package_calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._package


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _recall(
    *,
    repository: _RepositoryStub | None = None,
    embedding_adapter: _EmbeddingAdapterStub | None = None,
    embeddings_enabled: bool = True,
    recall_enabled: bool = True,
    recall_top_k: int = 6,
    context_budget_tokens: int | None = 1_000,
    hot_cache: dict[str, deque[RecallFinding]] | None = None,
) -> OperationalMemoryRecall:
    return OperationalMemoryRecall(
        repository=repository or _RepositoryStub(),
        redactor=_RedactorStub(),
        embedding_adapter=embedding_adapter,
        embeddings_enabled=embeddings_enabled,
        recall_enabled=recall_enabled,
        recall_top_k=recall_top_k,
        context_budget_tokens=context_budget_tokens,
        semantic_candidate_limit=80,
        recent_candidate_limit=40,
        hot_cache=hot_cache or {},
    )


# ---------------------------------------------------------------------------
# recall_package_for_prompt — recall_enabled=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_package_disabled_records_skip_and_returns_empty() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo, recall_enabled=False)

    package = await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert package == _empty_structured_package()
    assert len(repo.record_recall_skip_calls) == 1
    assert repo.record_recall_skip_calls[0]["reason"] == "recall_disabled"
    assert repo.record_recall_skip_calls[0]["project_slug"] == "acme"


# ---------------------------------------------------------------------------
# recall_package_for_prompt — intent gate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_package_intent_gate_skips_generic_query() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo, recall_enabled=True)

    package = await recall.recall_package_for_prompt(
        project_slug="acme", query="quais memorias voce tem acesso?"
    )

    assert package == _empty_structured_package()
    assert len(repo.record_recall_skip_calls) == 1
    assert repo.record_recall_skip_calls[0]["reason"] == "query_intent_gate"
    assert repo.recall_structured_package_calls == []


@pytest.mark.anyio
async def test_recall_package_allows_operational_query() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo, recall_enabled=True)

    await recall.recall_package_for_prompt(
        project_slug="acme", query="Qual header foi escolhido para evitar duplicar incidentes?"
    )

    assert len(repo.record_recall_skip_calls) == 0
    assert len(repo.recall_structured_package_calls) == 1


# ---------------------------------------------------------------------------
# recall_package_for_prompt — embedding behaviour
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_package_embeds_query_when_enabled() -> None:
    adapter = _EmbeddingAdapterStub(vectors=[[0.5] * 10])
    repo = _RepositoryStub()
    recall = _recall(repository=repo, embedding_adapter=adapter, embeddings_enabled=True)

    await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert len(adapter.calls) == 1
    assert adapter.calls[0] == ["retry budget"]
    assert repo.recall_structured_package_calls[0]["query_embedding"] == [0.5] * 10


@pytest.mark.anyio
async def test_recall_package_omits_embedding_when_disabled() -> None:
    adapter = _EmbeddingAdapterStub()
    repo = _RepositoryStub()
    recall = _recall(repository=repo, embedding_adapter=adapter, embeddings_enabled=False)

    await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert adapter.calls == []
    assert repo.recall_structured_package_calls[0]["query_embedding"] is None


@pytest.mark.anyio
async def test_recall_package_omits_embedding_when_adapter_is_none() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo, embedding_adapter=None, embeddings_enabled=True)

    await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert repo.recall_structured_package_calls[0]["query_embedding"] is None


# ---------------------------------------------------------------------------
# recall_package_for_prompt — structured package invocation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_package_passes_correct_filters() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo)

    await recall.recall_package_for_prompt(
        project_slug="acme",
        query="retry budget",
        conversation_id="conv-1",
        current_conversation_id="conv-2",
        session_id="sess-1",
        workspace_root="/repo",
        source_types=["decision"],
        file_paths=["src/app.py"],
        created_after="2024-01-01",
        created_before="2024-12-31",
        latest_only=True,
        active_only=False,
        include_statuses=["active"],
    )

    filters = repo.recall_structured_package_calls[0]["filters"]
    assert filters["conversation_id"] == "conv-1"
    assert filters["current_conversation_id"] == "conv-2"
    assert filters["session_id"] == "sess-1"
    assert filters["workspace_root"] == "/repo"
    assert filters["source_types"] == ["decision"]
    assert filters["file_paths"] == ["src/app.py"]
    assert filters["created_after"] == "2024-01-01"
    assert filters["created_before"] == "2024-12-31"
    assert filters["latest_only"] is True
    assert filters["active_only"] is False
    assert filters["statuses"] == ["active"]
    assert filters["semantic_candidate_limit"] == 80
    assert filters["recent_candidate_limit"] == 40


@pytest.mark.anyio
async def test_recall_package_uses_default_top_k_and_budget() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo, recall_top_k=6, context_budget_tokens=1_000)

    await recall.recall_package_for_prompt(
        project_slug="acme", query="retry budget", context_window_tokens=128_000
    )

    call = repo.recall_structured_package_calls[0]
    assert call["top_k"] == 6
    budget = call["budget"]
    assert isinstance(budget, MemoryContextBudget)


@pytest.mark.anyio
async def test_recall_package_uses_custom_top_k_and_budget_tokens() -> None:
    repo = _RepositoryStub()
    recall = _recall(repository=repo)

    await recall.recall_package_for_prompt(
        project_slug="acme",
        query="retry budget",
        top_k=10,
        budget_tokens=500,
        context_window_tokens=64_000,
    )

    call = repo.recall_structured_package_calls[0]
    assert call["top_k"] == 10
    budget = call["budget"]
    assert isinstance(budget, MemoryContextBudget)


@pytest.mark.anyio
async def test_recall_package_returns_empty_on_repository_exception() -> None:
    repo = _RepositoryStub(exc=RuntimeError("db down"))
    recall = _recall(repository=repo)

    package = await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert package == _empty_structured_package()


@pytest.mark.anyio
async def test_recall_package_returns_repository_package() -> None:
    expected = StructuredMemoryPackage(
        formatted="# Memory",
        items=[],
        filters_applied={},
        budget_used=10,
        budget_tokens=100,
        omitted_count=0,
        latency_ms=5,
    )
    repo = _RepositoryStub(package=expected)
    recall = _recall(repository=repo)

    package = await recall.recall_package_for_prompt(project_slug="acme", query="retry budget")

    assert package is expected


# ---------------------------------------------------------------------------
# recall_for_prompt
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_recall_for_prompt_returns_formatted_string() -> None:
    expected = StructuredMemoryPackage(
        formatted="# Relevant Execution Memory",
        items=[],
        filters_applied={},
        budget_used=0,
        budget_tokens=0,
        omitted_count=0,
        latency_ms=0,
    )
    repo = _RepositoryStub(package=expected)
    recall = _recall(repository=repo)

    result = await recall.recall_for_prompt(project_slug="acme", query="retry budget")

    assert result == "# Relevant Execution Memory"


# ---------------------------------------------------------------------------
# _embed_query
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_query_returns_vector_when_successful() -> None:
    adapter = _EmbeddingAdapterStub(vectors=[[0.2] * 10])
    recall = _recall(embedding_adapter=adapter, embeddings_enabled=True)

    vector = await recall._embed_query("retry budget")

    assert vector == [0.2] * 10


@pytest.mark.anyio
async def test_embed_query_returns_none_when_adapter_raises() -> None:
    adapter = _EmbeddingAdapterStub(exc=RuntimeError("timeout"))
    recall = _recall(embedding_adapter=adapter, embeddings_enabled=True)

    vector = await recall._embed_query("retry budget")

    assert vector is None


@pytest.mark.anyio
async def test_embed_query_returns_none_when_embeddings_disabled() -> None:
    adapter = _EmbeddingAdapterStub()
    recall = _recall(embedding_adapter=adapter, embeddings_enabled=False)

    vector = await recall._embed_query("retry budget")

    assert vector is None
    assert adapter.calls == []


# ---------------------------------------------------------------------------
# _merge_hot_findings
# ---------------------------------------------------------------------------


def test_merge_hot_findings_returns_unchanged_when_cache_empty() -> None:
    recall = _recall(hot_cache={})
    findings: list[RecallFinding] = []

    result = recall._merge_hot_findings("acme", "retry budget", findings, top_k=6)

    assert result == []


def test_merge_hot_findings_appends_matching_findings() -> None:
    hot = deque(
        [
            RecallFinding(
                finding="Evento recente `tool_result`: added retry header",
                source_ids=["chunk-1"],
                evidence=["added retry header"],
                paths=["src/app.py"],
                score=0.25,
                event_types=["tool_result"],
            ),
        ]
    )
    recall = _recall(hot_cache={"acme": hot})
    findings: list[RecallFinding] = []

    result = recall._merge_hot_findings("acme", "retry header", findings, top_k=6)

    assert len(result) == 1
    assert result[0].source_ids == ["chunk-1"]


def test_merge_hot_findings_skips_non_matching_terms() -> None:
    hot = deque(
        [
            RecallFinding(
                finding="Evento recente `tool_result`: unrelated change",
                source_ids=["chunk-1"],
                evidence=["unrelated change"],
                paths=["src/other.py"],
                score=0.25,
                event_types=["tool_result"],
            ),
        ]
    )
    recall = _recall(hot_cache={"acme": hot})
    findings: list[RecallFinding] = []

    result = recall._merge_hot_findings("acme", "retry budget", findings, top_k=6)

    assert result == []


def test_merge_hot_findings_skips_already_seen_source_ids() -> None:
    hot = deque(
        [
            RecallFinding(
                finding="Evento recente `tool_result`: added retry header",
                source_ids=["chunk-1"],
                evidence=["added retry header"],
                paths=["src/app.py"],
                score=0.25,
                event_types=["tool_result"],
            ),
        ]
    )
    recall = _recall(hot_cache={"acme": hot})
    existing = RecallFinding(
        finding="existing",
        source_ids=["chunk-1"],
        evidence=["existing"],
        paths=[],
        score=0.9,
        event_types=["fact"],
    )

    result = recall._merge_hot_findings("acme", "retry header", [existing], top_k=6)

    assert len(result) == 1
    assert result[0] is existing


def test_merge_hot_findings_respects_top_k() -> None:
    hot = deque(
        [
            RecallFinding(
                finding=f"Evento recente `tool_result`: finding {i}",
                source_ids=[f"chunk-{i}"],
                evidence=[f"finding {i}"],
                paths=[],
                score=0.25,
                event_types=["tool_result"],
            )
            for i in range(10)
        ]
    )
    recall = _recall(hot_cache={"acme": hot})
    findings: list[RecallFinding] = []

    result = recall._merge_hot_findings("acme", "finding", findings, top_k=3)

    assert len(result) == 3


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_empty_structured_package_has_zero_values() -> None:
    pkg = _empty_structured_package()
    assert pkg.formatted == ""
    assert pkg.items == []
    assert pkg.budget_used == 0
    assert pkg.omitted_count == 0


def test_should_recall_operational_memory_allows_code_anchors() -> None:
    assert _should_recall_operational_memory("What about src/app.py?") is True
    assert _should_recall_operational_memory("Check `docker-compose.yml`") is True


def test_should_recall_operational_memory_rejects_capability_queries() -> None:
    assert _should_recall_operational_memory("quais memorias voce tem?") is False
    assert _should_recall_operational_memory("what types of memory exist?") is False


def test_should_recall_operational_memory_allows_specific_queries() -> None:
    assert _should_recall_operational_memory("O que lembra sobre retry budget?") is True
    assert _should_recall_operational_memory("Como evitar duplicar incidentes?") is True


def test_normalize_query_strips_diacritics_and_lowercases() -> None:
    assert _normalize_query("São Paulo") == "sao paulo"
    assert _normalize_query("  Hello World  ") == "hello world"


def test_query_tokens_extracts_unique_terms() -> None:
    tokens = _query_tokens("hello world, hello!")
    assert tokens == {"hello", "world"}


def test_is_memory_capability_query_detects_generic_asks() -> None:
    assert _is_memory_capability_query({"memoria", "acesso", "voce"}) is True
    assert _is_memory_capability_query({"memoria", "retry"}) is False
