"""Modelos ORM do SQLAlchemy para PostgreSQL."""

import uuid

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # type: ignore

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import relationship

from personagent.infrastructure.persistence.database import Base
from personagent.infrastructure.persistence.models.core import (  # noqa: F401
    ConversationORM,
    MessageORM,
    TenantORM,
)


class MemoryFileORM(Base):
    """Metadados de arquivos de memória para queries rápidas.

    A fonte da verdade é o filesystem; esta tabela é um índice.
    """

    __tablename__ = "memory_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    memory_type = Column(
        String(20),
        nullable=True,
    )  # user, feedback, project, reference
    scope = Column(
        String(20),
        nullable=True,
    )  # private, team, project, user, local
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    mtime = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Índices para queries comuns do recall selector
        {"sqlite_autoincrement": False},
    )


class MemoryJobORM(Base):
    """Jobs de memória em background (extração, consolidação, sync)."""

    __tablename__ = "memory_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String(30), nullable=False)  # extract_memories, auto_dream, team_sync
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    project_slug = Column(Text, nullable=False)
    payload = Column(JSONB, default=dict)
    status = Column(String(20), default="pending")  # pending, running, completed, failed, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)


class MemorySessionORM(Base):
    """Sessões rastreadas para gates de consolidação (autoDream)."""

    __tablename__ = "memory_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(100), nullable=False, unique=True)
    project_slug = Column(Text, nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MemoryConsolidationLockORM(Base):
    """Lock de consolidação por projeto (prevenção de concorrência)."""

    __tablename__ = "memory_consolidation_locks"

    project_slug = Column(Text, primary_key=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    locked_by = Column(String(100), nullable=True)
    last_consolidated_at = Column(DateTime(timezone=True), server_default=func.now())


class OperationalMemoryEventORM(Base):
    """Raw operational events captured from agent execution."""

    __tablename__ = "memory_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug = Column(Text, nullable=False)
    workspace_root = Column(Text, nullable=True)
    session_id = Column(String(100), nullable=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_name = Column(String(100), nullable=True)
    event_type = Column(String(60), nullable=False)
    task = Column(Text, nullable=True)
    tool_name = Column(String(100), nullable=True)
    status = Column(String(40), nullable=True)
    input = Column(JSONB, nullable=False, default=dict)
    output = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    paths = Column(JSONB, nullable=False, default=list)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    source_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chunks = relationship(
        "OperationalMemoryChunkORM",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_memory_events_project_created", "project_slug", "created_at"),
        Index("idx_memory_events_project_type", "project_slug", "event_type"),
        Index("idx_memory_events_conversation", "conversation_id"),
    )


class OperationalMemoryChunkORM(Base):
    """Indexable memory chunks derived from events and files."""

    __tablename__ = "memory_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_events.id", ondelete="CASCADE"),
        nullable=True,
    )
    project_slug = Column(Text, nullable=False)
    source_type = Column(String(60), nullable=False)
    source_id = Column(Text, nullable=False)
    file_path = Column(Text, nullable=True)
    chunk_index = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    language = Column(String(60), nullable=True)
    symbols = Column(JSONB, nullable=False, default=list)
    imports = Column(JSONB, nullable=False, default=list)
    token_count = Column(Integer, nullable=True)
    embedding_status = Column(String(20), nullable=False, default="pending")
    embedding_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    event = relationship("OperationalMemoryEventORM", back_populates="chunks")
    if Vector is not None:
        embeddings = relationship(
            "MemoryEmbeddingORM",
            back_populates="chunk",
            cascade="all, delete-orphan",
        )

    __table_args__ = (
        Index("idx_memory_chunks_project_created", "project_slug", "created_at"),
        Index("idx_memory_chunks_project_source", "project_slug", "source_type"),
        Index("idx_memory_chunks_file_path", "file_path"),
        Index("idx_memory_chunks_hash", "content_hash"),
    )


if Vector is not None:
    class MemoryEmbeddingORM(Base):
        """Embedding vectors for operational memory chunks."""

        __tablename__ = "memory_embeddings"

        id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
        chunk_id = Column(
            UUID(as_uuid=True),
            ForeignKey("memory_chunks.id", ondelete="CASCADE"),
            nullable=False,
        )
        project_slug = Column(Text, nullable=False)
        embedding_model = Column(Text, nullable=False)
        dimensions = Column(Integer, nullable=False)
        embedding = Column(Vector(4096), nullable=False)
        content_hash = Column(String(64), nullable=False)
        created_at = Column(DateTime(timezone=True), server_default=func.now())

        chunk = relationship("OperationalMemoryChunkORM", back_populates="embeddings")

        __table_args__ = (
            Index("idx_memory_embeddings_project", "project_slug"),
            Index("idx_memory_embeddings_chunk", "chunk_id"),
            Index("idx_memory_embeddings_hash", "content_hash"),
        )
else:
    MemoryEmbeddingORM = None  # type: ignore


class StructuredMemoryItemORM(Base):
    """Prompt-facing structured operational memory derived from raw chunks."""

    __tablename__ = "memory_structured_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug = Column(Text, nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    session_id = Column(String(100), nullable=True)
    workspace_root = Column(Text, nullable=True)
    item_type = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    trust_level = Column(String(20), nullable=False, default="medium")
    importance = Column(Float, nullable=False, default=0.5)
    source_type = Column(String(60), nullable=False)
    source_id = Column(Text, nullable=False)
    source_chunk_id = Column(UUID(as_uuid=True), ForeignKey("memory_chunks.id", ondelete="CASCADE"), nullable=True)
    primary_path = Column(Text, nullable=True)
    summary = Column(Text, nullable=False)
    evidence = Column(JSONB, nullable=False, default=list)
    paths = Column(JSONB, nullable=False, default=list)
    source_ids = Column(JSONB, nullable=False, default=list)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False)
    search_text = Column(Text, nullable=False, default="")
    search_vector = Column(TSVECTOR, nullable=True)
    state_reason = Column(Text, nullable=True)
    superseded_by_id = Column(UUID(as_uuid=True), nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    ranking_metadata = Column(JSONB, nullable=False, default=dict)
    is_latest = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_memory_structured_project_created", "project_slug", "created_at"),
        Index("idx_memory_structured_project_type", "project_slug", "item_type"),
        Index("idx_memory_structured_project_latest", "project_slug", "is_latest"),
        Index("idx_memory_structured_conversation", "conversation_id"),
        Index("idx_memory_structured_session", "session_id"),
        Index("idx_memory_structured_workspace", "workspace_root"),
        Index("idx_memory_structured_source_type", "source_type"),
        Index("idx_memory_structured_primary_path", "primary_path"),
        Index("idx_memory_structured_source_chunk", "source_chunk_id"),
        Index("idx_memory_structured_hash", "content_hash"),
        Index("idx_memory_structured_status", "status"),
        Index("idx_memory_structured_trust", "trust_level"),
        Index("idx_memory_structured_search_vector", "search_vector", postgresql_using="gin"),
    )


class MemoryDecisionORM(Base):
    """Architectural decisions extracted into operational memory."""

    __tablename__ = "memory_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug = Column(Text, nullable=False)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision = Column(Text, nullable=False)
    context = Column(Text, nullable=False, default="")
    alternatives_considered = Column(JSONB, nullable=False, default=list)
    reason = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="active")
    source_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    embedding_status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_memory_decisions_project_status", "project_slug", "status"),
        Index("idx_memory_decisions_conversation", "conversation_id"),
    )


class MemoryRecallLogORM(Base):
    """Recall audit log for prompt-injected operational memory."""

    __tablename__ = "memory_recall_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_slug = Column(Text, nullable=False)
    workspace_root = Column(Text, nullable=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    recall_scope = Column(String(40), nullable=False, default="workspace")
    query_intent = Column(String(80), nullable=False, default="specific")
    query = Column(Text, nullable=False)
    filters = Column(JSONB, nullable=False, default=dict)
    result_ids = Column(JSONB, nullable=False, default=list)
    scores = Column(JSONB, nullable=False, default=dict)
    candidate_count = Column(Integer, nullable=False, default=0)
    selected_count = Column(Integer, nullable=False, default=0)
    discarded_candidates = Column(JSONB, nullable=False, default=list)
    included_reasons = Column(JSONB, nullable=False, default=list)
    ranking_breakdown = Column(JSONB, nullable=False, default=dict)
    token_usage = Column(JSONB, nullable=False, default=dict)
    budget_tokens = Column(Integer, nullable=False, default=0)
    budget_used = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    provider = Column(String(60), nullable=True)
    model = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_memory_recall_logs_project_created", "project_slug", "created_at"),
        Index("idx_memory_recall_logs_workspace_created", "workspace_root", "created_at"),
    )


class MemoryOutboxORM(Base):
    """Durable queue handoff for asynchronous operational-memory work."""

    __tablename__ = "memory_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_events.id", ondelete="CASCADE"),
        nullable=True,
    )
    project_slug = Column(Text, nullable=False)
    workspace_root = Column(Text, nullable=True)
    job_type = Column(String(80), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    dedupe_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_memory_outbox_dedupe_key"),
        Index("idx_memory_outbox_status_next_attempt", "status", "next_attempt_at"),
        Index("idx_memory_outbox_event", "event_id"),
        Index("idx_memory_outbox_project_created", "project_slug", "created_at"),
    )
