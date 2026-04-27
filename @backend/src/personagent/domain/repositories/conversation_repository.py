"""Porta (interface) para persistência de conversas."""

from abc import ABC, abstractmethod
from uuid import UUID

from personagent.domain.models.conversation import Conversation


class ConversationRepository(ABC):
    """Interface para operações de persistência de conversas."""

    @abstractmethod
    async def create(self, conversation: Conversation) -> Conversation:
        """Cria uma nova conversa."""
        ...

    @abstractmethod
    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        """Recupera uma conversa pelo ID."""
        ...

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """Lista todas as conversas com paginação."""
        ...

    @abstractmethod
    async def update(self, conversation: Conversation) -> Conversation:
        """Atualiza uma conversa existente."""
        ...

    @abstractmethod
    async def delete(self, conversation_id: UUID) -> bool:
        """Remove uma conversa pelo ID."""
        ...

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        """Busca conversas por conteúdo."""
        ...
