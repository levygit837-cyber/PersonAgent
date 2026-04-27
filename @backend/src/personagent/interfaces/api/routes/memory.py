"""Rotas de gerenciamento de memória da API FastAPI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import re

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_formatter import MemoryFormatter
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)
from personagent.interfaces.config.di_container import DIContainer, get_container

router = APIRouter(prefix="/memory", tags=["memory"])
logger = structlog.get_logger(__name__)

# Reutilizado para validação de nomes
_NAME_VALIDATOR = MemoryScanner()
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def get_memory_repo() -> MemoryRepository:
    """Factory para repositório de memória."""
    return FileSystemMemoryRepository()


class MemoryCreateRequest(BaseModel):
    """Request para criação de memória."""

    name: str = Field(..., description="Nome snake_case da memória")
    description: str = Field(..., description="Descrição da memória")
    content: str = Field(..., description="Conteúdo Markdown da memória")
    memory_type: MemoryType = Field(default=MemoryType.PROJECT, description="Tipo de memória")
    scope: MemoryScope = Field(default=MemoryScope.PRIVATE, description="Escopo de persistência")


class MemoryUpdateRequest(BaseModel):
    """Request para atualização de memória."""

    description: str | None = Field(default=None, description="Nova descrição")
    content: str | None = Field(default=None, description="Novo conteúdo")


class MemoryResponse(BaseModel):
    """Response com dados de uma memória."""

    path: str
    name: str
    description: str
    memory_type: str
    scope: str
    content: str
    mtime_ms: int
    is_truncated: bool = False


class MemoryListResponse(BaseModel):
    """Response com lista de memórias."""

    memories: list[dict[str, Any]]
    count: int


def _validate_memory_name(name: str) -> None:
    """Valida que o nome de memória segue snake_case e é seguro para filesystem."""
    if not name:
        raise HTTPException(status_code=400, detail="Memory name cannot be empty")
    if not _SNAKE_CASE_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"Memory name must be snake_case (got: {name})",
        )
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Memory name contains invalid characters")


# IMPORTANTE: rotas mais específicas devem vir ANTES das rotas com path params genéricos
# FastAPI resolve na ordem de definição.


@router.get("/{project_slug}/index")
async def get_memory_index(
    project_slug: str,
    scope: MemoryScope = Query(default=MemoryScope.PRIVATE),
    repo: MemoryRepository = Depends(get_memory_repo),
) -> dict[str, Any]:
    """Lê o MEMORY.md de um projeto."""
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
    scope: MemoryScope = Query(default=MemoryScope.PRIVATE),
    repo: MemoryRepository = Depends(get_memory_repo),
) -> MemoryResponse:
    """Lê uma memória específica."""
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
    scope: MemoryScope = Query(default=MemoryScope.PRIVATE),
    repo: MemoryRepository = Depends(get_memory_repo),
) -> dict[str, str]:
    """Atualiza uma memória existente."""
    _validate_memory_name(memory_name)
    from personagent.domain.memory.models.memory_file import MemoryFile

    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    file_path = memory_dir / f"{memory_name}.md"

    existing = await repo.read(file_path)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Merge frontmatter: preserva extras, atualiza name/description/type
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
    scope: MemoryScope = Query(default=MemoryScope.PRIVATE),
    repo: MemoryRepository = Depends(get_memory_repo),
) -> dict[str, str]:
    """Remove uma memória."""
    _validate_memory_name(memory_name)
    memory_dir = await repo.get_memory_dir(project_slug, scope=scope)
    file_path = memory_dir / f"{memory_name}.md"

    deleted = await repo.delete(file_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Atualiza índice
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
    repo: MemoryRepository = Depends(get_memory_repo),
) -> dict[str, str]:
    """Cria uma nova memória."""
    _validate_memory_name(request.name)
    from personagent.domain.memory.models.memory_file import MemoryFile

    memory_dir = await repo.get_memory_dir(project_slug, scope=request.scope)
    file_path = memory_dir / f"{request.name}.md"

    # Verifica duplicata
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

    # Atualiza índice
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
    scope: MemoryScope = Query(default=MemoryScope.PRIVATE),
    memory_type: MemoryType | None = Query(default=None),
    repo: MemoryRepository = Depends(get_memory_repo),
) -> MemoryListResponse:
    """Lista memórias de um projeto."""
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
