"""Chunk-based recall operations for operational memory."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import EmbeddingVector
from personagent.infrastructure.persistence.models import MemoryDecisionORM
from personagent.infrastructure.persistence.operational_memory._search_helpers import (
    _vector_literal,
)
from personagent.infrastructure.persistence.operational_memory.models import (
    StoredMemoryChunk,
)
from personagent.infrastructure.persistence.operational_memory.scoring import (
    _event_type_boost,
    _lexical_score,
    _overlap_coefficient,
    _semantic_signature,
    _semantic_term_set,
    _terms,
)

from .helpers import _excerpt


async def _ann_candidate_chunk_ids(
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


def _score_candidates(
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
