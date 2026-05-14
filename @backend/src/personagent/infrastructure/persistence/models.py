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


class BrowserWorkspaceORM(Base):
    """Persisted Browser Workspace state scoped to one conversation/browser."""

    __tablename__ = "browser_workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    browser_id = Column(String(120), nullable=False)
    workspace_id = Column(Text, nullable=True)
    active_runtime = Column(String(40), nullable=False, default="lightpanda")
    active_tab_id = Column(String(160), nullable=True)
    current_url = Column(Text, nullable=True)
    current_title = Column(Text, nullable=True)
    state = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tabs = relationship(
        "BrowserTabORM",
        back_populates="browser_workspace",
        cascade="all, delete-orphan",
    )
    annotations = relationship(
        "BrowserAnnotationORM",
        back_populates="browser_workspace",
        cascade="all, delete-orphan",
    )
    timeline_events = relationship(
        "BrowserTimelineEventORM",
        back_populates="browser_workspace",
        cascade="all, delete-orphan",
    )
    cooperation_events = relationship(
        "BrowserCooperationEventORM",
        back_populates="browser_workspace",
        cascade="all, delete-orphan",
    )
    automation_runs = relationship(
        "BrowserAutomationRunORM",
        back_populates="browser_workspace",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", "browser_id", name="uq_browser_workspace_conversation_browser"),
        Index("idx_browser_workspaces_conversation", "conversation_id"),
    )


class BrowserTabORM(Base):
    """Real browser tab tracked inside a Browser Workspace."""

    __tablename__ = "browser_tabs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    browser_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    tab_id = Column(String(160), nullable=False)
    url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    runtime = Column(String(40), nullable=False, default="lightpanda")
    is_active = Column(Boolean, nullable=False, default=False)
    history = Column(JSONB, nullable=False, default=list)
    state = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    browser_workspace = relationship("BrowserWorkspaceORM", back_populates="tabs")

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "tab_id", name="uq_browser_tabs_workspace_tab"),
        Index("idx_browser_tabs_workspace_active", "browser_workspace_id", "is_active"),
    )


class BrowserAnnotationORM(Base):
    """Annotation anchored to a mapped browser element."""

    __tablename__ = "browser_annotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    annotation_id = Column(String(120), nullable=False)
    browser_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    tab_id = Column(String(160), nullable=True)
    node_id = Column(String(240), nullable=False)
    url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    selector = Column(Text, nullable=True)
    frame_id = Column(String(160), nullable=True)
    selector_chain = Column(JSONB, nullable=False, default=list)
    shadow_path = Column(JSONB, nullable=False, default=list)
    body = Column(Text, nullable=False)
    quote = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    browser_workspace = relationship("BrowserWorkspaceORM", back_populates="annotations")

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "annotation_id", name="uq_browser_annotations_workspace_annotation"),
        Index("idx_browser_annotations_workspace_tab", "browser_workspace_id", "tab_id"),
        Index("idx_browser_annotations_node", "node_id"),
    )


class BrowserTimelineEventORM(Base):
    """Append-only Browser Workspace timeline event."""

    __tablename__ = "browser_timeline_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String(120), nullable=False)
    browser_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    tab_id = Column(String(160), nullable=True)
    source = Column(String(30), nullable=False)
    event_type = Column(String(80), nullable=False)
    label = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    sequence = Column(Integer, nullable=False, default=0)
    automation_run_id = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    browser_workspace = relationship("BrowserWorkspaceORM", back_populates="timeline_events")

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "event_id", name="uq_browser_timeline_workspace_event"),
        Index("idx_browser_timeline_workspace_sequence", "browser_workspace_id", "sequence"),
        Index("idx_browser_timeline_workspace_tab", "browser_workspace_id", "tab_id"),
    )


class BrowserCooperationEventORM(Base):
    """Append-only normalized/redacted Browser Cooperation event log."""

    __tablename__ = "browser_cooperation_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String(120), nullable=False)
    browser_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    browser_id = Column(String(120), nullable=False)
    tab_id = Column(String(160), nullable=True)
    page_id = Column(String(160), nullable=True)
    source = Column(String(30), nullable=False, default="user")
    channel = Column(String(40), nullable=False, default="event")
    trace_role = Column(String(30), nullable=False, default="user")
    visibility = Column(String(30), nullable=False, default="raw")
    raw_kind = Column(String(120), nullable=True)
    kind = Column(String(80), nullable=False)
    url = Column(Text, nullable=True)
    target = Column(JSONB, nullable=False, default=dict)
    payload = Column(JSONB, nullable=False, default=dict)
    coordinates = Column(JSONB, nullable=False, default=dict)
    duration_ms = Column(Integer, nullable=True)
    trace_effect = Column(String(80), nullable=True)
    correlation_id = Column(String(120), nullable=True)
    importance = Column(String(30), nullable=False, default="low")
    semantic_label = Column(Text, nullable=True)
    sequence = Column(Integer, nullable=False, default=0)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    browser_workspace = relationship("BrowserWorkspaceORM", back_populates="cooperation_events")

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "event_id", name="uq_browser_cooperation_workspace_event"),
        Index("idx_browser_cooperation_workspace_sequence", "browser_workspace_id", "sequence"),
        Index("idx_browser_cooperation_conversation_created", "conversation_id", "created_at"),
        Index("idx_browser_cooperation_workspace_kind", "browser_workspace_id", "kind"),
        Index("idx_browser_cooperation_workspace_correlation", "browser_workspace_id", "correlation_id"),
    )

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "event_id", name="uq_browser_cooperation_workspace_event"),
        Index("idx_browser_cooperation_workspace_sequence", "browser_workspace_id", "sequence"),
        Index("idx_browser_cooperation_conversation_created", "conversation_id", "created_at"),
        Index("idx_browser_cooperation_workspace_kind", "browser_workspace_id", "kind"),
    )


class BrowserAutomationRunORM(Base):
    """Persisted browser automation run for replay/edit workflows."""

    __tablename__ = "browser_automation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(String(120), nullable=False)
    browser_workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    tab_id = Column(String(160), nullable=True)
    status = Column(String(40), nullable=False, default="pending")
    title = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    browser_workspace = relationship("BrowserWorkspaceORM", back_populates="automation_runs")
    steps = relationship(
        "BrowserAutomationStepORM",
        back_populates="automation_run",
        cascade="all, delete-orphan",
        order_by="BrowserAutomationStepORM.sequence",
    )

    __table_args__ = (
        UniqueConstraint("browser_workspace_id", "run_id", name="uq_browser_automation_runs_workspace_run"),
        Index("idx_browser_automation_runs_workspace_status", "browser_workspace_id", "status"),
    )


class BrowserAutomationStepORM(Base):
    """One replayable action step inside a browser automation run."""

    __tablename__ = "browser_automation_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    automation_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("browser_automation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id = Column(String(120), nullable=False)
    sequence = Column(Integer, nullable=False)
    action = Column(String(80), nullable=False)
    target = Column(JSONB, nullable=False, default=dict)
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(40), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    snapshot_ref = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    automation_run = relationship("BrowserAutomationRunORM", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("automation_run_id", "step_id", name="uq_browser_automation_steps_run_step"),
        Index("idx_browser_automation_steps_run_sequence", "automation_run_id", "sequence"),
    )


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
