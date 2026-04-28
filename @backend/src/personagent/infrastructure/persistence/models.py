"""Modelos ORM do SQLAlchemy para PostgreSQL."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from personagent.infrastructure.persistence.database import Base


class ConversationORM(Base):
    """Tabela de conversas."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    model_config_id = Column(String(50), default="default")
    metadata_ = Column("metadata", JSONB, default=dict)

    messages = relationship(
        "MessageORM",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageORM.timestamp",
    )


class MessageORM(Base):
    """Tabela de mensagens."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    tool_calls = Column(JSONB, nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    conversation = relationship("ConversationORM", back_populates="messages")


class LabGraphORM(Base):
    """Tabela de grafos do Lab."""

    __tablename__ = "lab_graphs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="Untitled Lab Graph")
    graph = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationship with workflow runs
    runs = relationship(
        "WorkflowRunORM",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowRunORM.started_at.desc()",
    )


class WorkflowRunORM(Base):
    """Tabela de execuções de workflows."""

    __tablename__ = "workflow_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lab_graphs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger_mode = Column(String(20), default="manual")  # manual, cron, api
    status = Column(String(20), default="running")  # running, completed, failed
    input = Column(JSONB, nullable=True)
    output = Column(JSONB, nullable=True)
    trace_events = Column(JSONB, default=list)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    workflow = relationship("LabGraphORM", back_populates="runs")


class TeamRunORM(Base):
    """Tabela de execuções do Team Mode multi-agentes."""

    __tablename__ = "team_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(String(100), nullable=True, unique=True)
    workspace_id = Column(Text, nullable=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status = Column(String(20), nullable=False, default="running")
    team_config = Column(JSONB, nullable=False, default=dict)
    trace_events = Column(JSONB, nullable=False, default=list)
    blackboard_snapshot = Column(JSONB, nullable=True)
    final_output = Column(Text, nullable=True)
    consensus = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)


class TeamBlackboardEventORM(Base):
    """Journal persistente do Blackboard de uma execução Team Mode."""

    __tablename__ = "team_blackboard_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(String(100), nullable=False)
    workspace_id = Column(Text, nullable=True)
    conversation_id = Column(
        UUID(as_uuid=True),
        nullable=True,
    )
    sequence = Column(Integer, nullable=False)
    phase = Column(String(40), nullable=False)
    round = Column(Integer, nullable=True)
    agent_id = Column(String(100), nullable=True)
    event_type = Column(String(60), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TeamMemorySnapshotORM(Base):
    """Snapshot persistente do claim graph por workspace."""

    __tablename__ = "team_memory_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(Text, nullable=False, unique=True)
    snapshot = Column(JSONB, nullable=False, default=dict)
    last_run_id = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TaskRecordORM(Base):
    """Tabela de tarefas criadas pelas ferramentas Task*."""

    __tablename__ = "task_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(String(100), nullable=True)
    workspace_root = Column(Text, nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(30), nullable=False, default="open")
    priority = Column(String(30), nullable=False, default="normal")
    output = Column(Text, nullable=False, default="")
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    query = Column(Text, nullable=False)
    filters = Column(JSONB, nullable=False, default=dict)
    result_ids = Column(JSONB, nullable=False, default=list)
    scores = Column(JSONB, nullable=False, default=dict)
    latency_ms = Column(Integer, nullable=False, default=0)
    provider = Column(String(60), nullable=True)
    model = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_memory_recall_logs_project_created", "project_slug", "created_at"),
    )
