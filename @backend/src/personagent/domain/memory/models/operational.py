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
    TEST_RESULT = "test_result"
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


class MemoryItemStatus(StrEnum):
    """Lifecycle of prompt-facing operational memory items."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    STALE = "stale"


class StructuredMemoryType(StrEnum):
    """Prompt-facing operational memory layers."""

    FACT = "fact"
    DECISION = "decision"
    LATEST_STATE = "latest_state"
    SESSION_SUMMARY = "session_summary"
    ERROR_SOLUTION = "error_solution"
    FILE_STATE = "file_state"
    COMMAND_RESULT = "command_result"
    TEST_RESULT = "test_result"
    TOOL_TRACE = "tool_trace"


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


@dataclass(slots=True)
class OperationalMemoryFilter:
    """Filters applied before operational-memory ANN/recent retrieval."""

    conversation_id: str | None = None
    current_conversation_id: str | None = None
    session_id: str | None = None
    workspace_root: str | None = None
    source_types: list[str] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None
    latest_only: bool = False
    active_only: bool = True
    statuses: list[str] = field(default_factory=list)
    include_raw_chunks: bool = False
    semantic_candidate_limit: int = 80
    recent_candidate_limit: int = 40

    @classmethod
    def from_mapping(cls, filters: dict[str, Any] | None) -> OperationalMemoryFilter:
        data = filters or {}
        return cls(
            conversation_id=_string_or_none(data.get("conversation_id")),
            current_conversation_id=_string_or_none(data.get("current_conversation_id")),
            session_id=_string_or_none(data.get("session_id")),
            workspace_root=_string_or_none(data.get("workspace_root")),
            source_types=_string_list(data.get("source_types") or data.get("source_type")),
            file_paths=_string_list(data.get("file_paths") or data.get("file_path")),
            created_after=_datetime_or_none(data.get("created_after")),
            created_before=_datetime_or_none(data.get("created_before")),
            latest_only=bool(data.get("latest_only", False)),
            active_only=bool(data.get("active_only", True)),
            statuses=_string_list(data.get("statuses") or data.get("include_statuses")),
            include_raw_chunks=bool(data.get("include_raw_chunks", False)),
            semantic_candidate_limit=max(1, int(data.get("semantic_candidate_limit") or 80)),
            recent_candidate_limit=max(0, int(data.get("recent_candidate_limit") or 40)),
        )

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "current_conversation_id": self.current_conversation_id,
            "session_id": self.session_id,
            "workspace_root": self.workspace_root,
            "source_types": list(self.source_types),
            "file_paths": list(self.file_paths),
            "created_after": self.created_after.isoformat() if self.created_after else None,
            "created_before": self.created_before.isoformat() if self.created_before else None,
            "latest_only": self.latest_only,
            "active_only": self.active_only,
            "statuses": list(self.statuses),
            "include_raw_chunks": self.include_raw_chunks,
            "semantic_candidate_limit": self.semantic_candidate_limit,
            "recent_candidate_limit": self.recent_candidate_limit,
        }


@dataclass(slots=True)
class MemoryContextBudget:
    """Strict prompt budget for operational memory context."""

    total_tokens: int
    session_summary_tokens: int
    latest_decision_tokens: int
    fact_tokens: int
    evidence_tokens: int
    evidence_max_chars: int = 350

    @classmethod
    def for_context_window(
        cls,
        context_window_tokens: int,
        *,
        total_tokens: int | None = None,
    ) -> MemoryContextBudget:
        total = int(total_tokens or min(2_400, max(800, context_window_tokens * 0.015)))
        session = max(1, int(total * 0.25))
        latest = max(1, int(total * 0.30))
        fact = max(1, int(total * 0.30))
        evidence = max(1, total - session - latest - fact)
        return cls(
            total_tokens=total,
            session_summary_tokens=session,
            latest_decision_tokens=latest,
            fact_tokens=fact,
            evidence_tokens=evidence,
        )


@dataclass(slots=True)
class StructuredMemoryItem:
    """Structured memory item ready for prompt formatting."""

    type: StructuredMemoryType
    summary: str
    evidence: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    score: float = 0.0
    status: str = "active"
    trust_level: str = "medium"
    importance: float = 0.5
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def estimated_tokens(self) -> int:
        text = " ".join([self.summary, *self.evidence, *self.paths, *self.source_ids])
        return max(1, (len(text) + 3) // 4)


@dataclass(slots=True)
class StructuredMemoryPackage:
    """Formatted operational memory plus metadata for APIs and prompt telemetry."""

    formatted: str
    items: list[StructuredMemoryItem]
    filters_applied: dict[str, Any]
    budget_used: int
    budget_tokens: int
    omitted_count: int
    latency_ms: int
    recall_scope: str = "workspace"
    query_intent: str = "specific"
    candidate_count: int = 0
    discarded_candidates: list[dict[str, Any]] = field(default_factory=list)
    included_reasons: list[dict[str, Any]] = field(default_factory=list)
    ranking_breakdown: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "memory_budget_tokens": self.budget_tokens,
            "memory_budget_used": self.budget_used,
            "memory_items_injected": len(self.items),
            "memory_items_omitted": self.omitted_count,
            "memory_latency_ms": self.latency_ms,
            "memory_filters_applied": self.filters_applied,
            "memory_recall_scope": self.recall_scope,
            "memory_query_intent": self.query_intent,
            "memory_candidate_count": self.candidate_count,
            "memory_discarded_candidates": self.discarded_candidates,
            "memory_included_reasons": self.included_reasons,
            "memory_ranking_breakdown": self.ranking_breakdown,
            "memory_token_usage": self.token_usage,
        }


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
