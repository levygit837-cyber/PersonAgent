"""FastAPI memory management routes."""

from __future__ import annotations

import re
from datetime import datetime
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
from personagent.interfaces.api.action_approvals import require_action_approval
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
    approval_id: str | None = None
    args_hash: str | None = None


class MemoryUpdateRequest(BaseModel):
    """Request for memory updates."""

    description: str | None = Field(default=None, description="New description")
    content: str | None = Field(default=None, description="New content")
    approval_id: str | None = None
    args_hash: str | None = None


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
    conversation_id: str | None = None
    current_conversation_id: str | None = None
    session_id: str | None = None
    workspace_root: str | None = None
    source_types: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None
    latest_only: bool = False
    active_only: bool = True
    include_statuses: list[str] = Field(default_factory=list)
    budget_tokens: int | None = Field(default=None, ge=1)
    provider: str | None = None
    model: str | None = None
    debug: bool = False


class OperationalReindexRequest(BaseModel):
    """Request for operational reindexing."""

    source: str = Field(default="all", description="all, files, failed_embeddings")
    limit: int = Field(default=5_000, ge=1, le=50_000)


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


def _memory_approval_arguments(
    *,
    project_slug: str,
    memory_name: str | None = None,
    request: BaseModel | None = None,
    scope: MemoryScope | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"project_slug": project_slug}
    if memory_name is not None:
        data["memory_name"] = memory_name
    if scope is not None:
        data["scope"] = scope.value
    if request is not None:
        payload = request.model_dump(mode="json")
        payload.pop("approval_id", None)
        payload.pop("args_hash", None)
        data["request"] = payload
    return data


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
    try:
        status["embedding_runtime"] = container.get_embedding_process_manager().runtime_status()
    except Exception:
        logger.warning("embedding_runtime_status_failed", exc_info=True)
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
    package = await service.recall_package_for_prompt(
        project_slug=project_slug,
        query=request.query,
        provider=request.provider,
        model=request.model,
        top_k=request.top_k,
        conversation_id=request.conversation_id,
        current_conversation_id=request.current_conversation_id,
        session_id=request.session_id,
        workspace_root=request.workspace_root,
        source_types=request.source_types,
        file_paths=request.file_paths,
        created_after=request.created_after,
        created_before=request.created_before,
        latest_only=request.latest_only,
        active_only=request.active_only,
        include_statuses=request.include_statuses,
        budget_tokens=request.budget_tokens,
    )
    return {
        "project_slug": project_slug,
        "query": request.query,
        "top_k": request.top_k,
        "formatted": package.formatted,
        "items": [_structured_memory_item_payload(item) for item in package.items],
        "filters_applied": package.filters_applied,
        "budget_used": package.budget_used,
        "budget_tokens": package.budget_tokens,
        "omitted_count": package.omitted_count,
        "latency_ms": package.latency_ms,
        "recall_scope": package.recall_scope,
        "query_intent": package.query_intent,
        "candidate_count": package.candidate_count,
        "token_usage": package.token_usage,
        "included_reasons": package.included_reasons,
        "discarded_candidates": package.discarded_candidates if request.debug else [],
        "ranking_breakdown": package.ranking_breakdown if request.debug else {},
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
    result = await service.backfill_structured_memory(project_slug, limit=request.limit)
    return {
        "project_slug": project_slug,
        "status": "accepted",
        "source": request.source,
        "backfill": result,
        "message": "Structured operational-memory backfill completed for stored raw chunks.",
    }


def _structured_memory_item_payload(item: Any) -> dict[str, Any]:
    return {
        "type": item.type.value if hasattr(item.type, "value") else str(item.type),
        "summary": item.summary,
        "evidence": item.evidence,
        "paths": item.paths,
        "source_ids": item.source_ids,
        "event_types": item.event_types,
        "score": item.score,
        "status": item.status,
        "trust_level": getattr(item, "trust_level", "medium"),
        "importance": getattr(item, "importance", 0.5),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "metadata": item.metadata,
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
    require_action_approval(
        action_kind="memory.update",
        approval_id=request.approval_id,
        args_hash=request.args_hash,
        arguments=_memory_approval_arguments(
            project_slug=project_slug,
            memory_name=memory_name,
            request=request,
            scope=scope,
        ),
    )
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
    approval_id: str | None = Query(default=None),
    args_hash: str | None = Query(default=None),
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, str]:
    """Delete a memory."""
    _validate_memory_name(memory_name)
    require_action_approval(
        action_kind="memory.delete",
        approval_id=approval_id,
        args_hash=args_hash,
        arguments=_memory_approval_arguments(
            project_slug=project_slug,
            memory_name=memory_name,
            scope=scope,
        ),
    )
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
    require_action_approval(
        action_kind="memory.create",
        approval_id=request.approval_id,
        args_hash=request.args_hash,
        arguments=_memory_approval_arguments(project_slug=project_slug, request=request),
    )
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
