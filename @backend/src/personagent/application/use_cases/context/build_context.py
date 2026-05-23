"""Build context use case.

Use case para montagem de contexto completo para uma conversa.
Orquestra os serviços de contexto e produz um :class:`RequestContext`
imutável que pode ser propagado pela cadeia de chamadas, em vez de
mutar um singleton global.
"""

from __future__ import annotations

from pathlib import Path

from personagent.application.state import PermissionMode, RequestContext
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.context.repositories import ContextRepository
from personagent.domain.context.services.context_builder import ContextBuilder
from personagent.domain.memory.repositories.memory_repository import MemoryRepository


class BuildContextUseCase:
    """Use case para montagem de contexto.

    Coordena a montagem de contexto usando :class:`ContextBuilder` e
    devolve o :class:`ContextBuildResult`. Para os consumidores que
    precisam de uma visão por requisição (workspace + conversa +
    contexto), use :meth:`build_request_context`.
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

        self._context_builder = ContextBuilder(
            self._workspace_root,
            context_repository=context_repository,
            enable_persona_md=enable_persona_md,
            additional_directories=additional_directories,
            memory_repository=memory_repository,
        )

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
        return await self._context_builder.build_context(
            conversation_id=conversation_id,
            use_cache=use_cache,
        )

    async def build_request_context(
        self,
        conversation_id: str,
        *,
        use_cache: bool = True,
        permission_mode: PermissionMode = "manual",
        tenant_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> RequestContext:
        """Build context and wrap the result as a per-request snapshot.

        This is the preferred entrypoint for callers that need to pass
        the active conversation/workspace down the call chain without
        leaning on a global singleton.
        """

        result = await self.execute(conversation_id, use_cache=use_cache)
        return RequestContext.from_build_result(
            conversation_id=conversation_id,
            workspace_root=str(self._workspace_root),
            result=result,
            permission_mode=permission_mode,
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
        )

    async def clear_context(self, conversation_id: str) -> None:
        """Limpa o contexto cacheado para uma conversa.

        Args:
            conversation_id: ID da conversa.
        """
        await self._context_builder.clear_context(conversation_id)
