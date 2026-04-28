"""Routes for Lab graph persistence."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.infrastructure.persistence.models import LabGraphORM
from personagent.interfaces.api.routes.chat import get_db

router = APIRouter(prefix="/lab/graphs", tags=["lab"])
DB_SESSION_DEPENDENCY = Depends(get_db)


class LabGraphCreateRequest(BaseModel):
    """Payload for creating a Lab graph."""

    title: str = Field(default="Untitled Lab Graph", min_length=1, max_length=255)
    graph: dict[str, Any] = Field(default_factory=dict)


class LabGraphUpdateRequest(BaseModel):
    """Payload for updating a Lab graph."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    graph: dict[str, Any] | None = None


class LabGraphResponse(BaseModel):
    """Complete Lab graph response."""

    id: str
    title: str
    graph: dict[str, Any]
    created_at: str
    updated_at: str


class LabGraphStore(Protocol):
    """Persistence contract for Lab graphs."""

    async def list(self, limit: int, offset: int) -> Sequence[LabGraphORM]: ...

    async def create(self, request: LabGraphCreateRequest) -> LabGraphORM: ...

    async def get(self, graph_id: UUID) -> LabGraphORM | None: ...

    async def update(
        self,
        graph_id: UUID,
        request: LabGraphUpdateRequest,
    ) -> LabGraphORM | None: ...

    async def delete(self, graph_id: UUID) -> bool: ...


class SqlAlchemyLabGraphStore:
    """Lab graph persistence with SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list(self, limit: int, offset: int) -> Sequence[LabGraphORM]:
        result = await self._session.execute(
            select(LabGraphORM).order_by(LabGraphORM.updated_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def create(self, request: LabGraphCreateRequest) -> LabGraphORM:
        graph = LabGraphORM(title=request.title, graph=request.graph)
        self._session.add(graph)
        await self._session.commit()
        await self._session.refresh(graph)
        return graph

    async def get(self, graph_id: UUID) -> LabGraphORM | None:
        result = await self._session.execute(select(LabGraphORM).where(LabGraphORM.id == graph_id))
        return result.scalar_one_or_none()

    async def update(
        self,
        graph_id: UUID,
        request: LabGraphUpdateRequest,
    ) -> LabGraphORM | None:
        graph = await self.get(graph_id)
        if graph is None:
            return None
        if request.title is not None:
            graph.title = request.title
        if request.graph is not None:
            graph.graph = request.graph
        await self._session.commit()
        await self._session.refresh(graph)
        return graph

    async def delete(self, graph_id: UUID) -> bool:
        graph = await self.get(graph_id)
        if graph is None:
            return False
        await self._session.delete(graph)
        await self._session.commit()
        return True


async def get_lab_graph_store(
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> LabGraphStore:
    """Dependency for obtaining the Lab graph store."""

    return SqlAlchemyLabGraphStore(session)


LAB_GRAPH_STORE_DEPENDENCY = Depends(get_lab_graph_store)


def serialize_lab_graph(graph: LabGraphORM) -> LabGraphResponse:
    """Serialize a Lab graph into an HTTP response."""

    created_at = graph.created_at or datetime.now()
    updated_at = graph.updated_at or created_at
    return LabGraphResponse(
        id=str(graph.id),
        title=graph.title,
        graph=graph.graph or {},
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
    )


@router.get("", response_model=list[LabGraphResponse])
async def list_lab_graphs(
    limit: int = 50,
    offset: int = 0,
    store: LabGraphStore = LAB_GRAPH_STORE_DEPENDENCY,
) -> list[LabGraphResponse]:
    """List Lab graphs."""

    graphs = await store.list(limit=limit, offset=offset)
    return [serialize_lab_graph(graph) for graph in graphs]


@router.post("", response_model=LabGraphResponse)
async def create_lab_graph(
    request: LabGraphCreateRequest,
    store: LabGraphStore = LAB_GRAPH_STORE_DEPENDENCY,
) -> LabGraphResponse:
    """Create a Lab graph."""

    graph = await store.create(request)
    return serialize_lab_graph(graph)


@router.get("/{graph_id}", response_model=LabGraphResponse)
async def get_lab_graph(
    graph_id: UUID,
    store: LabGraphStore = LAB_GRAPH_STORE_DEPENDENCY,
) -> LabGraphResponse:
    """Load a complete Lab graph."""

    graph = await store.get(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Lab graph not found")
    return serialize_lab_graph(graph)


@router.put("/{graph_id}", response_model=LabGraphResponse)
async def update_lab_graph(
    graph_id: UUID,
    request: LabGraphUpdateRequest,
    store: LabGraphStore = LAB_GRAPH_STORE_DEPENDENCY,
) -> LabGraphResponse:
    """Update the complete document for a Lab graph."""

    graph = await store.update(graph_id, request)
    if graph is None:
        raise HTTPException(status_code=404, detail="Lab graph not found")
    return serialize_lab_graph(graph)


@router.delete("/{graph_id}")
async def delete_lab_graph(
    graph_id: UUID,
    store: LabGraphStore = LAB_GRAPH_STORE_DEPENDENCY,
) -> dict[str, bool]:
    """Delete a Lab graph."""

    deleted = await store.delete(graph_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lab graph not found")
    return {"deleted": True}
