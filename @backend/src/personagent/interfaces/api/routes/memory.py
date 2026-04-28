"""FastAPI memory management routes."""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)
from personagent.interfaces.config.di_container import DIContainer, get_container

router = APIRouter(prefix="/memory", tags=["memory"])
logger = structlog.get_logger(__name__)

# Reused for name validation
_NAME_VALIDATOR = MemoryScanner()
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def get_memory_repo() -> MemoryRepository:
    """Factory for the memory repository."""
    return FileSystemMemoryRepository()


PRIVATE_SCOPE_QUERY = Query(default=MemoryScope.PRIVATE)
MEMORY_TYPE_QUERY = Query(default=None)
MEMORY_REPO_DEPENDENCY = Depends(get_memory_repo)
CONTAINER_DEPENDENCY = Depends(get_container)
EVENT_LIMIT_QUERY = Query(default=50, ge=1, le=200)


class MemoryCreateRequest(BaseModel):
    """Request for memory creation."""

    name: str = Field(..., description="Memory snake_case name")
    description: str = Field(..., description="Memory description")
    content: str = Field(..., description="Memory Markdown content")
    memory_type: MemoryType = Field(default=MemoryType.PROJECT, description="Memory type")
    scope: MemoryScope = Field(default=MemoryScope.PRIVATE, description="Persistence scope")


class MemoryUpdateRequest(BaseModel):
    """Request for memory updates."""

    description: str | None = Field(default=None, description="New description")
    content: str | None = Field(default=None, description="New content")


class MemoryResponse(BaseModel):
    """Response with memory data."""

    path: str
    name: str
    description: str
    memory_type: str
    scope: str
    content: str
    mtime_ms: int
    is_truncated: bool = False


class MemoryListResponse(BaseModel):
    """Response with a memory list."""

    memories: list[dict[str, Any]]
    count: int


class OperationalRecallRequest(BaseModel):
    """Request for operational RAG recall preview."""

    query: str = Field(..., description="Semantic query")
    top_k: int = Field(default=6, ge=1, le=20)
    provider: str | None = None
    model: str | None = None


class OperationalReindexRequest(BaseModel):
    """Request for operational reindexing."""

    source: str = Field(default="all", description="all, files, failed_embeddings")


def _validate_memory_name(name: str) -> None:
    """Validate that the memory name is snake_case and filesystem-safe."""
    if not name:
        raise HTTPException(status_code=400, detail="Memory name cannot be empty")
    if not _SNAKE_CASE_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"Memory name must be snake_case (got: {name})",
        )
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Memory name contains invalid characters")


# IMPORTANT: more specific routes must come before generic path-param routes.
# FastAPI resolves routes in definition order.


@router.get("/{project_slug}/index")
async def get_memory_index(
    project_slug: str,
    scope: MemoryScope = PRIVATE_SCOPE_QUERY,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, Any]:
    """Read the MEMORY.md file for a project."""
    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    index = await repo.read_index(memory_dir)

    if not index:
        raise HTTPException(status_code=404, detail="Memory index not found")

    return {
        "path": str(index.entrypoint_path),
        "content": index.content,
        "line_count": index.line_count,
        "was_truncated": index.was_truncated,
    }


@router.get("/{project_slug}/operational/status")
async def get_operational_memory_status(
    project_slug: str,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Operational RAG memory status."""
    service = container.get_operational_memory_service()
    if service is None:
        return {"project_slug": project_slug, "enabled": False}
    status = await service.status(project_slug)
    status["enabled"] = True
    return status


@router.post("/{project_slug}/operational/recall")
async def preview_operational_memory_recall(
    project_slug: str,
    request: OperationalRecallRequest,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Preview the operational memory block that would enter the prompt."""
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    formatted = await service.recall_for_prompt(
        project_slug=project_slug,
        query=request.query,
        provider=request.provider,
        model=request.model,
        top_k=request.top_k,
    )
    return {
        "project_slug": project_slug,
        "query": request.query,
        "top_k": request.top_k,
        "formatted": formatted,
    }


@router.get("/{project_slug}/operational/events")
async def list_operational_memory_events(
    project_slug: str,
    limit: int = EVENT_LIMIT_QUERY,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """List recent operational events."""
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    events = await service.repository.list_recent_events(project_slug, limit=limit)
    return {"project_slug": project_slug, "events": events, "count": len(events)}


@router.post("/{project_slug}/operational/reindex")
async def reindex_operational_memory(
    project_slug: str,
    request: OperationalReindexRequest,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Accept an operational reindex request.

    v1 already indexes in real time; this endpoint reserves the public contract
    for backfill/reembedding jobs.
    """
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    return {
        "project_slug": project_slug,
        "status": "accepted",
        "source": request.source,
        "message": "Real-time indexing is active; batch reindex worker is reserved for v1.1.",
    }


@router.get("/{project_slug}/{memory_name}")
async def get_memory(
    project_slug: str,
    memory_name: str,
    scope: MemoryScope = PRIVATE_SCOPE_QUERY,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> MemoryResponse:
    """Read a specific memory."""
    _validate_memory_name(memory_name)
    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    file_path = memory_dir / f"{memory_name}.md"

    memory = await repo.read(file_path)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    return MemoryResponse(
        path=str(memory.path),
        name=memory.name,
        description=memory.description,
        memory_type=memory.memory_type.value,
        scope=memory.scope.value,
        content=memory.content,
        mtime_ms=memory.mtime_ms,
        is_truncated=memory.is_truncated,
    )


@router.put("/{project_slug}/{memory_name}")
async def update_memory(
    project_slug: str,
    memory_name: str,
    request: MemoryUpdateRequest,
    scope: MemoryScope = PRIVATE_SCOPE_QUERY,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, str]:
    """Update an existing memory."""
    _validate_memory_name(memory_name)
    from personagent.domain.memory.models.memory_file import MemoryFile

    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    file_path = memory_dir / f"{memory_name}.md"

    existing = await repo.read(file_path)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Merge frontmatter: preserve extras and update name/description/type
    merged_frontmatter = dict(existing.frontmatter)
    merged_frontmatter.update({
        "name": existing.name,
        "description": request.description or existing.description,
        "type": str(existing.memory_type),
    })

    memory = MemoryFile(
        path=file_path,
        memory_type=existing.memory_type,
        name=existing.name,
        description=request.description or existing.description,
        content=request.content or existing.content,
        raw_content=existing.raw_content,
        frontmatter=merged_frontmatter,
        scope=existing.scope,
    )

    written_path = await repo.write(memory)
    logger.info("memory_updated", path=str(written_path), project_slug=project_slug)
    return {"status": "updated", "path": str(written_path)}


@router.delete("/{project_slug}/{memory_name}")
async def delete_memory(
    project_slug: str,
    memory_name: str,
    scope: MemoryScope = PRIVATE_SCOPE_QUERY,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, str]:
    """Delete a memory."""
    _validate_memory_name(memory_name)
    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    file_path = memory_dir / f"{memory_name}.md"

    deleted = await repo.delete(file_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Update index
    headers = await repo.scan(memory_dir)
    entries = [
        {
            "name": h.name or h.filename.replace(".md", ""),
            "description": h.description or "",
            "type": h.memory_type.value if h.memory_type else "project",
        }
        for h in headers
        if h.name
    ]
    if entries:
        await repo.update_index(memory_dir, entries)

    logger.info("memory_deleted", path=str(file_path), project_slug=project_slug)
    return {"status": "deleted", "path": str(file_path)}


@router.post("/{project_slug}")
async def create_memory(
    project_slug: str,
    request: MemoryCreateRequest,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, str]:
    """Create a new memory."""
    _validate_memory_name(request.name)
    from personagent.domain.memory.models.memory_file import MemoryFile

    memory_dir = await repo.get_memory_dir(project_slug, scope=request.scope)
    file_path = memory_dir / f"{request.name}.md"

    # Check duplicate
    if await repo.read(file_path):
        raise HTTPException(status_code=409, detail=f"Memory '{request.name}' already exists")

    memory = MemoryFile(
        path=file_path,
        memory_type=request.memory_type,
        name=request.name,
        description=request.description,
        content=request.content,
        raw_content="",
        scope=request.scope,
    )

    written_path = await repo.write(memory)

    # Update index
    headers = await repo.scan(memory_dir)
    entries = [
        {
            "name": h.name or h.filename.replace(".md", ""),
            "description": h.description or "",
            "type": h.memory_type.value if h.memory_type else "project",
        }
        for h in headers
        if h.name
    ]
    if entries:
        await repo.update_index(memory_dir, entries)

    logger.info("memory_created", path=str(written_path), project_slug=project_slug)
    return {"status": "created", "path": str(written_path)}


@router.get("/{project_slug}")
async def list_memories(
    project_slug: str,
    scope: MemoryScope = PRIVATE_SCOPE_QUERY,
    memory_type: MemoryType | None = MEMORY_TYPE_QUERY,
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> MemoryListResponse:
    """List memories for a project."""
    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)

    if memory_type:
        headers = await repo.list_by_type(memory_dir, memory_type)
    else:
        headers = await repo.scan(memory_dir)

    memories = [
        {
            "path": str(h.file_path),
            "filename": h.filename,
            "name": h.name,
            "description": h.description,
            "type": h.memory_type.value if h.memory_type else None,
            "mtime_ms": h.mtime_ms,
        }
        for h in headers
    ]

    return MemoryListResponse(memories=memories, count=len(memories))
