"""SQLAlchemy-backed TaskStore."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.tools.task_store import TaskRecord, TaskStore
from personagent.infrastructure.persistence.models import TaskRecordORM


class SqlAlchemyTaskStore(TaskStore):
    """Persistência de TaskRecord em PostgreSQL."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, record: TaskRecord) -> TaskRecord:
        async with self._session_factory() as session:
            orm = TaskRecordORM(
                id=UUID(record.id),
                conversation_id=record.conversation_id,
                workspace_root=record.workspace_root,
                title=record.title,
                description=record.description,
                status=record.status,
                priority=record.priority,
                output=record.output,
                metadata_=record.metadata,
            )
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return _to_record(orm)

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._session_factory() as session:
            orm = await session.get(TaskRecordORM, UUID(task_id))
            return _to_record(orm) if orm is not None else None

    async def update(self, task_id: str, values: dict[str, Any]) -> TaskRecord | None:
        async with self._session_factory() as session:
            orm = await session.get(TaskRecordORM, UUID(task_id))
            if orm is None:
                return None
            for key in ("title", "description", "status", "priority", "output"):
                if values.get(key) is not None:
                    setattr(orm, key, values[key])
            if values.get("metadata") is not None:
                orm.metadata_ = values["metadata"]
            orm.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(orm)
            return _to_record(orm)

    async def list(
        self,
        *,
        conversation_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        async with self._session_factory() as session:
            stmt = (
                select(TaskRecordORM).order_by(TaskRecordORM.updated_at.desc()).limit(max(1, limit))
            )
            if conversation_id is not None:
                stmt = stmt.where(TaskRecordORM.conversation_id == conversation_id)
            if status is not None:
                stmt = stmt.where(TaskRecordORM.status == status)
            result = await session.execute(stmt)
            return [_to_record(orm) for orm in result.scalars().all()]


def _to_record(orm: TaskRecordORM) -> TaskRecord:
    return TaskRecord(
        id=str(orm.id),
        title=str(orm.title),
        description=str(orm.description or ""),
        status=str(orm.status or "open"),
        priority=str(orm.priority or "normal"),
        conversation_id=str(orm.conversation_id) if orm.conversation_id else None,
        workspace_root=str(orm.workspace_root) if orm.workspace_root else None,
        output=str(orm.output or ""),
        metadata=dict(orm.metadata_ or {}),
        created_at=orm.created_at or datetime.now(UTC),
        updated_at=orm.updated_at or datetime.now(UTC),
    )


__all__ = ["SqlAlchemyTaskStore"]
