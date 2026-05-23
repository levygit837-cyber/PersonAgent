"""Implementação do ConversationRepository com PostgreSQL + SQLAlchemy."""

from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.tenancy import DEFAULT_TENANT_ID
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.infrastructure.persistence.models import ConversationORM, MessageORM


class PostgresConversationRepository(ConversationRepository):
    """Repositório de conversas persistido em PostgreSQL."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, conversation: Conversation) -> Conversation:
        """Cria uma nova conversa no banco de dados."""
        orm = ConversationORM(
            id=conversation.id,
            tenant_id=conversation.tenant_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            model_config_id=conversation.model_config_id,
            metadata_=conversation.metadata,
        )
        self._session.add(orm)
        for msg in conversation.messages:
            self._session.add(self._message_orm(conversation.id, msg))
        await self._session.commit()
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        """Recupera uma conversa pelo ID."""
        result = await self._session.execute(
            select(ConversationORM)
            .options(selectinload(ConversationORM.messages))
            .where(ConversationORM.id == conversation_id)
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return self._to_domain(orm)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """Lista conversas com paginação, ordenadas por updated_at decrescente."""
        result = await self._session.execute(
            select(ConversationORM)
            .options(selectinload(ConversationORM.messages))
            .order_by(ConversationORM.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(orm) for orm in result.scalars().all()]

    async def list_summaries(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Lista conversas sem carregar conteúdo/metadata de mensagens."""
        result = await self._session.execute(
            select(
                ConversationORM.id,
                ConversationORM.title,
                ConversationORM.created_at,
                ConversationORM.updated_at,
                ConversationORM.metadata_,
                func.count(MessageORM.id).label("message_count"),
            )
            .outerjoin(MessageORM, MessageORM.conversation_id == ConversationORM.id)
            .group_by(ConversationORM.id)
            .order_by(ConversationORM.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "message_count": int(row.message_count or 0),
                "workspace_root": _workspace_root_from_metadata(row.metadata_),
                "status": _conversation_status_from_metadata(row.metadata_),
            }
            for row in result
        ]

    async def update(self, conversation: Conversation) -> Conversation:
        """Atualiza uma conversa existente sem regravar mensagens antigas."""
        # Busca a conversa existente
        result = await self._session.execute(
            select(ConversationORM).where(ConversationORM.id == conversation.id)
        )
        orm = result.scalar_one_or_none()

        if not orm:
            # Cria se não existir
            return await self.create(conversation)

        # Atualiza campos
        orm.title = conversation.title
        orm.updated_at = conversation.updated_at
        orm.model_config_id = conversation.model_config_id
        orm.metadata_ = conversation.metadata

        result = await self._session.execute(
            select(
                MessageORM.id,
                MessageORM.timestamp,
                MessageORM.role,
                MessageORM.tool_call_id,
            ).where(MessageORM.conversation_id == conversation.id)
        )
        existing_by_key = {
            (row.timestamp, row.role, row.tool_call_id or ""): row.id for row in result
        }
        incoming_keys = set()

        for msg in conversation.messages:
            key = self._message_key(msg)
            incoming_keys.add(key)
            if key in existing_by_key:
                continue
            self._session.add(self._message_orm(conversation.id, msg))

        stale_ids = [
            message_id for key, message_id in existing_by_key.items() if key not in incoming_keys
        ]
        if stale_ids:
            await self._session.execute(delete(MessageORM).where(MessageORM.id.in_(stale_ids)))

        await self._session.commit()
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        """Remove uma conversa pelo ID."""
        result = await self._session.execute(
            select(ConversationORM).where(ConversationORM.id == conversation_id)
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return False

        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        """Busca conversas por título ou conteúdo de mensagens."""
        result = await self._session.execute(
            select(ConversationORM)
            .options(selectinload(ConversationORM.messages))
            .where(
                or_(
                    ConversationORM.title.ilike(f"%{query}%"),
                    ConversationORM.messages.any(MessageORM.content.ilike(f"%{query}%")),
                )
            )
            .order_by(ConversationORM.updated_at.desc())
            .limit(limit)
        )
        return [self._to_domain(orm) for orm in result.scalars().all()]

    async def search_summaries(self, query: str, limit: int = 10) -> list[dict]:
        """Busca conversas retornando apenas campos de listagem."""
        result = await self._session.execute(
            select(
                ConversationORM.id,
                ConversationORM.title,
                ConversationORM.created_at,
                ConversationORM.updated_at,
                ConversationORM.metadata_,
                func.count(MessageORM.id).label("message_count"),
            )
            .outerjoin(MessageORM, MessageORM.conversation_id == ConversationORM.id)
            .where(
                or_(
                    ConversationORM.title.ilike(f"%{query}%"),
                    ConversationORM.messages.any(MessageORM.content.ilike(f"%{query}%")),
                )
            )
            .group_by(ConversationORM.id)
            .order_by(ConversationORM.updated_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "message_count": int(row.message_count or 0),
                "workspace_root": _workspace_root_from_metadata(row.metadata_),
                "status": _conversation_status_from_metadata(row.metadata_),
            }
            for row in result
        ]

    def _to_domain(self, orm: ConversationORM) -> Conversation:
        """Converte um ORM para modelo de domínio."""
        messages = [
            Message(
                role=Role(msg.role),
                content=msg.content,
                timestamp=msg.timestamp,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                metadata=msg.metadata_ or {},
            )
            for msg in orm.messages
        ]

        return Conversation(
            id=orm.id,
            title=orm.title,
            messages=messages,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            model_config_id=orm.model_config_id,
            metadata=orm.metadata_ or {},
            tenant_id=orm.tenant_id or DEFAULT_TENANT_ID,
        )

    def _message_orm(self, conversation_id: UUID, msg: Message) -> MessageORM:
        return MessageORM(
            conversation_id=conversation_id,
            role=msg.role.value,
            content=msg.content,
            timestamp=msg.timestamp,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            metadata_=msg.metadata,
        )

    def _message_key(self, msg: Message) -> tuple:
        return (msg.timestamp, msg.role.value, msg.tool_call_id or "")

    def _message_key_from_orm(self, msg: MessageORM) -> tuple:
        return (msg.timestamp, msg.role, msg.tool_call_id or "")


def _workspace_root_from_metadata(metadata: dict | None) -> str | None:
    value = (metadata or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _conversation_status_from_metadata(metadata: dict | None) -> str:
    data = metadata or {}
    status = data.get("session_status")
    if status in {"idle", "error", "pending", "running"}:
        return str(status)
    pending_tool = data.get("pending_tool_approval")
    if isinstance(pending_tool, dict) and pending_tool.get("status") == "awaiting_approval":
        return "pending"
    plan_mode = data.get("plan_mode")
    if isinstance(plan_mode, dict) and plan_mode.get("status") == "awaiting_approval":
        return "pending"
    return "idle"
