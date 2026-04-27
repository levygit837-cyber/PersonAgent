"""Context builder service.

Este serviço orquestra a montagem do contexto completo (sistema + usuário)
para uma conversa, usando os serviços especializados (Git, ClaudeMd, etc.).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.context.repositories import ContextRepository
from personagent.domain.context.services.git_context import GitContextService
from personagent.domain.context.services.personamd_loader import PersonaMdLoader
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.models.memory_types import MemoryScope


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

        return UserContext(
            claude_md=persona_md if persona_md else None,
            memory_files=tuple(memory_files),
            current_date=current_date,
            user_settings={},  # TODO: carregar de configurações
            project_config={},  # TODO: carregar de config.yaml
            long_term_memory_index=long_term_memory_index,
        )

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
