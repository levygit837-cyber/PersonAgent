"""In-memory context repository implementation.

Implementação concreta do ContextRepository usando cache em memória.
Adequado para desenvolvimento e testes. Para produção, considere
implementação com Redis ou outro cache distribuído.
"""

from __future__ import annotations

from typing import Any

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.context.repositories import ContextRepository


class InMemoryContextRepository(ContextRepository):
    """Implementação em memória do ContextRepository.

    Usa dicionários Python para cache de contexto e metadados.
    Não persiste entre reinicializações do processo.
    """

    def __init__(self) -> None:
        """Inicializa o repositório em memória."""
        self._system_context_cache: dict[str, SystemContext] = {}
        self._user_context_cache: dict[str, UserContext] = {}
        self._metadata_cache: dict[str, Any] = {}

    async def get_system_context(self, conversation_id: str) -> SystemContext | None:
        """Busca o contexto de sistema cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.

        Returns:
            SystemContext cacheado ou None se não existir.
        """
        return self._system_context_cache.get(conversation_id)

    async def save_system_context(self, conversation_id: str, context: SystemContext) -> None:
        """Salva o contexto de sistema no cache.

        Args:
            conversation_id: ID da conversa.
            context: Contexto de sistema para salvar.
        """
        self._system_context_cache[conversation_id] = context

    async def get_user_context(self, conversation_id: str) -> UserContext | None:
        """Busca o contexto de usuário cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.

        Returns:
            UserContext cacheado ou None se não existir.
        """
        return self._user_context_cache.get(conversation_id)

    async def save_user_context(self, conversation_id: str, context: UserContext) -> None:
        """Salva o contexto de usuário no cache.

        Args:
            conversation_id: ID da conversa.
            context: Contexto de usuário para salvar.
        """
        self._user_context_cache[conversation_id] = context

    async def clear_context(self, conversation_id: str) -> None:
        """Limpa o contexto cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.
        """
        self._system_context_cache.pop(conversation_id, None)
        self._user_context_cache.pop(conversation_id, None)

    async def get_metadata(self, key: str) -> Any | None:
        """Busca metadados globais.

        Args:
            key: Chave do metadado.

        Returns:
            Valor do metadado ou None se não existir.
        """
        return self._metadata_cache.get(key)

    async def set_metadata(self, key: str, value: Any) -> None:
        """Salva metadados globais.

        Args:
            key: Chave do metadado.
            value: Valor do metadado.
        """
        self._metadata_cache[key] = value

    def clear_all(self) -> None:
        """Limpa todos os caches (útil para testes)."""
        self._system_context_cache.clear()
        self._user_context_cache.clear()
        self._metadata_cache.clear()
