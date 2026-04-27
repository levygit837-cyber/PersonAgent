"""Application state management.

Define o estado global da aplicação (singleton por processo backend).
Seguindo a Arquitetura Clean, este estado é gerenciado na camada de aplicação.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class AppState:
    """Estado global da aplicação.

    Singleton por processo backend que armazena configurações, contexto,
    permissões e metadados relevantes para toda a sessão.
    """

    # Identificação
    session_id: str = field(default_factory=lambda: str(uuid4()))
    conversation_id: str = ""

    # Configurações
    settings: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = "manual"  # auto, manual, ask

    # Contexto atual
    system_context: dict[str, Any] = field(default_factory=dict)
    user_context: dict[str, Any] = field(default_factory=dict)

    # Workspace
    workspace_root: str = ""
    allowed_roots: tuple[str, ...] = ()

    # Permissões de ferramentas
    tool_permissions: dict[str, Any] = field(default_factory=dict)
    allowed_tools: set[str] = field(default_factory=set)

    # Metadados
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Performance e métricas
    total_cost_usd: float = 0.0
    total_api_duration_ms: int = 0
    total_tool_duration_ms: int = 0
    total_tokens_used: int = 0
    request_count: int = 0

    # Estado de UI (para integração com desktop)
    ui_state: dict[str, Any] = field(default_factory=dict)

    # Cache
    system_prompt_cache: dict[str, str] = field(default_factory=dict)
    context_cache: dict[str, dict[str, Any]] = field(default_factory=dict)

    def update_timestamp(self) -> None:
        """Atualiza o timestamp de modificação."""
        self.updated_at = datetime.now(UTC)

    def with_conversation(self, conversation_id: str) -> AppState:
        """Retorna uma cópia com um novo conversation_id."""
        self.conversation_id = conversation_id
        self.update_timestamp()
        return self

    def with_workspace(self, workspace_root: str) -> AppState:
        """Retorna uma cópia com um novo workspace_root."""
        self.workspace_root = workspace_root
        self.update_timestamp()
        return self

    def with_permission_mode(self, mode: str) -> AppState:
        """Retorna uma cópia com um novo permission_mode."""
        if mode in ("auto", "manual", "ask"):
            self.permission_mode = mode
            self.update_timestamp()
        return self

    def add_allowed_tool(self, tool_name: str) -> None:
        """Adiciona uma ferramenta à allowlist."""
        self.allowed_tools.add(tool_name)
        self.update_timestamp()

    def remove_allowed_tool(self, tool_name: str) -> None:
        """Remove uma ferramenta da allowlist."""
        self.allowed_tools.discard(tool_name)
        self.update_timestamp()

    def increment_request_count(self) -> None:
        """Incrementa o contador de requisições."""
        self.request_count += 1
        self.update_timestamp()

    def add_cost(self, cost_usd: float) -> None:
        """Adiciona custo ao total."""
        self.total_cost_usd += cost_usd
        self.update_timestamp()

    def add_api_duration(self, duration_ms: int) -> None:
        """Adiciona duração de API ao total."""
        self.total_api_duration_ms += duration_ms
        self.update_timestamp()

    def add_tool_duration(self, duration_ms: int) -> None:
        """Adiciona duração de ferramenta ao total."""
        self.total_tool_duration_ms += duration_ms
        self.update_timestamp()

    def add_tokens_used(self, tokens: int) -> None:
        """Adiciona tokens usados ao total."""
        self.total_tokens_used += tokens
        self.update_timestamp()

    def cache_system_prompt(self, key: str, value: str) -> None:
        """Cacheia um system prompt."""
        self.system_prompt_cache[key] = value

    def get_cached_system_prompt(self, key: str) -> str | None:
        """Busca um system prompt cacheado."""
        return self.system_prompt_cache.get(key)

    def cache_context(self, key: str, value: dict[str, Any]) -> None:
        """Cacheia um contexto."""
        self.context_cache[key] = value

    def get_cached_context(self, key: str) -> dict[str, Any] | None:
        """Busca um contexto cacheado."""
        return self.context_cache.get(key)

    def clear_caches(self) -> None:
        """Limpa todos os caches."""
        self.system_prompt_cache.clear()
        self.context_cache.clear()
        self.update_timestamp()
