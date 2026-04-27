"""Modelos ORM do SQLAlchemy para PostgreSQL."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from personagent.infrastructure.persistence.database import Base


class ConversationORM(Base):
    """Tabela de conversas."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="Nova Conversa")
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
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(20), nullable=False, default="running")
    team_config = Column(JSONB, nullable=False, default=dict)
    trace_events = Column(JSONB, nullable=False, default=list)
    final_output = Column(Text, nullable=True)
    consensus = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)


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
