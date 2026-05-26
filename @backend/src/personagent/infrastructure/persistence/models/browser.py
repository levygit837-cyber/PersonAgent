"""Browser-related ORM models."""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from personagent.infrastructure.persistence.database import Base


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
