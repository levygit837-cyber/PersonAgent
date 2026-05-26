"""Hybrid recall, scoring, and ranking pipeline for operational memory.

Extracted from ``OperationalMemoryRepository`` (Slice 4).
Owns the read path: semantic/lexical/recent search, hybrid scoring,
deduplication, and structured-item/chunk-to-finding conversion.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from personagent.domain.memory.models.operational import (
    MemoryContextBudget,
    OperationalMemoryFilter,
    RecallFinding,
    StructuredMemoryPackage,
    StructuredMemoryType,
)
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryFormatter,
)
from personagent.infrastructure.persistence.models import (
    MemoryRecallLogORM,
)
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _lexical_query_text,
    _rows_to_structured_candidates,
    _structured_where_clause,
    _uuid_or_none,
    _vector_literal,
)
from personagent.infrastructure.persistence.operational_memory.models import (
    StoredStructuredMemoryItem,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    ScoringRanker,
)

from .chunk_recall import (
    _ann_candidate_chunk_ids,
    _dedupe_and_diversify,
    _score_candidates,
    _to_findings,
)
from .helpers import (
    _discarded_candidate_payload,
    _included_reason_payload,
    _query_intent,
)


class RecallRetrievalPipeline:
    """Read-path pipeline: hybrid search, scoring, dedup, and formatting."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._scoring = ScoringRanker()

    async def recall(
        self,
        *,
        project_slug: str,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 6,
        filters: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> list[RecallFinding]:
        package = await self.recall_structured_package(
            project_slug=project_slug,
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters,
            provider=provider,
            model=model,
        )
        return [
            RecallFinding(
                finding=item.summary,
                source_ids=item.source_ids,
                evidence=item.evidence,
                paths=item.paths,
                decisions=[item.summary] if item.type == StructuredMemoryType.DECISION else [],
                cautions=[],
                score=item.score,
                event_types=item.event_types,
                created_at=item.created_at,
            )
            for item in package.items
        ]

    async def recall_structured_package(
        self,
        *,
        project_slug: str,
        query: str,
        query_embedding: list[float] | None = None,
        top_k: int = 6,
        filters: dict[str, Any] | None = None,
        budget: MemoryContextBudget | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> StructuredMemoryPackage:
        started = time.perf_counter()
        memory_filter = OperationalMemoryFilter.from_mapping(filters)
        budget = budget or MemoryContextBudget.for_context_window(262_144)
        async with self._session_factory() as session:
            semantic = await self._structured_semantic_candidates(
                session=session,
                project_slug=project_slug,
                query_embedding=query_embedding,
                filters=memory_filter,
            )
            lexical = await self._structured_lexical_candidates(
                session=session,
                project_slug=project_slug,
                query=query,
                filters=memory_filter,
            )
            recent = await self._structured_recent_candidates(
                session=session,
                project_slug=project_slug,
                filters=memory_filter,
            )
            candidates = self._bounded_structured_candidates(
                semantic,
                lexical,
                recent,
                limit=max(25, min(50, top_k * 8)),
            )
            scored = self._scoring.score(query, candidates, filters=memory_filter)
            diversified = self._scoring.dedupe(scored, top_k=max(1, top_k * 4))
            items = self._scoring.to_items(diversified)
            formatted, budget_used, omitted_count, selected = (
                OperationalMemoryFormatter.format_structured_items(items, budget=budget)
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            selected_ids = {source_id for item in selected for source_id in item.source_ids}
            discarded = _discarded_candidate_payload(scored, selected_ids, limit=20)
            included_reasons = _included_reason_payload(selected)
            ranking_breakdown = {
                "semantic_candidates": len(semantic),
                "lexical_candidates": len(lexical),
                "recent_candidates": len(recent),
                "merged_candidates": len(candidates),
                "scored_candidates": len(scored),
                "selected_items": len(selected),
            }
            token_usage = {
                "budget_tokens": int(budget.total_tokens),
                "budget_used": int(budget_used),
                "omitted_count": int(omitted_count),
            }
            session.add(
                MemoryRecallLogORM(
                    project_slug=project_slug,
                    workspace_root=memory_filter.workspace_root,
                    conversation_id=_uuid_or_none(memory_filter.current_conversation_id),
                    recall_scope="conversation" if memory_filter.conversation_id else "workspace",
                    query_intent=_query_intent(query),
                    query=query,
                    filters=memory_filter.to_log_dict(),
                    result_ids=[source_id for item in selected for source_id in item.source_ids],
                    scores={
                        source_id: item.score
                        for item in selected
                        for source_id in item.source_ids[:1]
                    },
                    candidate_count=len(scored),
                    selected_count=len(selected),
                    discarded_candidates=discarded,
                    included_reasons=included_reasons,
                    ranking_breakdown=ranking_breakdown,
                    token_usage=token_usage,
                    budget_tokens=budget.total_tokens,
                    budget_used=budget_used,
                    latency_ms=latency_ms,
                    provider=provider,
                    model=model,
                )
            )
            await session.commit()
        return StructuredMemoryPackage(
            formatted=formatted,
            items=selected,
            filters_applied=memory_filter.to_log_dict(),
            budget_used=budget_used,
            budget_tokens=budget.total_tokens,
            omitted_count=omitted_count,
            latency_ms=latency_ms,
            recall_scope="conversation" if memory_filter.conversation_id else "workspace",
            query_intent=_query_intent(query),
            candidate_count=len(scored),
            discarded_candidates=discarded,
            included_reasons=included_reasons,
            ranking_breakdown=ranking_breakdown,
            token_usage=token_usage,
        )

    async def _structured_semantic_candidates(
        self,
        *,
        session: Any,
        project_slug: str,
        query_embedding: list[float] | None,
        filters: OperationalMemoryFilter,
    ) -> list[StoredStructuredMemoryItem]:
        if not query_embedding or len(query_embedding) != 4096 or filters.semantic_candidate_limit <= 0:
            return []
        params: dict[str, Any] = {
            "project_slug": project_slug,
            "query_vector": _vector_literal(query_embedding),
            "limit": filters.semantic_candidate_limit,
        }
        where = _structured_where_clause("smi", filters, params)
        try:
            result = await session.execute(
                text(
                    f"""
                    SELECT
                        smi.id,
                        smi.project_slug,
                        smi.item_type,
                        smi.summary,
                        smi.evidence,
                        smi.paths,
                        smi.source_ids,
                        smi.status,
                        smi.source_type,
                        smi.source_chunk_id,
                        smi.primary_path,
                        smi.conversation_id,
                        smi.workspace_root,
                        smi.trust_level,
                        smi.importance,
                        smi.created_at,
                        ((subvector(me.embedding, 1, 2000))::vector(2000))
                          <=> ((subvector(CAST(:query_vector AS vector(4096)), 1, 2000))::vector(2000))
                          AS distance,
                        0::double precision AS lexical_rank
                    FROM memory_structured_items smi
                    JOIN memory_embeddings me ON me.chunk_id = smi.source_chunk_id
                    WHERE smi.project_slug = :project_slug
                      AND me.dimensions = 4096
                      {where}
                    ORDER BY distance ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        except Exception:
            return []
        return _rows_to_structured_candidates(result.all())

    async def _structured_lexical_candidates(
        self,
        *,
        session: Any,
        project_slug: str,
        query: str,
        filters: OperationalMemoryFilter,
    ) -> list[StoredStructuredMemoryItem]:
        lexical_query = _lexical_query_text(query)
        if not lexical_query:
            return []
        params: dict[str, Any] = {
            "project_slug": project_slug,
            "lexical_query": lexical_query,
            "limit": filters.semantic_candidate_limit,
        }
        where = _structured_where_clause("smi", filters, params)
        try:
            result = await session.execute(
                text(
                    f"""
                    WITH q AS (SELECT plainto_tsquery('simple', :lexical_query) AS query)
                    SELECT
                        smi.id,
                        smi.project_slug,
                        smi.item_type,
                        smi.summary,
                        smi.evidence,
                        smi.paths,
                        smi.source_ids,
                        smi.status,
                        smi.source_type,
                        smi.source_chunk_id,
                        smi.primary_path,
                        smi.conversation_id,
                        smi.workspace_root,
                        smi.trust_level,
                        smi.importance,
                        smi.created_at,
                        NULL::double precision AS distance,
                        ts_rank_cd(smi.search_vector, q.query)::double precision AS lexical_rank
                    FROM memory_structured_items smi, q
                    WHERE smi.project_slug = :project_slug
                      AND smi.search_vector @@ q.query
                      {where}
                    ORDER BY lexical_rank DESC, smi.created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        except Exception:
            return []
        return _rows_to_structured_candidates(result.all())

    async def _structured_recent_candidates(
        self,
        *,
        session: Any,
        project_slug: str,
        filters: OperationalMemoryFilter,
    ) -> list[StoredStructuredMemoryItem]:
        if filters.recent_candidate_limit <= 0:
            return []
        params: dict[str, Any] = {
            "project_slug": project_slug,
            "limit": filters.recent_candidate_limit,
        }
        where = _structured_where_clause("smi", filters, params)
        result = await session.execute(
            text(
                f"""
                SELECT
                    smi.id,
                    smi.project_slug,
                    smi.item_type,
                    smi.summary,
                    smi.evidence,
                    smi.paths,
                    smi.source_ids,
                    smi.status,
                    smi.source_type,
                    smi.source_chunk_id,
                    smi.primary_path,
                    smi.conversation_id,
                    smi.workspace_root,
                    smi.trust_level,
                    smi.importance,
                    smi.created_at,
                    NULL::double precision AS distance,
                    0::double precision AS lexical_rank
                FROM memory_structured_items smi
                WHERE smi.project_slug = :project_slug
                  {where}
                ORDER BY smi.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return _rows_to_structured_candidates(result.all())

    async def _ann_candidate_chunk_ids(
        self,
        *,
        session: Any,
        project_slug: str,
        query_embedding: list[float] | None,
        limit: int,
    ) -> list[Any]:
        return await _ann_candidate_chunk_ids(
            session=session,
            project_slug=project_slug,
            query_embedding=query_embedding,
            limit=limit,
        )

    def _bounded_structured_candidates(
        self,
        semantic: list[StoredStructuredMemoryItem],
        lexical: list[StoredStructuredMemoryItem],
        recent: list[StoredStructuredMemoryItem],
        *,
        limit: int,
    ) -> list[StoredStructuredMemoryItem]:
        if not semantic and not lexical:
            return self._merge_structured_candidates(recent[:limit])
        semantic_quota = max(0, int(limit * 0.45))
        lexical_quota = max(0, int(limit * 0.40))
        recent_quota = max(0, limit - semantic_quota - lexical_quota)
        return self._merge_structured_candidates(
            [
                *semantic[:semantic_quota],
                *lexical[:lexical_quota],
                *recent[:recent_quota],
            ]
        )

    def _merge_structured_candidates(
        self,
        candidates: list[StoredStructuredMemoryItem],
    ) -> list[StoredStructuredMemoryItem]:
        merged: dict[Any, StoredStructuredMemoryItem] = {}
        for candidate in candidates:
            existing = merged.get(candidate.id)
            if existing is None:
                merged[candidate.id] = candidate
                continue
            if existing.distance is None or (
                candidate.distance is not None and candidate.distance < existing.distance
            ):
                existing.distance = candidate.distance
            if candidate.lexical_rank > existing.lexical_rank:
                existing.lexical_rank = candidate.lexical_rank
        return list(merged.values())

    def _score_candidates(
        self,
        query: str,
        candidates: list[Any],
        query_embedding: list[float] | None,
    ) -> list[Any]:
        return _score_candidates(query, candidates, query_embedding)

    def _dedupe_and_diversify(
        self,
        candidates: list[Any],
        *,
        top_k: int,
    ) -> list[Any]:
        return _dedupe_and_diversify(candidates, top_k=top_k)

    def _to_findings(
        self,
        candidates: list[Any],
        active_decisions: list[Any],
        *,
        query_terms: set[str] | None = None,
    ) -> list[RecallFinding]:
        return _to_findings(candidates, active_decisions, query_terms=query_terms)
