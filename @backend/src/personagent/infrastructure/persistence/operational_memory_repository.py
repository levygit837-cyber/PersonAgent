"""PostgreSQL-backed repository for operational RAG memory."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personagent.domain.memory.models.operational import (
    DecisionMemory,
    EmbeddingStatus,
    MemoryChunk,
    MemoryEvent,
    RecallFinding,
)
from personagent.domain.memory.services.operational_memory import EmbeddingVector
from personagent.infrastructure.persistence.models import (
    MemoryDecisionORM,
    MemoryEmbeddingORM,
    MemoryRecallLogORM,
    OperationalMemoryChunkORM,
    OperationalMemoryEventORM,
)


@dataclass(slots=True)
class StoredMemoryChunk:
    """Chunk plus optional vector returned by recall."""

    chunk: OperationalMemoryChunkORM
    event: OperationalMemoryEventORM | None
    embedding: list[float] | None
    score: float = 0.0


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
                        OperationalMemoryChunkORM.source_id == chunk.source_id,
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
        started = time.perf_counter()
        filters = filters or {}
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    OperationalMemoryChunkORM,
                    OperationalMemoryEventORM,
                    MemoryEmbeddingORM.embedding,
                )
                .join(
                    OperationalMemoryEventORM,
                    OperationalMemoryChunkORM.event_id == OperationalMemoryEventORM.id,
                    isouter=True,
                )
                .join(
                    MemoryEmbeddingORM,
                    OperationalMemoryChunkORM.id == MemoryEmbeddingORM.chunk_id,
                    isouter=True,
                )
                .where(OperationalMemoryChunkORM.project_slug == project_slug)
                .order_by(desc(OperationalMemoryChunkORM.created_at))
                .limit(int(filters.get("candidate_limit") or 500))
            )
            candidates = [
                StoredMemoryChunk(chunk=row[0], event=row[1], embedding=row[2])
                for row in result.all()
            ]

            active_decisions = (
                await session.execute(
                    select(MemoryDecisionORM)
                    .where(
                        MemoryDecisionORM.project_slug == project_slug,
                        MemoryDecisionORM.status == "active",
                    )
                    .order_by(desc(MemoryDecisionORM.updated_at))
                    .limit(8)
                )
            ).scalars().all()

            scored = self._score_candidates(query, candidates, query_embedding)
            findings = self._to_findings(scored[: max(1, top_k)], active_decisions)
            latency_ms = int((time.perf_counter() - started) * 1000)
            session.add(
                MemoryRecallLogORM(
                    project_slug=project_slug,
                    query=query,
                    filters=filters,
                    result_ids=[source_id for f in findings for source_id in f.source_ids],
                    scores={
                        source_id: f.score
                        for f in findings
                        for source_id in f.source_ids[:1]
                    },
                    latency_ms=latency_ms,
                    provider=provider,
                    model=model,
                )
            )
            await session.commit()
        return findings

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

    def _to_findings(
        self,
        candidates: list[StoredMemoryChunk],
        active_decisions: list[MemoryDecisionORM],
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
            excerpt = _excerpt(candidate.chunk.content)
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


def _terms(text: str) -> set[str]:
    return {
        term.lower()
        for term in text.replace("_", " ").replace("-", " ").split()
        if len(term.strip(".,:;()[]{}'\"`")) >= 3
        for term in [term.strip(".,:;()[]{}'\"`")]
    }


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


def _excerpt(text: str, limit: int = 420) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."
