"""Build context use case.

Use case para montagem de contexto completo para uma conversa.
Orquestra os serviços de contexto e atualiza o estado global.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from personagent.application.state.services import StateManager
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.context.repositories import ContextRepository
from personagent.domain.context.services.context_builder import ContextBuilder
from personagent.domain.memory.repositories.memory_repository import MemoryRepository


class BuildContextUseCase:
    """Use case para montagem de contexto.

    Coordena a montagem de contexto usando ContextBuilder e
    atualiza o StateManager com os resultados.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        context_repository: ContextRepository | None = None,
        enable_persona_md: bool = True,
        additional_directories: list[str | Path] | None = None,
        memory_repository: MemoryRepository | None = None,
    ) -> None:
        """Inicializa o use case.

        Args:
            workspace_root: Diretório raiz do workspace.
            context_repository: Repositório opcional para cache de contexto.
            enable_persona_md: Se False, desabilita carregamento de persona.md.
            additional_directories: Diretórios adicionais para buscar persona.md.
            memory_repository: Repositório opcional para memória de longo prazo.
        """
        self._workspace_root = Path(workspace_root).expanduser().resolve()
        self._context_repository = context_repository
        self._enable_persona_md = enable_persona_md
        self._additional_directories = additional_directories

        # Inicializa ContextBuilder
        self._context_builder = ContextBuilder(
            self._workspace_root,
            context_repository=context_repository,
            enable_persona_md=enable_persona_md,
            additional_directories=additional_directories,
            memory_repository=memory_repository,
        )

        # Obtém StateManager singleton
        self._state_manager = StateManager.get_instance()

    async def execute(
        self,
        conversation_id: str,
        use_cache: bool = True,
    ) -> ContextBuildResult:
        """Executa a montagem de contexto.

        Args:
            conversation_id: ID da conversa.
            use_cache: Se True, usa contexto cacheado se disponível.

        Returns:
            ContextBuildResult com contexto completo.
        """
        # Atualiza conversation_id no estado global
        self._state_manager.set_conversation_id(conversation_id)
        self._state_manager.set_workspace_root(str(self._workspace_root))

        # Monta contexto
        context_result = await self._context_builder.build_context(
            conversation_id=conversation_id,
            use_cache=use_cache,
        )

        # Atualiza estado global com contexto
        self._state_manager.set_system_context(dataclasses.asdict(context_result.system_context))
        self._state_manager.set_user_context(dataclasses.asdict(context_result.user_context))

        return context_result

    async def clear_context(self, conversation_id: str) -> None:
        """Limpa o contexto cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.
        """
        await self._context_builder.clear_context(conversation_id)
        self._state_manager.clear_caches()
