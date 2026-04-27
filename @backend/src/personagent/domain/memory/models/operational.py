"""Contracts for persistent operational RAG memory.

This module intentionally stores only provider-visible reasoning fields and
system-generated operational summaries. Private chain-of-thought is not a
memory source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class OperationalMemoryEventType(StrEnum):
    """Event classes indexed by the operational memory pipeline."""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FILE_CREATED = "file_created"
    FILE_EDITED = "file_edited"
    FILE_READ = "file_read"
    DIFF_APPLIED = "diff_applied"
    COMMAND_EXECUTED = "command_executed"
    ERROR_FOUND = "error_found"
    SOLUTION_ATTEMPTED = "solution_attempted"
    DEPENDENCY_INSTALLED = "dependency_installed"
    DECISION = "decision"
    AGENT_STATE = "agent_state"
    OPERATIONAL_SUMMARY = "operational_summary"


class EmbeddingStatus(StrEnum):
    """Lifecycle of a memory chunk embedding."""

    PENDING = "pending"
    EMBEDDED = "embedded"
    STALE = "stale"
    FAILED = "failed"
    SKIPPED = "skipped"


class DecisionStatus(StrEnum):
    """Architectural decision lifecycle."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(slots=True)
class MemoryEvent:
    """Raw operational event captured during an agent turn."""

    project_slug: str
    event_type: OperationalMemoryEventType
    workspace_root: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    agent_name: str | None = None
    task: str | None = None
    tool_name: str | None = None
    status: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    resolution: str | None = None
    paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_hash: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class MemoryChunk:
    """Indexable chunk derived from an operational event or current file."""

    project_slug: str
    source_type: str
    source_id: str
    content: str
    chunk_index: int = 0
    file_path: str | None = None
    content_hash: str | None = None
    language: str | None = None
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    token_count: int | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    embedding_error: str | None = None
    event_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class MemoryEmbedding:
    """Embedding vector associated with a memory chunk."""

    chunk_id: UUID
    project_slug: str
    embedding_model: str
    dimensions: int
    embedding: list[float]
    content_hash: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class DecisionMemory:
    """Persistent architectural or workflow decision."""

    project_slug: str
    decision: str
    context: str = ""
    alternatives_considered: list[str] = field(default_factory=list)
    reason: str = ""
    status: DecisionStatus = DecisionStatus.ACTIVE
    conversation_id: str | None = None
    source_event_id: UUID | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class FileChunk:
    """Current-file chunk contract for codebase memory."""

    project_slug: str
    file_path: str
    chunk: str
    hash: str
    language: str | None = None
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    last_modified: datetime | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    embedding: list[float] | None = None


@dataclass(slots=True)
class DiffMemory:
    """Diff memory contract."""

    project_slug: str
    file_path: str
    diff: str
    reason: str = ""
    agent_name: str | None = None
    commit: str | None = None
    session_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING


@dataclass(slots=True)
class ExecutionMemory:
    """Tool and agent execution memory contract."""

    project_slug: str
    agent: str | None
    task: str | None
    tool_call: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    resolution: str | None = None
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING


@dataclass(slots=True)
class RecallFinding:
    """Structured result injected into the agent context."""

    finding: str
    source_ids: list[str]
    evidence: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    score: float = 0.0
    event_types: list[str] = field(default_factory=list)
    created_at: datetime | None = None

