"""Database session and repository mixin."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from personagent.domain.conversation.repositories import ConversationRepository
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)


class _DatabaseMixin:
    async def get_db_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Return a database session."""
        session = AsyncSessionLocal()
        try:
            yield session
        finally:
            await session.close()

    async def get_conversation_repo(self, session: AsyncSession) -> ConversationRepository:
        """Return the conversation repository."""
        return PostgresConversationRepository(session)
