"""Dependency Injection (DI) container."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from personagent.application.services import OperationalMemoryService, SessionTitleService
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.config.settings import get_settings
from personagent.infrastructure.llm.process_manager import (
    EmbeddingServerProcessManager,
    LlamaServerProcessManager,
)
from personagent.infrastructure.persistence.context import InMemoryContextRepository
from personagent.interfaces.config.di_container._browser import _BrowserMixin
from personagent.interfaces.config.di_container._database import _DatabaseMixin
from personagent.interfaces.config.di_container._llm import _LLMMixin
from personagent.interfaces.config.di_container._memory import _MemoryMixin
from personagent.interfaces.config.di_container._process import _ProcessMixin
from personagent.interfaces.config.di_container._prompt_context import _PromptContextMixin
from personagent.interfaces.config.di_container._services import _ServicesMixin
from personagent.interfaces.config.di_container._tools import _ToolMixin


class DIContainer(
    _LLMMixin,
    _ProcessMixin,
    _ToolMixin,
    _PromptContextMixin,
    _ServicesMixin,
    _MemoryMixin,
    _BrowserMixin,
    _DatabaseMixin,
):
    """Simple dependency injection container."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm_backends: dict[str, LLMBackendRepository] = {}
        self._process_manager: LlamaServerProcessManager | None = None
        self._embedding_process_manager: EmbeddingServerProcessManager | None = None
        self._lightpanda_browser_worker: LightPandaBrowserWorker | None = None
        self._tool_registry: ToolRegistry | None = None
        self._tool_runtime_config: ToolRuntimeConfig | None = None
        self._prompt_builder: PromptBuilder | None = None
        self._prompt_context_analyzers: dict[int, PromptContextAnalyzer] = {}
        self._context_repository: InMemoryContextRepository | None = None
        self._session_title_service: SessionTitleService | None = None
        self._embedding_adapter = None
        self._operational_memory_repository = None
        self._operational_memory_queue = None
        self._operational_memory_service: OperationalMemoryService | None = None

    @property
    def settings(self):
        return self._settings


# Singleton global do container
_container: DIContainer | None = None


def get_container() -> DIContainer:
    """Retorna o container DI singleton."""
    global _container
    if _container is None:
        _container = DIContainer()
    return _container


def reset_container() -> None:
    """Reset the container, useful for tests."""
    global _container
    _container = None


@asynccontextmanager
async def lifespan() -> AsyncGenerator[DIContainer, None]:
    """Context manager para o ciclo de vida do container."""
    container = get_container()
    settings = container.settings

    # Inicia o llama-server se configurado
    if settings.llama_auto_start:
        pm = container.get_process_manager()
        started = await pm.start()
        if not started:
            print("⚠️  Warning: Could not start llama-server automatically.")
            print("   Make sure the server is running manually.")

    if settings.embedding_auto_start:
        embedding_pm = container.get_embedding_process_manager()
        started = await embedding_pm.start()
        if not started:
            print("⚠️  Warning: Could not start the embedding server automatically.")
            print("   Run manually: ./@llama/scripts/start-embedding-server.sh")

    try:
        yield container
    finally:
        # Encerra o llama-server
        if container._process_manager:
            container._process_manager.stop()
        if container._embedding_process_manager:
            container._embedding_process_manager.stop()
        # Fecha os adapters LLM
        await container.close_llm_backends()
        await container.close_browser_workers()


__all__ = [
    "DIContainer",
    "get_container",
    "lifespan",
    "reset_container",
]
