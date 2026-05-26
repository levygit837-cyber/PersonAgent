"""Team mode and QA debugging ORM models."""

import uuid

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB, UUID

from personagent.infrastructure.persistence.database import Base


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


class QASessionORM(Base):
    """Sandboxed QA debugging session."""

    __tablename__ = "qa_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_root = Column(Text, nullable=False)
    sandbox_path = Column(Text, nullable=True)
    base_commit = Column(String(80), nullable=True)
    branch_name = Column(Text, nullable=True)
    branch_mode = Column(String(30), nullable=False, default="current")
    env_profile = Column(JSONB, nullable=True)
    trace_mode = Column(String(30), nullable=False, default="function")
    agent_id = Column(String(120), nullable=True)
    status = Column(String(30), nullable=False, default="active")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_qa_sessions_repo_created", "repo_root", "created_at"),
        Index("idx_qa_sessions_agent", "agent_id"),
    )


class QACodeNodeORM(Base):
    """Static code graph node for a QA session."""

    __tablename__ = "qa_code_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False)
    node_key = Column(String(80), nullable=False)
    kind = Column(String(40), nullable=False)
    name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("session_id", "node_key", name="uq_qa_code_nodes_session_key"),
        Index("idx_qa_code_nodes_session_kind", "session_id", "kind"),
        Index("idx_qa_code_nodes_file", "file_path"),
    )


class QACodeEdgeORM(Base):
    """Static code graph edge for a QA session."""

    __tablename__ = "qa_code_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False)
    edge_key = Column(String(80), nullable=False)
    kind = Column(String(40), nullable=False)
    source_node_key = Column(String(80), nullable=False)
    target_node_key = Column(String(80), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("session_id", "edge_key", name="uq_qa_code_edges_session_key"),
        Index("idx_qa_code_edges_session_kind", "session_id", "kind"),
        Index("idx_qa_code_edges_source", "source_node_key"),
        Index("idx_qa_code_edges_target", "target_node_key"),
    )


class QARequestRunORM(Base):
    """One QA request executed under runtime tracing."""

    __tablename__ = "qa_request_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False)
    method = Column(String(20), nullable=False)
    path = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="running")
    trace_id = Column(String(40), nullable=False, default="")
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    request_payload = Column(JSONB, nullable=False, default=dict)
    response_payload = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_qa_request_runs_session_created", "session_id", "created_at"),
        Index("idx_qa_request_runs_trace", "trace_id"),
    )


class QARuntimeEventORM(Base):
    """Append-only event captured from real backend execution."""

    __tablename__ = "qa_runtime_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(UUID(as_uuid=True), ForeignKey("qa_request_runs.id", ondelete="CASCADE"), nullable=True)
    event_key = Column(String(80), nullable=False)
    sequence = Column(Integer, nullable=False)
    trace_id = Column(String(40), nullable=False)
    span_id = Column(String(20), nullable=True)
    parent_id = Column(String(20), nullable=True)
    event_type = Column(String(40), nullable=False)
    function = Column(Text, nullable=True)
    file_path = Column(Text, nullable=True)
    line = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    exception = Column(Text, nullable=True)
    sanitized_payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("session_id", "request_id", "event_key", name="uq_qa_runtime_events_request_key"),
        Index("idx_qa_runtime_events_session_sequence", "session_id", "sequence"),
        Index("idx_qa_runtime_events_request_sequence", "request_id", "sequence"),
        Index("idx_qa_runtime_events_trace", "trace_id"),
        Index("idx_qa_runtime_events_file_line", "file_path", "line"),
    )


class QAArtifactORM(Base):
    """Generated QA artifact such as coverage snapshots or exported traces."""

    __tablename__ = "qa_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("qa_sessions.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(UUID(as_uuid=True), ForeignKey("qa_request_runs.id", ondelete="SET NULL"), nullable=True)
    artifact_type = Column(String(60), nullable=False)
    path = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_qa_artifacts_session_type", "session_id", "artifact_type"),
    )
