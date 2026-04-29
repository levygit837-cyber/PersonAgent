"""Context builder service.

Este serviço orquestra a montagem do contexto completo (sistema + usuário)
para uma conversa, usando os serviços especializados (Git, PersonaMd, etc.).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.context.repositories import ContextRepository
from personagent.domain.context.services.git_context import GitContextService
from personagent.domain.context.services.personamd_loader import PersonaMdLoader
from personagent.domain.memory.models.memory_types import MemoryScope
from personagent.domain.memory.repositories.memory_repository import MemoryRepository

_SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "credential",
    "auth",
    "cookie",
)

_SAFE_SETTINGS_FIELDS = (
    "app_name",
    "app_version",
    "app_env",
    "app_host",
    "app_port",
    "log_level",
    "llama_server_url",
    "llama_model_path",
    "llama_ctx_size",
    "llama_n_gpu_layers",
    "llama_temperature",
    "llama_max_tokens",
    "llama_cache_type_k",
    "llama_cache_type_v",
    "llama_threads",
    "llama_reasoning",
    "llama_reasoning_budget",
    "llama_verbose",
    "llama_timeout_seconds",
    "llama_stream_read_timeout_seconds",
    "llama_auto_start",
    "nvidia_base_url",
    "nvidia_default_model",
    "nvidia_timeout_seconds",
    "nvidia_stream_read_timeout_seconds",
    "nvidia_models_cache_ttl_seconds",
    "deepseek_base_url",
    "deepseek_default_model",
    "deepseek_max_tokens",
    "deepseek_context_window",
    "deepseek_timeout_seconds",
    "deepseek_stream_read_timeout_seconds",
    "deepseek_models_cache_ttl_seconds",
    "vertex_location",
    "vertex_default_model",
    "vertex_context_window",
    "vertex_timeout_seconds",
    "vertex_stream_read_timeout_seconds",
    "vertex_models_cache_ttl_seconds",
    "kimi_base_url",
    "kimi_default_model",
    "kimi_max_tokens",
    "kimi_context_window",
    "kimi_timeout_seconds",
    "kimi_stream_read_timeout_seconds",
    "embedding_server_url",
    "embedding_model",
    "embedding_dimensions",
    "embedding_timeout_seconds",
    "embedding_auto_start",
    "lightpanda_enabled",
    "lightpanda_cdp_url",
    "lightpanda_timeout_ms",
    "lightpanda_search_base_url",
    "lightpanda_session_ttl_seconds",
    "operational_memory_enabled",
    "operational_memory_capture_tools_enabled",
    "operational_memory_recall_enabled",
    "operational_memory_embedding_enabled",
    "operational_memory_max_capture_chars",
    "operational_memory_chunk_max_chars",
    "operational_memory_recall_top_k",
)


class ContextBuilder:
    """Orquestra a montagem do contexto completo.

    Coordena os serviços especializados para coletar informações de
    sistema e usuário, combinando-as em um contexto completo para o agente.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        context_repository: ContextRepository | None = None,
        enable_persona_md: bool = True,
        additional_directories: list[str | Path] | None = None,
        memory_repository: MemoryRepository | None = None,
        project_slug: str | None = None,
    ) -> None:
        """Inicializa o ContextBuilder.

        Args:
            workspace_root: Diretório raiz do workspace.
            context_repository: Repositório opcional para cache de contexto.
            enable_persona_md: Se False, desabilita carregamento de persona.md.
            additional_directories: Diretórios adicionais para buscar persona.md.
            memory_repository: Repositório opcional para memória de longo prazo.
            project_slug: Slug do projeto para resolver diretório de memória.
        """
        self._workspace_root = Path(workspace_root).expanduser().resolve()
        self._context_repository = context_repository
        self._persona_md_loader = PersonaMdLoader(
            workspace_root=self._workspace_root,
            enable_persona_md=enable_persona_md,
            additional_directories=additional_directories,
        )
        self._git_context_service = GitContextService(self._workspace_root)
        self._memory_repository = memory_repository
        self._project_slug = project_slug or self._workspace_root.name

    async def build_context(
        self,
        conversation_id: str,
        use_cache: bool = True,
    ) -> ContextBuildResult:
        """Monta o contexto completo para uma conversa.

        Args:
            conversation_id: ID da conversa.
            use_cache: Se True, usa contexto cacheado se disponível.

        Returns:
            ContextBuildResult com sistema e usuário context.
        """
        start_time = time.time()

        # Tenta buscar do cache
        if use_cache and self._context_repository:
            cached_system = await self._context_repository.get_system_context(conversation_id)
            cached_user = await self._context_repository.get_user_context(conversation_id)
            if cached_system and cached_user:
                return ContextBuildResult(
                    system_context=cached_system,
                    user_context=cached_user,
                    build_duration_ms=0,
                    metadata={"source": "cache"},
                )

        # Monta contexto de sistema
        system_context = await self._build_system_context()

        # Monta contexto de usuário
        user_context = await self._build_user_context()

        # Salva no cache
        if self._context_repository:
            await self._context_repository.save_system_context(conversation_id, system_context)
            await self._context_repository.save_user_context(conversation_id, user_context)

        build_duration_ms = int((time.time() - start_time) * 1000)

        return ContextBuildResult(
            system_context=system_context,
            user_context=user_context,
            build_duration_ms=build_duration_ms,
            metadata={"source": "built"},
        )

    async def _build_system_context(self) -> SystemContext:
        """Monta o contexto de sistema.

        Coleta informações do Git, ambiente e workspace.
        """
        # Coleta informações Git
        git_info = self._git_context_service.get_git_info()

        # Coleta variáveis de ambiente relevantes
        environment = self._get_relevant_environment()

        return SystemContext(
            git_status=git_info.to_dict(),
            git_branch=git_info.branch,
            git_remote=git_info.remote,
            git_commit=git_info.commit,
            workspace_root=str(self._workspace_root),
            cwd=str(self._workspace_root),
            environment=environment,
        )

    async def _build_user_context(self) -> UserContext:
        """Monta o contexto de usuário.

        Carrega arquivos persona.md, índice MEMORY.md e informações do usuário.
        """
        # Carrega arquivos de memória (persona.md)
        memory_files = self._persona_md_loader.load_memory_files()

        # Combina conteúdo persona.md
        persona_md = self._persona_md_loader.get_combined_content()

        # Data atual
        current_date = datetime.now(UTC).strftime("%Y-%m-%d")

        # Carrega índice de memória de longo prazo (MEMORY.md)
        long_term_memory_index: str | None = None
        if self._memory_repository:
            memory_dir = await self._memory_repository.get_memory_dir(
                self._project_slug,
                scope=MemoryScope.PRIVATE,
            )
            index = await self._memory_repository.read_index(memory_dir)
            if index:
                long_term_memory_index = index.content

        project_config = self._safe_project_config()

        return UserContext(
            persona_md=persona_md if persona_md else None,
            memory_files=tuple(memory_files),
            current_date=current_date,
            user_settings=self._safe_user_settings(project_config),
            project_config=project_config,
            long_term_memory_index=long_term_memory_index,
        )

    def _safe_user_settings(self, project_config: Mapping[str, Any]) -> dict[str, Any]:
        """Return runtime settings that are safe to expose in prompt context."""
        return safe_settings_context(project_config)

    def _safe_project_config(self) -> dict[str, Any]:
        """Return a redacted `config.yaml` subset for prompt context."""
        config_path = self._workspace_root / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            with open(config_path, encoding="utf-8") as file:
                raw = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return redact_sensitive_mapping(raw) if isinstance(raw, Mapping) else {}

    def _get_relevant_environment(self) -> dict[str, str]:
        """Retorna variáveis de ambiente relevantes.

        Filtra variáveis de ambiente para incluir apenas as relevantes
        para o contexto do agente.
        """
        relevant_vars = {
            "PATH",
            "HOME",
            "USER",
            "SHELL",
            "LANG",
            "LC_ALL",
            "TERM",
        }

        env_vars: dict[str, str] = {}
        for var in relevant_vars:
            value = self._get_env_var(var)
            if value:
                env_vars[var] = value

        return env_vars

    def _get_env_var(self, name: str) -> str | None:
        """Busca uma variável de ambiente de forma segura."""
        import os

        return os.environ.get(name)

    async def clear_context(self, conversation_id: str) -> None:
        """Limpa o contexto cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.
        """
        if self._context_repository:
            await self._context_repository.clear_context(conversation_id)


def safe_settings_context(project_config: Mapping[str, Any]) -> dict[str, Any]:
    """Build a small config snapshot without credentials or tokens."""
    flattened: dict[str, Any] = {}
    for section_name, section in project_config.items():
        if not isinstance(section, Mapping):
            continue
        for key, value in section.items():
            flattened[f"{section_name}_{key}"] = value
    return redact_sensitive_mapping(
        {field: flattened[field] for field in _SAFE_SETTINGS_FIELDS if field in flattened}
    )


def redact_sensitive_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive keys from a mapping before prompt injection."""
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            redacted[key_text] = "[redacted]"
        elif isinstance(item, Mapping):
            redacted[key_text] = redact_sensitive_mapping(item)
        elif isinstance(item, list):
            redacted[key_text] = [_redact_sensitive_value(child) for child in item]
        elif isinstance(item, str) and _is_url_with_credentials(item):
            redacted[key_text] = "[redacted]"
        else:
            redacted[key_text] = item
    return redacted


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_sensitive_mapping(value)
    if isinstance(value, list):
        return [_redact_sensitive_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _is_url_with_credentials(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(parsed.scheme and parsed.netloc and (parsed.username or parsed.password))
