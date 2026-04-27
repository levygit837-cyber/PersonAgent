"""Persistence store for workflow documents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.infrastructure.persistence.models import LabGraphORM


class WorkflowStore(Protocol):
    """Persistence contract used by workflow routes."""

    async def list(self, limit: int, offset: int) -> Sequence[LabGraphORM]: ...

    async def create(self, title: str, workflow: dict[str, Any]) -> LabGraphORM: ...

    async def get(self, workflow_id: UUID) -> LabGraphORM | None: ...

    async def update(
        self,
        workflow_id: UUID,
        *,
        title: str | None = None,
        workflow: dict[str, Any] | None = None,
    ) -> LabGraphORM | None: ...

    async def delete(self, workflow_id: UUID) -> bool: ...


class SqlAlchemyWorkflowStore:
    """Workflow persistence backed by the existing lab_graphs table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, limit: int, offset: int) -> Sequence[LabGraphORM]:
        result = await self._session.execute(
            select(LabGraphORM).order_by(LabGraphORM.updated_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def create(self, title: str, workflow: dict[str, Any]) -> LabGraphORM:
        graph = LabGraphORM(title=title, graph=workflow)
        self._session.add(graph)
        await self._session.commit()
        await self._session.refresh(graph)
        return graph

    async def get(self, workflow_id: UUID) -> LabGraphORM | None:
        result = await self._session.execute(
            select(LabGraphORM).where(LabGraphORM.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        workflow_id: UUID,
        *,
        title: str | None = None,
        workflow: dict[str, Any] | None = None,
    ) -> LabGraphORM | None:
        graph = await self.get(workflow_id)
        if graph is None:
            return None
        if title is not None:
            graph.title = title
        if workflow is not None:
            graph.graph = workflow
        await self._session.commit()
        await self._session.refresh(graph)
        return graph

    async def delete(self, workflow_id: UUID) -> bool:
        graph = await self.get(workflow_id)
        if graph is None:
            return False
        await self._session.delete(graph)
        await self._session.commit()
        return True
