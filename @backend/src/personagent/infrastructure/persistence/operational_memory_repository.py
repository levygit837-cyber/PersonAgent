"""PostgreSQL-backed repository for operational RAG memory.

After decomposition, this class is a thin facade that wires three
collaborators extracted from the original god file:

* ``EventOutboxManager`` — event CRUD and outbox state machine
* ``StructuredItemStore`` — chunk/embedding/structured-item persistence
* ``RecallRetrievalPipeline`` — hybrid recall, scoring, and ranking

The only method that remains inlined is ``stats()`` (cross-cutting aggregator).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personagent.domain.memory.models.operational import (
    DecisionMemory,
    MemoryChunk,
    MemoryContextBudget,
    MemoryEvent,
    RecallFinding,
    StructuredMemoryItem,
    StructuredMemoryPackage,
)
from personagent.infrastructure.persistence.models import (
    MemoryDecisionORM,
    MemoryEmbeddingORM,
    MemoryOutboxORM,
    OperationalMemoryChunkORM,
    OperationalMemoryEventORM,
    StructuredMemoryItemORM,
)
from personagent.infrastructure.persistence.operational_memory.event_outbox import (
    EventOutboxManager,
)
from personagent.infrastructure.persistence.operational_memory.recall_retrieval import (
    RecallRetrievalPipeline,
)
from personagent.infrastructure.persistence.operational_memory.structured_items import (
    StructuredItemStore,
)


class OperationalMemoryRepository:
    """Persistence and lightweight hybrid recall for operational memory."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._event_outbox = EventOutboxManager(session_factory=session_factory)
        self._structured_items = StructuredItemStore(session_factory=session_factory)
        self._recall = RecallRetrievalPipeline(session_factory=session_factory)

    # -- event / outbox --------------------------------------------------

    async def record_event(self, event: MemoryEvent) -> MemoryEvent:
        return await self._event_outbox.record_event(event)

    async def record_event_with_outbox(
        self,
        event: MemoryEvent,
        *,
        job_type: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> tuple[MemoryEvent, dict[str, Any]]:
        """Persist the raw event and durable outbox job in one transaction."""
        return await self._event_outbox.record_event_with_outbox(
            event, job_type=job_type, payload=payload, dedupe_key=dedupe_key
        )

    async def get_event(self, event_id: str | UUID) -> MemoryEvent | None:
        return await self._event_outbox.get_event(event_id)

    async def mark_outbox_published(self, outbox_id: str | UUID) -> None:
        await self._event_outbox.mark_outbox_published(outbox_id)

    async def mark_outbox_processing(self, outbox_id: str | UUID) -> None:
        await self._event_outbox.mark_outbox_processing(outbox_id)

    async def mark_outbox_completed(self, outbox_id: str | UUID) -> None:
        await self._event_outbox.mark_outbox_completed(outbox_id)

    async def mark_outbox_failed(self, outbox_id: str | UUID, error: str) -> None:
        await self._event_outbox.mark_outbox_failed(outbox_id, error)

    async def list_recent_events(
        self, project_slug: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return await self._event_outbox.list_recent_events(project_slug, limit=limit)

    # -- chunk / embedding / structured-item persistence -----------------

    async def record_chunks(self, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        return await self._structured_items.record_chunks(chunks)

    async def record_embeddings(
        self,
        *,
        chunks: list[MemoryChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        await self._structured_items.record_embeddings(
            chunks=chunks, vectors=vectors, embedding_model=embedding_model
        )

    async def record_structured_items(
        self, items: list[StructuredMemoryItem]
    ) -> list[StructuredMemoryItem]:
        return await self._structured_items.record_structured_items(items)

    async def backfill_structured_items(
        self, project_slug: str, *, limit: int = 5_000
    ) -> dict[str, Any]:
        """Create prompt-facing structured records from already stored raw chunks."""
        return await self._structured_items.backfill_structured_items(
            project_slug, limit=limit
        )

    async def mark_chunks_failed(self, chunks: list[MemoryChunk], error: str) -> None:
        await self._structured_items.mark_chunks_failed(chunks, error)

    async def record_decision(self, decision: DecisionMemory) -> DecisionMemory:
        return await self._structured_items.record_decision(decision)

    async def record_recall_skip(
        self,
        *,
        project_slug: str,
        query: str,
        filters: dict[str, Any],
        reason: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        await self._structured_items.record_recall_skip(
            project_slug=project_slug,
            query=query,
            filters=filters,
            reason=reason,
            provider=provider,
            model=model,
        )

    # -- recall / retrieval -----------------------------------------------

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
        return await self._recall.recall(
            project_slug=project_slug,
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters,
            provider=provider,
            model=model,
        )

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
        return await self._recall.recall_structured_package(
            project_slug=project_slug,
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters,
            budget=budget,
            provider=provider,
            model=model,
        )

    # -- cross-cutting ----------------------------------------------------

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
            outbox_rows = await session.execute(
                select(MemoryOutboxORM.status, func.count(MemoryOutboxORM.id))
                .where(MemoryOutboxORM.project_slug == project_slug)
                .group_by(MemoryOutboxORM.status)
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
            "outbox_status": {
                str(status): int(count) for status, count in outbox_rows.all()
            },
        }
