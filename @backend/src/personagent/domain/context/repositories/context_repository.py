"""Context repository interface.

Define a interface para persistência e cache de contexto.
Seguindo a Arquitetura Clean, este é um repositório no domínio,
com implementações concretas na camada de infraestrutura.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from personagent.domain.context.models import SystemContext, UserContext


class ContextRepository(ABC):
    """Interface para repositório de contexto.

    Define contratos para cache e persistência de contexto de sistema
    e usuário. Implementações concretas ficam na camada de infraestrutura.
    """

    @abstractmethod
    async def get_system_context(self, conversation_id: str) -> SystemContext | None:
        """Busca o contexto de sistema cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.

        Returns:
            SystemContext cacheado ou None se não existir.
        """
        ...

    @abstractmethod
    async def save_system_context(self, conversation_id: str, context: SystemContext) -> None:
        """Salva o contexto de sistema no cache.

        Args:
            conversation_id: ID da conversa.
            context: Contexto de sistema para salvar.
        """
        ...

    @abstractmethod
    async def get_user_context(self, conversation_id: str) -> UserContext | None:
        """Busca o contexto de usuário cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.

        Returns:
            UserContext cacheado ou None se não existir.
        """
        ...

    @abstractmethod
    async def save_user_context(self, conversation_id: str, context: UserContext) -> None:
        """Salva o contexto de usuário no cache.

        Args:
            conversation_id: ID da conversa.
            context: Contexto de usuário para salvar.
        """
        ...

    @abstractmethod
    async def clear_context(self, conversation_id: str) -> None:
        """Limpa o contexto cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.
        """
        ...

    @abstractmethod
    async def get_metadata(self, key: str) -> Any | None:
        """Busca metadados globais.

        Args:
            key: Chave do metadado.

        Returns:
            Valor do metadado ou None se não existir.
        """
        ...

    @abstractmethod
    async def set_metadata(self, key: str, value: Any) -> None:
        """Salva metadados globais.

        Args:
            key: Chave do metadado.
            value: Valor do metadado.
        """
        ...
