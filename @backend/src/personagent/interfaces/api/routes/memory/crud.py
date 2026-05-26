"""Core memory CRUD API routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.interfaces.api.action_approvals import require_action_approval
from personagent.interfaces.api.routes.memory._router import (
    MEMORY_REPO_DEPENDENCY,
    MEMORY_TYPE_QUERY,
    PRIVATE_SCOPE_QUERY,
    _memory_approval_arguments,
    _validate_memory_name,
    logger,
    router,
)
from personagent.interfaces.api.routes.memory.models import (
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
)

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
        approval_signature=request.approval_signature,
        expires_at=request.expires_at,
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
    approval_signature: str | None = Query(default=None),
    expires_at: int | None = Query(default=None),
    repo: MemoryRepository = MEMORY_REPO_DEPENDENCY,
) -> dict[str, str]:
    """Delete a memory."""
    _validate_memory_name(memory_name)
    require_action_approval(
        action_kind="memory.delete",
        approval_id=approval_id,
        args_hash=args_hash,
        approval_signature=approval_signature,
        expires_at=expires_at,
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
        approval_signature=request.approval_signature,
        expires_at=request.expires_at,
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
