"""Core ORM models: Tenant, Conversation, Message."""

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from personagent.domain.models.tenancy import DEFAULT_TENANT_ID
from personagent.infrastructure.persistence.database import Base


class TenantORM(Base):
    """Tabela de tenants.

    Para installs single-tenant existe apenas uma linha pré-populada com
    :data:`DEFAULT_TENANT_ID`. Adicionar suporte multi-tenant real é só
    inserir novas linhas e setar ``tenant_id`` nas linhas filhas; nenhuma
    mudança de schema é necessária.
    """

    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(64), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    metadata_ = Column("metadata", JSONB, default=dict, nullable=False)


class ConversationORM(Base):
    """Tabela de conversas."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_TENANT_ID,
        index=True,
    )
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
