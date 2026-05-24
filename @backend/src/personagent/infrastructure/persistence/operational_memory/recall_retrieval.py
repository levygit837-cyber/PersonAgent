"""Hybrid recall, scoring, and ranking pipeline for operational memory.

Extracted from ``OperationalMemoryRepository`` (Slice 4).
Owns the read path: semantic/lexical/recent search, hybrid scoring,
deduplication, and structured-item/chunk-to-finding conversion.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from personagent.domain.memory.models.operational import (
    MemoryContextBudget,
    OperationalMemoryFilter,
    RecallFinding,
    StructuredMemoryItem,
    StructuredMemoryPackage,
    StructuredMemoryType,
)
from personagent.domain.memory.services.operational_memory import (
    EmbeddingVector,
    OperationalMemoryFormatter,
)
from personagent.infrastructure.persistence.models import (
    MemoryDecisionORM,
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
    StoredMemoryChunk,
    StoredStructuredMemoryItem,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    ScoringRanker,
    _event_type_boost,
    _lexical_score,
    _low_trust_memory_requested,
    _overlap_coefficient,
    _semantic_signature,
    _semantic_term_set,
    _terms,
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
    ) -> list[UUID]:
        if not query_embedding or len(query_embedding) != 4096:
            return []
        try:
            result = await session.execute(
                text(
                    """
                    SELECT me.chunk_id
                    FROM memory_embeddings me
                    WHERE me.project_slug = :project_slug
                      AND me.dimensions = 4096
                    ORDER BY ((subvector(me.embedding, 1, 2000))::vector(2000))
                      <=> ((subvector(CAST(:query_vector AS vector(4096)), 1, 2000))::vector(2000))
                    LIMIT :limit
                    """
                ),
                {
                    "project_slug": project_slug,
                    "query_vector": _vector_literal(query_embedding),
                    "limit": max(1, limit),
                },
            )
        except Exception:
            return []
        return [row[0] for row in result.all()]

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
        merged: dict[UUID, StoredStructuredMemoryItem] = {}
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
        candidates: list[StoredMemoryChunk],
        query_embedding: list[float] | None,
    ) -> list[StoredMemoryChunk]:
        query_terms = _terms(query)
        for candidate in candidates:
            text = " ".join(
                str(part or "")
                for part in (
                    candidate.chunk.content,
                    candidate.chunk.file_path,
                    candidate.chunk.source_type,
                    candidate.event.event_type if candidate.event else "",
                    candidate.event.tool_name if candidate.event else "",
                )
            )
            lexical = _lexical_score(query_terms, text)
            vector = EmbeddingVector.cosine(query_embedding, candidate.embedding)
            recency = 0.05
            if lexical <= 0 and vector <= 0:
                recency = 0.0
            raw_score = lexical + (vector * 2.0)
            event_type = str(candidate.event.event_type if candidate.event else candidate.chunk.source_type)
            if event_type in {"assistant_message", "user_message"}:
                candidate.score = (raw_score * 0.2) + recency
            else:
                candidate.score = raw_score + _event_type_boost(event_type) + recency
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _dedupe_and_diversify(
        self,
        candidates: list[StoredMemoryChunk],
        *,
        top_k: int,
    ) -> list[StoredMemoryChunk]:
        selected: list[StoredMemoryChunk] = []
        seen_hashes: set[str] = set()
        seen_signatures: set[str] = set()
        seen_term_sets: list[set[str]] = []

        for candidate in candidates:
            if candidate.score <= 0:
                continue
            content_hash = str(candidate.chunk.content_hash or "")
            if content_hash and content_hash in seen_hashes:
                continue
            signature = _semantic_signature(candidate.chunk.content)
            if signature and signature in seen_signatures:
                continue
            candidate_terms = _semantic_term_set(candidate.chunk.content)
            if any(
                _overlap_coefficient(candidate_terms, selected_terms) >= 0.82
                for selected_terms in seen_term_sets
            ):
                continue
            selected.append(candidate)
            if content_hash:
                seen_hashes.add(content_hash)
            if signature:
                seen_signatures.add(signature)
            if candidate_terms:
                seen_term_sets.append(candidate_terms)
            if len(selected) >= top_k:
                break
        return selected

    def _to_findings(
        self,
        candidates: list[StoredMemoryChunk],
        active_decisions: list[MemoryDecisionORM],
        *,
        query_terms: set[str] | None = None,
    ) -> list[RecallFinding]:
        findings: list[RecallFinding] = []
        decision_texts = [
            f"{row.decision} ({row.status})"
            for row in active_decisions
            if row.decision
        ]
        for candidate in candidates:
            if candidate.score <= 0:
                continue
            event = candidate.event
            path = candidate.chunk.file_path
            event_type = event.event_type if event else candidate.chunk.source_type
            tool_name = f" via {event.tool_name}" if event and event.tool_name else ""
            path_text = f" em {path}" if path else ""
            excerpt = _excerpt(candidate.chunk.content, query_terms=query_terms)
            finding = f"Evento operacional `{event_type}`{tool_name}{path_text}: {excerpt}"
            cautions: list[str] = []
            if event and event.error:
                cautions.append(event.error[:300])
            if event_type in {"assistant_message", "user_message"}:
                cautions.append(
                    "Conversation text is unverified; prefer tool, diff, file, and decision evidence."
                )
            findings.append(
                RecallFinding(
                    finding=finding,
                    source_ids=[str(candidate.chunk.id)],
                    evidence=[excerpt],
                    paths=[path] if path else [],
                    decisions=decision_texts[:4],
                    cautions=cautions,
                    score=round(candidate.score, 4),
                    event_types=[str(event_type)],
                    created_at=candidate.chunk.created_at,
                )
            )
        return findings


# ---------------------------------------------------------------------------
# Module-level helpers (moved from operational_memory_repository.py)
# ---------------------------------------------------------------------------


def _discarded_candidate_payload(
    candidates: list[StoredStructuredMemoryItem],
    selected_ids: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    discarded = []
    for candidate in candidates:
        source_ids = candidate.source_ids or [str(candidate.id)]
        if any(source_id in selected_ids for source_id in source_ids):
            continue
        discarded.append(
            {
                "id": str(candidate.id),
                "source_ids": source_ids[:3],
                "score": round(candidate.score, 4),
                "type": candidate.item_type,
                "status": candidate.status,
                "trust_level": candidate.trust_level,
                "reasons": candidate.ranking_reasons or [],
                "summary": _excerpt(candidate.summary, limit=180),
            }
        )
        if len(discarded) >= limit:
            break
    return discarded


def _included_reason_payload(items: list[StructuredMemoryItem]) -> list[dict[str, Any]]:
    return [
        {
            "source_ids": item.source_ids[:3],
            "score": item.score,
            "type": item.type.value,
            "status": item.status,
            "trust_level": item.trust_level,
            "reasons": item.metadata.get("ranking_reasons") or [],
        }
        for item in items
    ]


def _query_intent(query: str) -> str:
    terms = _terms(query)
    if _low_trust_memory_requested(terms):
        return "conversation_or_prior_interaction"
    if any("/" in token or "." in token for token in query.split()):
        return "file_or_path"
    if {"erro", "error", "falha", "failed"} & terms:
        return "error_resolution"
    if {"comando", "command", "test", "teste"} & terms:
        return "command_or_test"
    return "specific"


def _is_contextually_relevant(query: str, candidate: StoredMemoryChunk) -> bool:
    event_type = str(candidate.event.event_type if candidate.event else candidate.chunk.source_type)
    query_terms = _relevance_terms(query)
    if not query_terms:
        return False
    if event_type in {"assistant_message", "user_message"} and not _conversation_event_requested(query_terms):
        return False

    candidate_text = " ".join(
        str(part or "")
        for part in (
            candidate.chunk.content,
            candidate.chunk.file_path,
            candidate.chunk.source_type,
            event_type,
            candidate.event.tool_name if candidate.event else "",
        )
    )
    candidate_terms = _relevance_terms(candidate_text)
    if not _focus_requirements_satisfied(query_terms, candidate_terms):
        return False
    overlap = query_terms & candidate_terms
    if len(overlap) >= 2:
        return True

    anchor_terms = query_terms & _CONTEXT_ANCHOR_TERMS
    anchor_overlap = anchor_terms & candidate_terms
    return bool(anchor_overlap - _WEAK_SINGLE_MATCH_TERMS)


def _focus_requirements_satisfied(query_terms: set[str], candidate_terms: set[str]) -> bool:
    for focus, required_terms in _FOCUS_REQUIREMENTS.items():
        if focus in query_terms and not (candidate_terms & required_terms):
            return False
    return True


def _conversation_event_requested(query_terms: set[str]) -> bool:
    return bool(
        query_terms
        & {
            "assistant",
            "conversa",
            "mensagem",
            "pergunta",
            "resposta",
            "usuario",
            "user",
        }
    )


def _relevance_terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", ascii_text.lower()):
        if len(token) < 3 or token in _RELEVANCE_STOPWORDS:
            continue
        terms.add(_canonical_relevance_term(token))
    return terms


def _canonical_relevance_term(token: str) -> str:
    return _RELEVANCE_CANONICAL_TERMS.get(token, token)


def _excerpt(text: str, limit: int = 420, query_terms: set[str] | None = None) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    if query_terms:
        lower = compact.lower()
        best: tuple[int, int, int] | None = None
        for term in query_terms:
            if not term:
                continue
            position = lower.find(term)
            while position >= 0:
                start = max(0, position - max(40, limit // 5))
                end = min(len(compact), start + limit)
                if end - start < limit:
                    start = max(0, end - limit)
                window = lower[start:end]
                matched_terms = sum(1 for candidate in query_terms if candidate in window)
                identifier_bonus = 1 if _has_identifier(compact[start:end]) else 0
                score = matched_terms + identifier_bonus
                candidate_window = (score, position, start)
                if best is None or candidate_window > best:
                    best = candidate_window
                position = lower.find(term, position + len(term))
        if best is not None:
            start = best[2]
            end = min(len(compact), start + limit)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(compact) else ""
            return f"{prefix}{compact[start:end]}{suffix}"
    head_size = max(120, limit // 2 - 3)
    tail_size = max(120, limit - head_size - 5)
    return f"{compact[:head_size]} ... {compact[-tail_size:]}"


def _has_identifier(text: str) -> bool:
    for token in text.replace("`", " ").split():
        stripped = token.strip(".,:;()[]{}'\"")
        if "_" in stripped and stripped.upper() == stripped and len(stripped) >= 6:
            return True
    return False


# ---------------------------------------------------------------------------
# Relevance constants (moved from operational_memory_repository.py)
# ---------------------------------------------------------------------------

_RELEVANCE_STOPWORDS = {
    "a", "as", "com", "como", "de", "da", "das", "do", "dos",
    "e", "em", "foi", "na", "no", "nos", "o", "os",
    "para", "por", "qual", "quais", "que",
    "the", "to", "was", "what", "which",
}

_RELEVANCE_CANONICAL_TERMS = {
    "arquitetura": "architecture",
    "arquiteturais": "architecture",
    "arquivo": "file",
    "arquivos": "file",
    "comando": "command",
    "comandos": "command",
    "decisao": "decision",
    "decisoes": "decision",
    "decisions": "decision",
    "dependencia": "dependency",
    "dependencias": "dependency",
    "duplicados": "duplicate",
    "duplicar": "duplicate",
    "erros": "error",
    "ferramenta": "tool",
    "ferramentas": "tool",
    "incidente": "incident",
    "incidentes": "incident",
    "marcador": "marker",
    "marcadores": "marker",
    "retries": "retry",
    "solucao": "resolution",
    "solucoes": "resolution",
    "usuario": "user",
}

_CONTEXT_ANCHOR_TERMS = {
    "architecture", "api", "auth", "backpressure", "benchmark", "budget",
    "canary", "chunk", "command", "conversation", "cookie",
    "decision", "dependency", "diff", "duplicate",
    "error", "executor",
    "fetch", "file", "fingerprint", "frontend",
    "header", "idempotency", "incident",
    "jwt",
    "marker",
    "planner",
    "registry", "retry",
    "tenant", "timeout", "tool",
    "workspace",
}

_WEAK_SINGLE_MATCH_TERMS = {"benchmark", "incident"}

_FOCUS_REQUIREMENTS = {
    "decision": {"auth", "cookie", "decision", "executor", "jwt", "planner"},
    "file": {"api", "backend", "file", "frontend", "path", "src"},
    "header": {"fingerprint", "header", "idempotency"},
    "marker": {"boundary", "canary", "marker", "tenant"},
}
