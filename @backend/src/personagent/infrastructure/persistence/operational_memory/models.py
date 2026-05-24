"""Dataclass models for operational memory persistence.

Extracted from ``OperationalMemoryRepository`` (Slice 1).
Pure data definitions — no behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from personagent.infrastructure.persistence.models import (
    OperationalMemoryChunkORM,
    OperationalMemoryEventORM,
)


@dataclass(slots=True)
class StoredMemoryChunk:
    """Chunk plus optional vector returned by recall."""

    chunk: OperationalMemoryChunkORM
    event: OperationalMemoryEventORM | None
    embedding: list[float] | None
    score: float = 0.0


@dataclass(slots=True)
class StoredStructuredMemoryItem:
    """Structured item returned by DB-first recall."""

    id: UUID
    project_slug: str
    item_type: str
    summary: str
    evidence: list[str]
    paths: list[str]
    source_ids: list[str]
    event_types: list[str]
    status: str
    source_type: str
    source_chunk_id: UUID | None
    primary_path: str | None
    conversation_id: UUID | None
    workspace_root: str | None
    trust_level: str
    importance: float
    created_at: Any
    distance: float | None = None
    lexical_rank: float = 0.0
    score: float = 0.0
    ranking_reasons: list[str] | None = None
