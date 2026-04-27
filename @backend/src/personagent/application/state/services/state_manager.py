"""State manager service.

Gerenciador singleton para estado global da aplicação.
Seguindo a Arquitetura Clean, este serviço fica na camada de aplicação.
"""

from __future__ import annotations

from typing import Any

from personagent.application.state.app_state import AppState


class StateManager:
    """Gerenciador singleton para estado global.

    Mantém uma única instância de AppState por processo backend,
    fornecendo acesso thread-safe ao estado da aplicação.
    """

    _instance: StateManager | None = None
    _state: AppState

    def __init__(self) -> None:
        """Inicializa o StateManager (privado - use get_instance())."""
        self._state = AppState()

    @classmethod
    def get_instance(cls) -> StateManager:
        """Retorna a instância singleton do StateManager.

        Returns:
            Instância singleton de StateManager.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reseta a instância singleton (útil para testes)."""
        cls._instance = None

    @property
    def state(self) -> AppState:
        """Retorna o estado atual da aplicação."""
        return self._state

    def update_state(self, **kwargs: Any) -> AppState:
        """Atualiza o estado com os campos fornecidos.

        Args:
            **kwargs: Campos a atualizar no estado.

        Returns:
            AppState atualizado.
        """
        for key, value in kwargs.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)
        self._state.update_timestamp()
        return self._state

    def get_session_id(self) -> str:
        """Retorna o ID da sessão atual."""
        return self._state.session_id

    def set_conversation_id(self, conversation_id: str) -> None:
        """Define o ID da conversa atual.

        Args:
            conversation_id: ID da conversa.
        """
        self._state.with_conversation(conversation_id)

    def get_conversation_id(self) -> str:
        """Retorna o ID da conversa atual."""
        return self._state.conversation_id

    def set_workspace_root(self, workspace_root: str) -> None:
        """Define o diretório raiz do workspace.

        Args:
            workspace_root: Caminho do workspace.
        """
        self._state.with_workspace(workspace_root)

    def get_workspace_root(self) -> str:
        """Retorna o diretório raiz do workspace."""
        return self._state.workspace_root

    def set_permission_mode(self, mode: str) -> None:
        """Define o modo de permissão.

        Args:
            mode: Modo de permissão (auto, manual, ask).
        """
        self._state.with_permission_mode(mode)

    def get_permission_mode(self) -> str:
        """Retorna o modo de permissão atual."""
        return self._state.permission_mode

    def get_settings(self) -> dict[str, Any]:
        """Retorna as configurações atuais."""
        return self._state.settings.copy()

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Atualiza as configurações.

        Args:
            settings: Novas configurações (merge com existentes).
        """
        self._state.settings.update(settings)
        self._state.update_timestamp()

    def get_system_context(self) -> dict[str, Any]:
        """Retorna o contexto de sistema atual."""
        return self._state.system_context.copy()

    def set_system_context(self, context: dict[str, Any]) -> None:
        """Define o contexto de sistema.

        Args:
            context: Contexto de sistema.
        """
        self._state.system_context = context.copy()
        self._state.update_timestamp()

    def get_user_context(self) -> dict[str, Any]:
        """Retorna o contexto de usuário atual."""
        return self._state.user_context.copy()

    def set_user_context(self, context: dict[str, Any]) -> None:
        """Define o contexto de usuário.

        Args:
            context: Contexto de usuário.
        """
        self._state.user_context = context.copy()
        self._state.update_timestamp()

    def add_allowed_tool(self, tool_name: str) -> None:
        """Adiciona uma ferramenta à allowlist.

        Args:
            tool_name: Nome da ferramenta.
        """
        self._state.add_allowed_tool(tool_name)

    def remove_allowed_tool(self, tool_name: str) -> None:
        """Remove uma ferramenta da allowlist.

        Args:
            tool_name: Nome da ferramenta.
        """
        self._state.remove_allowed_tool(tool_name)

    def get_allowed_tools(self) -> set[str]:
        """Retorna o conjunto de ferramentas permitidas."""
        return self._state.allowed_tools.copy()

    def increment_request_count(self) -> int:
        """Incrementa o contador de requisições.

        Returns:
            Novo valor do contador.
        """
        self._state.increment_request_count()
        return self._state.request_count

    def add_cost(self, cost_usd: float) -> float:
        """Adiciona custo ao total.

        Args:
            cost_usd: Custo em USD.

        Returns:
            Novo total de custo.
        """
        self._state.add_cost(cost_usd)
        return self._state.total_cost_usd

    def add_api_duration(self, duration_ms: int) -> int:
        """Adiciona duração de API ao total.

        Args:
            duration_ms: Duração em milissegundos.

        Returns:
            Novo total de duração.
        """
        self._state.add_api_duration(duration_ms)
        return self._state.total_api_duration_ms

    def add_tool_duration(self, duration_ms: int) -> int:
        """Adiciona duração de ferramenta ao total.

        Args:
            duration_ms: Duração em milissegundos.

        Returns:
            Novo total de duração.
        """
        self._state.add_tool_duration(duration_ms)
        return self._state.total_tool_duration_ms

    def add_tokens_used(self, tokens: int) -> int:
        """Adiciona tokens usados ao total.

        Args:
            tokens: Número de tokens.

        Returns:
            Novo total de tokens.
        """
        self._state.add_tokens_used(tokens)
        return self._state.total_tokens_used

    def get_metrics(self) -> dict[str, Any]:
        """Retorna métricas de performance.

        Returns:
            Dicionário com métricas atuais.
        """
        return {
            "total_cost_usd": self._state.total_cost_usd,
            "total_api_duration_ms": self._state.total_api_duration_ms,
            "total_tool_duration_ms": self._state.total_tool_duration_ms,
            "total_tokens_used": self._state.total_tokens_used,
            "request_count": self._state.request_count,
        }

    def clear_caches(self) -> None:
        """Limpa todos os caches."""
        self._state.clear_caches()

    def cache_system_prompt(self, key: str, value: str) -> None:
        """Cacheia um system prompt.

        Args:
            key: Chave do cache.
            value: Valor do system prompt.
        """
        self._state.cache_system_prompt(key, value)

    def get_cached_system_prompt(self, key: str) -> str | None:
        """Busca um system prompt cacheado.

        Args:
            key: Chave do cache.

        Returns:
            System prompt cacheado ou None.
        """
        return self._state.get_cached_system_prompt(key)

    def cache_context(self, key: str, value: dict[str, Any]) -> None:
        """Cacheia um contexto.

        Args:
            key: Chave do cache.
            value: Valor do contexto.
        """
        self._state.cache_context(key, value)

    def get_cached_context(self, key: str) -> dict[str, Any] | None:
        """Busca um contexto cacheado.

        Args:
            key: Chave do cache.

        Returns:
            Contexto cacheado ou None.
        """
        return self._state.get_cached_context(key)

    def reset_state(self) -> None:
        """Reseta o estado para valores padrão."""
        self._state = AppState()
