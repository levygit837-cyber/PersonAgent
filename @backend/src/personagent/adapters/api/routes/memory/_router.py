"""FastAPI memory management router and shared utilities."""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from personagent.adapters.composition import get_container
from personagent.domain.memory.models.memory_types import MemoryScope
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.infrastructure.persistence.memory import (
    FileSystemMemoryRepository,
)

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
        payload.pop("approval_signature", None)
        payload.pop("expires_at", None)
        data["request"] = payload
    return data
