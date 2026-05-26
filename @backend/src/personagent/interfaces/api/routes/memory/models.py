"""Pydantic models for memory API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType


class MemoryCreateRequest(BaseModel):
    """Request for memory creation."""

    name: str = Field(..., description="Memory snake_case name")
    description: str = Field(..., description="Memory description")
    content: str = Field(..., description="Memory Markdown content")
    memory_type: MemoryType = Field(default=MemoryType.PROJECT, description="Memory type")
    scope: MemoryScope = Field(default=MemoryScope.PRIVATE, description="Persistence scope")
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


class MemoryUpdateRequest(BaseModel):
    """Request for memory updates."""

    description: str | None = Field(default=None, description="New description")
    content: str | None = Field(default=None, description="New content")
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


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
