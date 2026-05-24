"""Event and outbox persistence for operational memory.

Extracted from ``OperationalMemoryRepository`` (Slice 2).
Owns raw event CRUD, outbox state machine, and event queries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from personagent.domain.memory.models.operational import (
    MemoryEvent,
    OperationalMemoryEventType,
)
from personagent.infrastructure.persistence.models import (
    MemoryOutboxORM,
    OperationalMemoryEventORM,
)


class EventOutboxManager:
    """Raw event persistence and durable outbox state machine."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_event(self, event: MemoryEvent) -> MemoryEvent:
        async with self._session_factory() as session:
            session.add(_event_row(event))
            await session.commit()
        return event

    async def record_event_with_outbox(
        self,
        event: MemoryEvent,
        *,
        job_type: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> tuple[MemoryEvent, dict[str, Any]]:
        """Persist the raw event and durable outbox job in one transaction."""

        async with self._session_factory() as session:
            session.add(_event_row(event))
            existing = await session.scalar(
                select(MemoryOutboxORM).where(MemoryOutboxORM.dedupe_key == dedupe_key)
            )
            if existing is None:
                existing = MemoryOutboxORM(
                    id=uuid4(),
                    event_id=event.id,
                    project_slug=event.project_slug,
                    workspace_root=event.workspace_root,
                    job_type=job_type,
                    payload=payload,
                    status="pending",
                    dedupe_key=dedupe_key,
                )
                session.add(existing)
            await session.commit()
            outbox = _outbox_payload(existing)
        return event, outbox

    async def get_event(self, event_id: str | UUID) -> MemoryEvent | None:
        event_uuid = _uuid_or_none(event_id)
        if event_uuid is None:
            return None
        async with self._session_factory() as session:
            row = await session.get(OperationalMemoryEventORM, event_uuid)
        return _event_from_row(row) if row is not None else None

    async def mark_outbox_published(self, outbox_id: str | UUID) -> None:
        await self._update_outbox(outbox_id, status="published", last_error=None)

    async def mark_outbox_processing(self, outbox_id: str | UUID) -> None:
        await self._update_outbox(outbox_id, status="processing")

    async def mark_outbox_completed(self, outbox_id: str | UUID) -> None:
        await self._update_outbox(outbox_id, status="completed", last_error=None)

    async def mark_outbox_failed(self, outbox_id: str | UUID, error: str) -> None:
        outbox_uuid = _uuid_or_none(outbox_id)
        if outbox_uuid is None:
            return
        async with self._session_factory() as session:
            row = await session.get(MemoryOutboxORM, outbox_uuid)
            if row is None:
                return
            row.attempts = int(row.attempts or 0) + 1
            row.status = "failed" if row.attempts >= 5 else "pending"
            row.last_error = error[:2_000]
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(300, 2 ** row.attempts))
            await session.commit()

    async def _update_outbox(
        self,
        outbox_id: str | UUID,
        *,
        status: str,
        last_error: str | None = None,
    ) -> None:
        outbox_uuid = _uuid_or_none(outbox_id)
        if outbox_uuid is None:
            return
        async with self._session_factory() as session:
            row = await session.get(MemoryOutboxORM, outbox_uuid)
            if row is None:
                return
            row.status = status
            row.last_error = last_error
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def list_recent_events(
        self, project_slug: str, limit: int = 50
    ) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Module-level helpers (moved from operational_memory_repository.py)
# ---------------------------------------------------------------------------


def _event_row(event: MemoryEvent) -> OperationalMemoryEventORM:
    return OperationalMemoryEventORM(
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


def _event_from_row(row: OperationalMemoryEventORM) -> MemoryEvent:
    return MemoryEvent(
        id=row.id,
        project_slug=row.project_slug,
        workspace_root=row.workspace_root,
        session_id=row.session_id,
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
        agent_name=row.agent_name,
        event_type=OperationalMemoryEventType(str(row.event_type)),
        task=row.task,
        tool_name=row.tool_name,
        status=row.status,
        input=row.input or {},
        output=row.output or {},
        error=row.error,
        resolution=row.resolution,
        paths=row.paths or [],
        metadata=row.metadata_ or {},
        source_hash=row.source_hash,
        created_at=row.created_at,
    )


def _outbox_payload(row: MemoryOutboxORM) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "event_id": str(row.event_id) if row.event_id else None,
        "project_slug": row.project_slug,
        "workspace_root": row.workspace_root,
        "job_type": row.job_type,
        "payload": row.payload or {},
        "dedupe_key": row.dedupe_key,
    }


def _uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
