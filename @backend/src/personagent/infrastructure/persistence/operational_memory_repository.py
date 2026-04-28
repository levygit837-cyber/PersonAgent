"""PostgreSQL-backed repository for operational RAG memory."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from personagent.domain.memory.models.operational import (
    DecisionMemory,
    EmbeddingStatus,
    MemoryChunk,
    MemoryContextBudget,
    MemoryEvent,
    OperationalMemoryFilter,
    RecallFinding,
    StructuredMemoryItem,
    StructuredMemoryPackage,
    StructuredMemoryType,
)
from personagent.domain.memory.services.operational_memory import (
    EmbeddingVector,
    OperationalMemoryFormatter,
    stable_hash,
)
from personagent.infrastructure.persistence.models import (
    MemoryDecisionORM,
    MemoryEmbeddingORM,
    MemoryRecallLogORM,
    OperationalMemoryChunkORM,
    OperationalMemoryEventORM,
    StructuredMemoryItemORM,
)


@dataclass(slots=True)
class StoredMemoryChunk:
    """Chunk plus optional vector returned by recall."""

    chunk: OperationalMemoryChunkORM
    event: OperationalMemoryEventORM | None
    embedding: list[float] | None
    score: float = 0.0


@dataclass(slots=True)
class StoredStructuredMemoryItem:
    """Structured item returned by DB-first recall."""

    id: UUID
    project_slug: str
    item_type: str
    summary: str
    evidence: list[str]
    paths: list[str]
    source_ids: list[str]
    event_types: list[str]
    status: str
    source_type: str
    source_chunk_id: UUID | None
    primary_path: str | None
    created_at: Any
    distance: float | None = None
    score: float = 0.0


_RELEVANCE_STOPWORDS = {
    "a",
    "as",
    "com",
    "como",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "foi",
    "na",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "qual",
    "quais",
    "que",
    "the",
    "to",
    "was",
    "what",
    "which",
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
    "architecture",
    "api",
    "auth",
    "backpressure",
    "benchmark",
    "budget",
    "canary",
    "chunk",
    "command",
    "conversation",
    "cookie",
    "decision",
    "dependency",
    "diff",
    "duplicate",
    "error",
    "executor",
    "fetch",
    "file",
    "fingerprint",
    "frontend",
    "header",
    "idempotency",
    "incident",
    "jwt",
    "marker",
    "planner",
    "registry",
    "retry",
    "tenant",
    "timeout",
    "tool",
    "workspace",
}
_WEAK_SINGLE_MATCH_TERMS = {"benchmark", "incident"}
_FOCUS_REQUIREMENTS = {
    "decision": {"auth", "cookie", "decision", "executor", "jwt", "planner"},
    "file": {"api", "backend", "file", "frontend", "path", "src"},
    "header": {"fingerprint", "header", "idempotency"},
    "marker": {"boundary", "canary", "marker", "tenant"},
}


class OperationalMemoryRepository:
    """Persistence and lightweight hybrid recall for operational memory."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def record_event(self, event: MemoryEvent) -> MemoryEvent:
        async with self._session_factory() as session:
            row = OperationalMemoryEventORM(
                id=event.id,
                project_slug=event.project_slug,
                workspace_root=event.workspace_root,
                session_id=event.session_id,
                conversation_id=_uuid_or_none(event.conversation_id),
                agent_name=event.agent_name,
                event_type=event.event_type.value,
                task=event.task,
                tool_name=event.tool_name,
                status=event.status,
                input=event.input,
                output=event.output,
                error=event.error,
                resolution=event.resolution,
                paths=event.paths,
                metadata_=event.metadata,
                source_hash=event.source_hash,
                created_at=event.created_at,
            )
            session.add(row)
            await session.commit()
        return event

    async def record_chunks(self, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        if not chunks:
            return []
        stored: list[MemoryChunk] = []
        async with self._session_factory() as session:
            for chunk in chunks:
                existing = await session.scalar(
                    select(OperationalMemoryChunkORM).where(
                        OperationalMemoryChunkORM.project_slug == chunk.project_slug,
                        OperationalMemoryChunkORM.source_type == chunk.source_type,
                        OperationalMemoryChunkORM.content_hash == chunk.content_hash,
                    )
                )
                if existing is not None:
                    chunk.id = existing.id
                    chunk.embedding_status = EmbeddingStatus(str(existing.embedding_status))
                    stored.append(chunk)
                    continue
                row = OperationalMemoryChunkORM(
                    id=chunk.id,
                    event_id=chunk.event_id,
                    project_slug=chunk.project_slug,
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                    file_path=chunk.file_path,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=chunk.content_hash or "",
                    language=chunk.language,
                    symbols=chunk.symbols,
                    imports=chunk.imports,
                    token_count=chunk.token_count,
                    embedding_status=chunk.embedding_status.value,
                    embedding_error=chunk.embedding_error,
                    created_at=chunk.created_at,
                    updated_at=chunk.updated_at,
                )
                session.add(row)
                stored.append(chunk)
            await session.commit()
        return stored

    async def record_embeddings(
        self,
        *,
        chunks: list[MemoryChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        if not chunks or not vectors:
            return
        async with self._session_factory() as session:
            for chunk, vector in zip(chunks, vectors, strict=False):
                if not vector:
                    continue
                existing_embedding = await session.scalar(
                    select(MemoryEmbeddingORM).where(
                        MemoryEmbeddingORM.chunk_id == chunk.id,
                        MemoryEmbeddingORM.embedding_model == embedding_model,
                    )
                )
                if existing_embedding is not None:
                    row = await session.get(OperationalMemoryChunkORM, chunk.id)
                    if row is not None:
                        row.embedding_status = EmbeddingStatus.EMBEDDED.value
                        row.embedding_error = None
                    continue
                session.add(
                    MemoryEmbeddingORM(
                        chunk_id=chunk.id,
                        project_slug=chunk.project_slug,
                        embedding_model=embedding_model,
                        dimensions=len(vector),
                        embedding=vector,
                        content_hash=chunk.content_hash or "",
                    )
                )
                row = await session.get(OperationalMemoryChunkORM, chunk.id)
                if row is not None:
                    row.embedding_status = EmbeddingStatus.EMBEDDED.value
                    row.embedding_error = None
            await session.commit()

    async def record_structured_items(self, items: list[StructuredMemoryItem]) -> list[StructuredMemoryItem]:
        if not items:
            return []
        stored: list[StructuredMemoryItem] = []
        async with self._session_factory() as session:
            for item in items:
                project_slug = str(item.metadata.get("project_slug") or "").strip()
                if not project_slug:
                    continue
                source_chunk_id = _uuid_or_none((item.source_ids or [None])[0])
                content_hash = str(item.metadata.get("content_hash") or stable_hash(item.summary))
                event_type = item.event_types[0] if item.event_types else None
                source_type = str(item.metadata.get("source_type") or event_type or item.type.value)
                existing = await session.scalar(
                    select(StructuredMemoryItemORM).where(
                        StructuredMemoryItemORM.project_slug == project_slug,
                        StructuredMemoryItemORM.content_hash == content_hash,
                    )
                )
                if existing is not None:
                    continue
                primary_path = item.paths[0] if item.paths else None
                if item.metadata.get("is_latest", True) and primary_path:
                    await session.execute(
                        update(StructuredMemoryItemORM)
                        .where(
                            StructuredMemoryItemORM.project_slug == project_slug,
                            StructuredMemoryItemORM.item_type == item.type.value,
                            StructuredMemoryItemORM.primary_path == primary_path,
                        )
                        .values(is_latest=False)
                    )
                session.add(
                    StructuredMemoryItemORM(
                        project_slug=project_slug,
                        conversation_id=_uuid_or_none(item.metadata.get("conversation_id")),
                        session_id=item.metadata.get("session_id"),
                        workspace_root=item.metadata.get("workspace_root"),
                        item_type=item.type.value,
                        status=item.status,
                        source_type=source_type,
                        source_id=str(item.metadata.get("source_id") or source_chunk_id or ""),
                        source_chunk_id=source_chunk_id,
                        primary_path=primary_path,
                        summary=item.summary,
                        evidence=item.evidence,
                        paths=item.paths,
                        source_ids=item.source_ids,
                        metadata_=item.metadata,
                        content_hash=content_hash,
                        is_latest=bool(item.metadata.get("is_latest", True)),
                        created_at=item.created_at,
                    )
                )
                stored.append(item)
            await session.commit()
        return stored

    async def backfill_structured_items(self, project_slug: str, *, limit: int = 5_000) -> dict[str, Any]:
        """Create prompt-facing structured records from already stored raw chunks."""

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(OperationalMemoryChunkORM, OperationalMemoryEventORM)
                    .join(
                        OperationalMemoryEventORM,
                        OperationalMemoryChunkORM.event_id == OperationalMemoryEventORM.id,
                        isouter=True,
                    )
                    .where(OperationalMemoryChunkORM.project_slug == project_slug)
                    .order_by(desc(OperationalMemoryChunkORM.created_at))
                    .limit(max(1, min(50_000, limit)))
                )
            ).all()

        items = [
            _structured_item_from_chunk_event(chunk, event)
            for chunk, event in rows
            if chunk.content and chunk.content.strip()
        ]
        stored = await self.record_structured_items([item for item in items if item is not None])
        return {
            "project_slug": project_slug,
            "examined_chunks": len(rows),
            "derived_items": len(items),
            "stored_items": len(stored),
        }

    async def mark_chunks_failed(self, chunks: list[MemoryChunk], error: str) -> None:
        if not chunks:
            return
        async with self._session_factory() as session:
            for chunk in chunks:
                row = await session.get(OperationalMemoryChunkORM, chunk.id)
                if row is not None:
                    row.embedding_status = EmbeddingStatus.FAILED.value
                    row.embedding_error = error[:2_000]
            await session.commit()

    async def record_decision(self, decision: DecisionMemory) -> DecisionMemory:
        async with self._session_factory() as session:
            row = MemoryDecisionORM(
                id=decision.id,
                project_slug=decision.project_slug,
                conversation_id=_uuid_or_none(decision.conversation_id),
                decision=decision.decision,
                context=decision.context,
                alternatives_considered=decision.alternatives_considered,
                reason=decision.reason,
                status=decision.status.value,
                source_event_id=decision.source_event_id,
                embedding_status=decision.embedding_status.value,
                created_at=decision.created_at,
                updated_at=decision.updated_at,
            )
            session.add(row)
            await session.commit()
        return decision

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
            recent = await self._structured_recent_candidates(
                session=session,
                project_slug=project_slug,
                filters=memory_filter,
            )
            candidates = self._bounded_structured_candidates(
                semantic,
                recent,
                limit=max(25, min(50, top_k * 8)),
            )
            scored = self._score_structured_candidates(query, candidates)
            diversified = self._dedupe_structured_candidates(scored, top_k=max(1, top_k * 4))
            items = self._to_structured_items(diversified)
            formatted, budget_used, omitted_count, selected = (
                OperationalMemoryFormatter.format_structured_items(items, budget=budget)
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            session.add(
                MemoryRecallLogORM(
                    project_slug=project_slug,
                    query=query,
                    filters=memory_filter.to_log_dict(),
                    result_ids=[source_id for item in selected for source_id in item.source_ids],
                    scores={
                        source_id: item.score
                        for item in selected
                        for source_id in item.source_ids[:1]
                    },
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
                        smi.created_at,
                        ((subvector(me.embedding, 1, 2000))::vector(2000))
                          <=> ((subvector(CAST(:query_vector AS vector(4096)), 1, 2000))::vector(2000))
                          AS distance
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

    def _bounded_structured_candidates(
        self,
        semantic: list[StoredStructuredMemoryItem],
        recent: list[StoredStructuredMemoryItem],
        *,
        limit: int,
    ) -> list[StoredStructuredMemoryItem]:
        if not semantic:
            return self._merge_structured_candidates(recent[:limit])
        if not recent:
            return self._merge_structured_candidates(semantic[:limit])
        semantic_quota = max(1, int(limit * 0.7))
        recent_quota = max(0, limit - semantic_quota)
        return self._merge_structured_candidates(
            [*semantic[:semantic_quota], *recent[:recent_quota]]
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
        return list(merged.values())

    def _score_structured_candidates(
        self,
        query: str,
        candidates: list[StoredStructuredMemoryItem],
    ) -> list[StoredStructuredMemoryItem]:
        query_terms = _terms(query)
        for candidate in candidates:
            text = " ".join(
                str(part or "")
                for part in (
                    candidate.summary,
                    " ".join(candidate.evidence),
                    " ".join(candidate.paths),
                    candidate.item_type,
                    candidate.source_type,
                    candidate.primary_path,
                )
            )
            lexical = _lexical_score(query_terms, text)
            vector = 0.0
            if candidate.distance is not None:
                vector = max(0.0, 1.0 - float(candidate.distance))
            recency = 0.05 if lexical > 0 or vector > 0 else 0.0
            candidate.score = (vector * 2.0) + lexical + _structured_type_boost(candidate.item_type) + recency
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _dedupe_structured_candidates(
        self,
        candidates: list[StoredStructuredMemoryItem],
        *,
        top_k: int,
    ) -> list[StoredStructuredMemoryItem]:
        selected: list[StoredStructuredMemoryItem] = []
        seen_ids: set[UUID] = set()
        seen_sources: set[str] = set()
        seen_signatures: set[str] = set()
        seen_term_sets: list[set[str]] = []

        for candidate in candidates:
            if candidate.score <= 0:
                continue
            if candidate.id in seen_ids:
                continue
            if any(source_id in seen_sources for source_id in candidate.source_ids):
                continue
            signature = _semantic_signature(candidate.summary)
            if signature and signature in seen_signatures:
                continue
            candidate_terms = _semantic_term_set(
                " ".join([candidate.summary, *candidate.evidence, *candidate.paths])
            )
            if any(
                _overlap_coefficient(candidate_terms, selected_terms) >= 0.88
                for selected_terms in seen_term_sets
            ):
                continue
            selected.append(candidate)
            seen_ids.add(candidate.id)
            seen_sources.update(candidate.source_ids)
            if signature:
                seen_signatures.add(signature)
            if candidate_terms:
                seen_term_sets.append(candidate_terms)
            if len(selected) >= top_k:
                break
        return selected

    def _to_structured_items(
        self,
        candidates: list[StoredStructuredMemoryItem],
    ) -> list[StructuredMemoryItem]:
        items: list[StructuredMemoryItem] = []
        for candidate in candidates:
            try:
                item_type = StructuredMemoryType(candidate.item_type)
            except ValueError:
                item_type = StructuredMemoryType.FACT
            items.append(
                StructuredMemoryItem(
                    type=item_type,
                    summary=candidate.summary,
                    evidence=candidate.evidence[:4],
                    paths=candidate.paths[:8],
                    source_ids=candidate.source_ids or [str(candidate.id)],
                    event_types=candidate.event_types,
                    score=round(candidate.score, 4),
                    status=candidate.status,
                    created_at=candidate.created_at,
                    metadata={
                        "project_slug": candidate.project_slug,
                        "source_type": candidate.source_type,
                        "source_chunk_id": str(candidate.source_chunk_id)
                        if candidate.source_chunk_id
                        else None,
                        "primary_path": candidate.primary_path,
                        "distance": candidate.distance,
                    },
                )
            )
        return items

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
                    smi.created_at,
                    NULL::double precision AS distance
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

    async def stats(self, project_slug: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            event_count = await session.scalar(
                select(func.count()).select_from(OperationalMemoryEventORM).where(
                    OperationalMemoryEventORM.project_slug == project_slug
                )
            )
            chunk_count = await session.scalar(
                select(func.count()).select_from(OperationalMemoryChunkORM).where(
                    OperationalMemoryChunkORM.project_slug == project_slug
                )
            )
            embedding_count = await session.scalar(
                select(func.count()).select_from(MemoryEmbeddingORM).where(
                    MemoryEmbeddingORM.project_slug == project_slug
                )
            )
            decision_count = await session.scalar(
                select(func.count()).select_from(MemoryDecisionORM).where(
                    MemoryDecisionORM.project_slug == project_slug
                )
            )
            structured_count = await session.scalar(
                select(func.count()).select_from(StructuredMemoryItemORM).where(
                    StructuredMemoryItemORM.project_slug == project_slug
                )
            )
            status_rows = await session.execute(
                select(
                    OperationalMemoryChunkORM.embedding_status,
                    func.count(OperationalMemoryChunkORM.id),
                )
                .where(OperationalMemoryChunkORM.project_slug == project_slug)
                .group_by(OperationalMemoryChunkORM.embedding_status)
            )
        return {
            "project_slug": project_slug,
            "events": int(event_count or 0),
            "chunks": int(chunk_count or 0),
            "embeddings": int(embedding_count or 0),
            "structured_items": int(structured_count or 0),
            "decisions": int(decision_count or 0),
            "embedding_status": {
                str(status): int(count) for status, count in status_rows.all()
            },
        }

    async def list_recent_events(self, project_slug: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(OperationalMemoryEventORM)
                    .where(OperationalMemoryEventORM.project_slug == project_slug)
                    .order_by(desc(OperationalMemoryEventORM.created_at))
                    .limit(max(1, min(200, limit)))
                )
            ).scalars().all()
        return [
            {
                "id": str(row.id),
                "project_slug": row.project_slug,
                "conversation_id": str(row.conversation_id) if row.conversation_id else None,
                "event_type": row.event_type,
                "tool_name": row.tool_name,
                "status": row.status,
                "paths": row.paths or [],
                "error": row.error,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

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
                cautions.append("Conversation text is unverified; prefer tool, diff, file, and decision evidence.")
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


def _uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_file_path_filter(file_path: str) -> str:
    return str(file_path or "").replace("\\", "/").removeprefix("./").rstrip("/")


def _file_path_filter_variants(file_path: str, workspace_root: str | None) -> list[str]:
    variants = [file_path]
    workspace = _normalize_file_path_filter(workspace_root or "")
    if workspace and file_path.startswith(f"{workspace}/"):
        variants.append(file_path[len(workspace) + 1 :])
    return list(dict.fromkeys(path for path in variants if path))


def _file_path_suffix_patterns(file_path: str) -> list[str]:
    if not file_path or file_path.startswith("/"):
        return []
    return [f"%/{file_path}"]


def _structured_where_clause(
    alias: str,
    filters: OperationalMemoryFilter,
    params: dict[str, Any],
) -> str:
    clauses: list[str] = []
    if not filters.include_raw_chunks:
        clauses.append(f"{alias}.item_type <> 'raw_chunk'")
    if filters.active_only:
        clauses.append(f"{alias}.status = 'active'")
    if filters.latest_only:
        clauses.append(f"{alias}.is_latest = true")
    conversation_id = _uuid_or_none(filters.conversation_id)
    if conversation_id is not None:
        params["conversation_id"] = conversation_id
        clauses.append(f"{alias}.conversation_id = :conversation_id")
    if filters.session_id:
        params["session_id"] = filters.session_id
        clauses.append(f"{alias}.session_id = :session_id")
    if filters.workspace_root:
        params["workspace_root"] = filters.workspace_root
        clauses.append(f"{alias}.workspace_root = :workspace_root")
    if filters.source_types:
        placeholders = []
        for index, source_type in enumerate(filters.source_types):
            key = f"source_type_{index}"
            params[key] = source_type
            placeholders.append(f":{key}")
        joined = ", ".join(placeholders)
        clauses.append(f"({alias}.source_type IN ({joined}) OR {alias}.item_type IN ({joined}))")
    if filters.file_paths:
        exact_placeholders = []
        variant_placeholders = []
        suffix_clauses: list[str] = []
        path_suffix_clauses: list[str] = []
        for index, file_path in enumerate(filters.file_paths):
            key = f"file_path_{index}"
            normalized_path = _normalize_file_path_filter(file_path)
            params[key] = normalized_path
            exact_placeholders.append(f":{key}")
            for variant_index, variant in enumerate(
                variant
                for variant in _file_path_filter_variants(normalized_path, filters.workspace_root)
                if variant != normalized_path
            ):
                variant_key = f"file_path_{index}_variant_{variant_index}"
                params[variant_key] = variant
                variant_placeholders.append(f":{variant_key}")
            for suffix_index, suffix in enumerate(_file_path_suffix_patterns(normalized_path)):
                suffix_key = f"file_path_{index}_suffix_{suffix_index}"
                params[suffix_key] = suffix
                suffix_clauses.append(f"{alias}.primary_path LIKE :{suffix_key}")
                path_suffix_clauses.append(f"memory_path.path LIKE :{suffix_key}")
        exact_joined = ", ".join(exact_placeholders)
        all_placeholders = [*exact_placeholders, *variant_placeholders]
        all_joined = ", ".join(all_placeholders)
        path_match_clauses = [
            f"{alias}.primary_path IN ({exact_joined})",
            f"EXISTS (SELECT 1 FROM jsonb_array_elements_text({alias}.paths) AS memory_path(path) "
            f"WHERE memory_path.path IN ({all_joined})"
            + (f" OR {' OR '.join(path_suffix_clauses)}" if path_suffix_clauses else "")
            + ")",
        ]
        if variant_placeholders:
            path_match_clauses.append(f"{alias}.primary_path IN ({', '.join(variant_placeholders)})")
        path_match_clauses.extend(suffix_clauses)
        clauses.append("(" + " OR ".join(path_match_clauses) + ")")
    if filters.created_after:
        params["created_after"] = filters.created_after
        clauses.append(f"{alias}.created_at >= :created_after")
    if filters.created_before:
        params["created_before"] = filters.created_before
        clauses.append(f"{alias}.created_at <= :created_before")
    if not clauses:
        return ""
    return "AND " + "\n                      AND ".join(clauses)


def _rows_to_structured_candidates(rows: list[Any]) -> list[StoredStructuredMemoryItem]:
    candidates: list[StoredStructuredMemoryItem] = []
    for row in rows:
        evidence = row[4] if isinstance(row[4], list) else []
        paths = row[5] if isinstance(row[5], list) else []
        source_ids = row[6] if isinstance(row[6], list) else []
        source_type = str(row[8] or row[2] or "")
        candidates.append(
            StoredStructuredMemoryItem(
                id=row[0],
                project_slug=str(row[1] or ""),
                item_type=str(row[2] or StructuredMemoryType.FACT.value),
                summary=str(row[3] or ""),
                evidence=[str(item) for item in evidence if str(item).strip()],
                paths=[str(item) for item in paths if str(item).strip()],
                source_ids=[str(item) for item in source_ids if str(item).strip()],
                event_types=[source_type] if source_type else [],
                status=str(row[7] or "active"),
                source_type=source_type,
                source_chunk_id=row[9],
                primary_path=row[10],
                created_at=row[11],
                distance=float(row[12]) if row[12] is not None else None,
            )
        )
    return candidates


def _structured_type_boost(item_type: str) -> float:
    if item_type in {StructuredMemoryType.DECISION.value, StructuredMemoryType.LATEST_STATE.value}:
        return 0.55
    if item_type == StructuredMemoryType.SESSION_SUMMARY.value:
        return 0.45
    if item_type in {
        StructuredMemoryType.ERROR_SOLUTION.value,
        StructuredMemoryType.FILE_STATE.value,
        StructuredMemoryType.COMMAND_RESULT.value,
    }:
        return 0.35
    return 0.2


def _structured_type_from_event_type(event_type: str) -> StructuredMemoryType:
    if event_type == "operational_summary":
        return StructuredMemoryType.SESSION_SUMMARY
    if event_type == "decision":
        return StructuredMemoryType.DECISION
    if event_type == "agent_state":
        return StructuredMemoryType.LATEST_STATE
    if event_type in {"error_found", "solution_attempted"}:
        return StructuredMemoryType.ERROR_SOLUTION
    if event_type in {"file_created", "file_edited", "file_read", "diff_applied"}:
        return StructuredMemoryType.FILE_STATE
    if event_type in {"command_executed", "dependency_installed"}:
        return StructuredMemoryType.COMMAND_RESULT
    return StructuredMemoryType.FACT


def _structured_item_from_chunk_event(
    chunk: OperationalMemoryChunkORM,
    event: OperationalMemoryEventORM | None,
) -> StructuredMemoryItem | None:
    content = " ".join(str(chunk.content or "").split())
    if not content:
        return None
    event_type = str(event.event_type if event else chunk.source_type)
    item_type = _structured_type_from_event_type(event_type)
    primary_path = chunk.file_path or ((event.paths or [None])[0] if event else None)
    paths = [path for path in [primary_path, *((event.paths or []) if event else [])] if path]
    paths = list(dict.fromkeys(str(path) for path in paths))
    summary = _summary_from_structured_source(
        item_type=item_type,
        event_type=event_type,
        tool_name=event.tool_name if event else None,
        path=primary_path,
        text=content,
    )
    evidence = [_excerpt(content, limit=350)]
    metadata = {
        "project_slug": chunk.project_slug,
        "conversation_id": str(event.conversation_id) if event and event.conversation_id else None,
        "session_id": event.session_id if event else None,
        "workspace_root": event.workspace_root if event else None,
        "source_type": event_type,
        "source_id": str(event.id) if event else chunk.source_id,
        "content_hash": stable_hash("|".join([item_type.value, summary, str(chunk.id)])),
        "is_latest": item_type
        in {
            StructuredMemoryType.LATEST_STATE,
            StructuredMemoryType.DECISION,
            StructuredMemoryType.FILE_STATE,
        },
    }
    return StructuredMemoryItem(
        type=item_type,
        summary=summary,
        evidence=evidence,
        paths=paths,
        source_ids=[str(chunk.id)],
        event_types=[event_type],
        status="active",
        created_at=chunk.created_at,
        metadata=metadata,
    )


def _summary_from_structured_source(
    *,
    item_type: StructuredMemoryType,
    event_type: str,
    tool_name: str | None,
    path: str | None,
    text: str,
) -> str:
    prefix_by_type = {
        StructuredMemoryType.SESSION_SUMMARY: "Session summary",
        StructuredMemoryType.DECISION: "Decision",
        StructuredMemoryType.LATEST_STATE: "Latest state",
        StructuredMemoryType.ERROR_SOLUTION: "Error or fix",
        StructuredMemoryType.FILE_STATE: "File state",
        StructuredMemoryType.COMMAND_RESULT: "Command result",
        StructuredMemoryType.FACT: "Operational fact",
    }
    source = event_type.replace("_", " ")
    if tool_name:
        source = f"{source} via {tool_name}"
    if path:
        source = f"{source} in {path}"
    return f"{prefix_by_type[item_type]} from {source}: {_excerpt(text, limit=420)}"


def _embedding_to_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        return [float(item) for item in to_list()]
    to_numpy = getattr(value, "to_numpy", None)
    if callable(to_numpy):
        return [float(item) for item in to_numpy().tolist()]
    try:
        return [float(item) for item in value]
    except TypeError:
        return None


def _rows_to_candidates(rows: list[Any]) -> list[StoredMemoryChunk]:
    return [
        StoredMemoryChunk(chunk=row[0], event=row[1], embedding=_embedding_to_list(row[2]))
        for row in rows
    ]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8g}" for value in values) + "]"


def _terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in text.replace("_", " ").replace("-", " ").split()
        if len(term.strip(".,:;()[]{}'\"`")) >= 3
        for term in [term.strip(".,:;()[]{}'\"`")]
    }


def _semantic_signature(text: str, limit: int = 360) -> str:
    """Normalize a chunk enough to collapse repeated synthetic filler."""

    compact = " ".join(text.lower().split())
    if not compact:
        return ""

    normalized: list[str] = []
    current_size = 0
    for raw in compact.replace("_", " ").replace("-", " ").split():
        token = raw.strip(".,:;()[]{}'\"`")
        if not token:
            continue
        if any(char.isdigit() for char in token):
            token = "<num>"
        normalized.append(token)
        current_size += len(token) + 1
        if current_size >= limit:
            break
    return " ".join(normalized)[:limit]


def _semantic_term_set(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in text.lower().replace("_", " ").replace("-", " ").split():
        token = raw.strip(".,:;()[]{}'\"`")
        if len(token) < 4:
            continue
        if any(char.isdigit() for char in token):
            token = "<num>"
        terms.add(token)
    return terms


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


def _overlap_coefficient(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _lexical_score(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    lower = text.lower()
    hits = sum(1 for term in query_terms if term in lower)
    return hits / max(1, len(query_terms))


def _event_type_boost(event_type: str) -> float:
    if event_type in {"file_read", "file_created", "file_edited", "diff_applied"}:
        return 0.6
    if event_type in {"operational_summary", "decision"}:
        return 0.5
    if event_type in {"command_executed", "error_found", "dependency_installed", "tool_result"}:
        return 0.35
    return 0.1


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
