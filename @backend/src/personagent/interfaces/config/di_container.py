"""Dependency Injection (DI) container."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services import (
    NextStepSuggestionService,
    OperationalMemoryService,
    SessionMemoryService,
    SessionTitleService,
)
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.domain.prompts.commands import CommandRegistry
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.config.settings import get_settings
from personagent.infrastructure.llm.codex_subscription_adapter import CodexSubscriptionAdapter
from personagent.infrastructure.llm.deepseek_adapter import DeepSeekAdapter
from personagent.infrastructure.llm.kimi_coding_adapter import KimiCodingAdapter
from personagent.infrastructure.llm.llama_cpp_adapter import LlamaCppAdapter
from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
from personagent.infrastructure.llm.process_manager import (
    EmbeddingServerProcessManager,
    LlamaServerProcessManager,
)
from personagent.infrastructure.llm.vertex_ai_adapter import VertexAiAdapter
from personagent.infrastructure.persistence.context import InMemoryContextRepository
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from personagent.infrastructure.persistence.task_store import SqlAlchemyTaskStore
from personagent.infrastructure.tools import (
    create_agent_tools,
    create_ask_user_question_tool,
    create_browser_tools,
    create_config_tool,
    create_edit_file_tool,
    create_enter_plan_mode_tool,
    create_enter_worktree_tool,
    create_exit_plan_mode_tool,
    create_exit_worktree_tool,
    create_glob_tool,
    create_grep_tool,
    create_lsp_tool,
    create_mcp_tools,
    create_read_file_tool,
    create_send_user_message_tool,
    create_shell_tool,
    create_skill_tool,
    create_structured_output_tool,
    create_task_tools,
    create_todo_write_tool,
    create_tool_search_tool,
    create_web_fetch_tool,
    create_web_search_tool,
    create_write_file_tool,
)


class DIContainer:
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
        self._operational_memory_service: OperationalMemoryService | None = None

    @property
    def settings(self):
        return self._settings

    def get_llm_backend(self, provider: str = "llama") -> LLMBackendRepository:
        """Retorna o adapter do LLM (singleton)."""
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"llama", "nvidia", "deepseek", "vertex", "kimi", "codex"}:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        if normalized_provider not in self._llm_backends:
            self._llm_backends[normalized_provider] = self._create_llm_backend(normalized_provider)
        return self._llm_backends[normalized_provider]

    def _create_llm_backend(self, provider: str) -> LLMBackendRepository:
        if provider == "llama":
            return LlamaCppAdapter(
                base_url=self._settings.llama_server_url,
                api_key=self._settings.llama_server_api_key,
                timeout=self._settings.llama_timeout_seconds,
                stream_read_timeout=self._settings.llama_stream_read_timeout_seconds,
                default_max_tokens=self._settings.llama_max_tokens,
                reasoning=self._settings.llama_reasoning,
                reasoning_budget=self._settings.llama_reasoning_budget,
                ctx_size=self._settings.llama_ctx_size,
            )
        if provider == "nvidia":
            return NvidiaNimAdapter(
                base_url=self._settings.nvidia_base_url,
                api_key=self._settings.nvidia_api_key,
                timeout=self._settings.nvidia_timeout_seconds,
                stream_read_timeout=self._settings.nvidia_stream_read_timeout_seconds,
                default_model=self._settings.nvidia_default_model,
                default_max_tokens=self._settings.nvidia_max_tokens,
                models_cache_ttl_seconds=self._settings.nvidia_models_cache_ttl_seconds,
            )
        if provider == "deepseek":
            return DeepSeekAdapter(
                base_url=self._settings.deepseek_base_url,
                api_key=self._settings.deepseek_api_key,
                timeout=self._settings.deepseek_timeout_seconds,
                stream_read_timeout=self._settings.deepseek_stream_read_timeout_seconds,
                default_model=self._settings.deepseek_default_model,
                default_max_tokens=self._settings.deepseek_max_tokens,
                models_cache_ttl_seconds=self._settings.deepseek_models_cache_ttl_seconds,
            )
        if provider == "vertex":
            return VertexAiAdapter(
                api_key=self._settings.google_api_key,
                auth_mode=self._settings.vertex_auth_mode,
                project_id=self._settings.vertex_project_id,
                location=self._settings.vertex_location,
                timeout=self._settings.vertex_timeout_seconds,
                stream_read_timeout=self._settings.vertex_stream_read_timeout_seconds,
                default_model=self._settings.vertex_default_model,
                default_max_tokens=self._settings.vertex_max_tokens,
                models_cache_ttl_seconds=self._settings.vertex_models_cache_ttl_seconds,
            )
        if provider == "kimi":
            return KimiCodingAdapter(
                base_url=self._settings.kimi_base_url,
                api_key=self._settings.kimi_api_key,
                timeout=self._settings.kimi_timeout_seconds,
                stream_read_timeout=self._settings.kimi_stream_read_timeout_seconds,
                default_model=self._settings.kimi_default_model,
                default_max_tokens=self._settings.kimi_max_tokens,
                context_window=self._settings.kimi_context_window,
                anthropic_version=self._settings.kimi_anthropic_version,
            )
        if provider == "codex":
            return CodexSubscriptionAdapter(
                base_url=self._settings.codex_base_url,
                codex_home=self._settings.codex_home,
                codex_cli_path=self._settings.codex_cli_path,
                client_version=self._settings.codex_client_version,
                timeout=self._settings.codex_timeout_seconds,
                stream_read_timeout=self._settings.codex_stream_read_timeout_seconds,
                default_model=self._settings.codex_default_model,
                default_max_tokens=self._settings.codex_max_tokens,
                context_window=self._settings.codex_context_window,
                models_cache_ttl_seconds=self._settings.codex_models_cache_ttl_seconds,
            )
        raise ValueError(f"Unsupported LLM provider: {provider}")

    def get_process_manager(self) -> LlamaServerProcessManager:
        """Retorna o gerenciador de processo do llama-server."""
        if self._process_manager is None:
            self._process_manager = LlamaServerProcessManager()
        return self._process_manager

    def get_embedding_process_manager(self) -> EmbeddingServerProcessManager:
        """Retorna o gerenciador do servidor local de embeddings."""
        if self._embedding_process_manager is None:
            self._embedding_process_manager = EmbeddingServerProcessManager()
        return self._embedding_process_manager

    def get_tool_registry(self) -> ToolRegistry:
        """Retorna o registry de ferramentas locais (singleton)."""
        if self._tool_registry is None:
            task_store = SqlAlchemyTaskStore(AsyncSessionLocal)
            registry = ToolRegistry()
            for tool in [
                create_read_file_tool(),
                create_write_file_tool(),
                create_edit_file_tool(),
                create_glob_tool(),
                create_grep_tool(),
                create_shell_tool(),
                create_config_tool(),
                create_enter_worktree_tool(),
                create_exit_worktree_tool(),
                create_ask_user_question_tool(),
                create_send_user_message_tool(enabled=self._settings.brief_tool_enabled),
                create_web_fetch_tool(),
                create_web_search_tool(enabled=False),
                *create_browser_tools(self.get_lightpanda_browser_worker()),
                *create_mcp_tools(
                    self._settings.tool_mcp_server_configs,
                    enabled=self._settings.tools_mcp_enabled,
                ),
                create_lsp_tool(enabled=self._settings.tools_lsp_enabled),
                create_enter_plan_mode_tool(),
                create_exit_plan_mode_tool(),
                create_todo_write_tool(),
                *create_agent_tools(task_store),
                *create_task_tools(task_store),
                create_skill_tool(),
                create_structured_output_tool(),
            ]:
                registry.register(tool)
            registry.register(create_tool_search_tool(lambda: registry))
            self._tool_registry = registry
        return self._tool_registry

    def get_prompt_builder(self) -> PromptBuilder:
        """Retorna o builder dinâmico de system prompts."""
        if self._prompt_builder is None:
            self._prompt_builder = PromptBuilder(permission_mode="manual")
        return self._prompt_builder

    def create_prompt_context_analyzer(
        self,
        llm_backend: LLMBackendRepository,
    ) -> PromptContextAnalyzer:
        backend_key = id(llm_backend)
        analyzer = self._prompt_context_analyzers.get(backend_key)
        if analyzer is None:
            analyzer = PromptContextAnalyzer(
                llm_backend,
                timeout_seconds=self._settings.prompt_context_analysis_timeout_seconds,
                long_timeout_seconds=self._settings.prompt_context_analysis_long_timeout_seconds,
                failure_cooldown_seconds=(
                    self._settings.prompt_context_analysis_failure_cooldown_seconds
                ),
                long_context_chars=self._settings.prompt_context_analysis_long_context_chars,
                max_payload_chars=self._settings.prompt_context_analysis_max_payload_chars,
            )
            self._prompt_context_analyzers[backend_key] = analyzer
        return analyzer

    def create_session_memory_service(
        self,
        llm_backend: LLMBackendRepository | None = None,
    ) -> SessionMemoryService:
        return SessionMemoryService(llm_backend)

    def create_next_step_suggestion_service(
        self,
        llm_backend: LLMBackendRepository,
    ) -> NextStepSuggestionService:
        return NextStepSuggestionService(llm_backend)

    def get_session_title_service(self) -> SessionTitleService | None:
        """Return the cached/LLM-backed session title verifier."""
        if not self._settings.chat_session_title_checks_enabled:
            return None
        if self._session_title_service is None:
            primary_provider = self._settings.chat_session_title_primary_provider
            fallback_provider = self._settings.chat_session_title_fallback_provider
            self._session_title_service = SessionTitleService(
                primary_llm_backend=self.get_llm_backend(primary_provider),
                fallback_llm_backend=self.get_llm_backend(fallback_provider),
                primary_provider=primary_provider,
                primary_model=self._settings.chat_session_title_primary_model,
                fallback_provider=fallback_provider,
                fallback_model=self._settings.chat_session_title_fallback_model,
                batch_size=self._settings.chat_session_title_batch_size,
                scan_limit=self._settings.chat_session_title_scan_limit,
                max_history_chars=self._settings.chat_session_title_max_history_chars,
                duplicate_check_interval_seconds=(
                    self._settings.chat_session_title_duplicate_check_interval_seconds
                ),
                similarity_threshold=self._settings.chat_session_title_similarity_threshold,
            )
        return self._session_title_service

    def create_command_registry(self) -> CommandRegistry:
        return CommandRegistry(extra_roots=self._settings.prompt_command_root_paths)

    def get_context_repository(self) -> InMemoryContextRepository:
        """Return the in-memory context cache for the main chat."""
        if self._context_repository is None:
            self._context_repository = InMemoryContextRepository()
        return self._context_repository

    def create_build_context_use_case(self, workspace_root: str) -> BuildContextUseCase:
        """Cria um use case de contexto para o workspace selecionado."""
        from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
            FileSystemMemoryRepository,
        )
        return BuildContextUseCase(
            workspace_root=workspace_root,
            context_repository=self.get_context_repository(),
            enable_persona_md=True,
            memory_repository=FileSystemMemoryRepository(),
        )

    # --- Intelligent Memory System ---

    def get_memory_repository(self):
        """Return the memory repository singleton."""
        from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
            FileSystemMemoryRepository,
        )
        return FileSystemMemoryRepository()

    def get_memory_job_scheduler(self):
        """Return the memory job scheduler singleton."""
        from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
        if not hasattr(self, "_memory_job_scheduler"):
            self._memory_job_scheduler = MemoryJobScheduler()
        return self._memory_job_scheduler

    def create_memory_recall_selector(self, llm_backend: LLMBackendRepository):
        """Create the relevant-memory selector."""
        from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector
        return MemoryRecallSelector(
            llm_backend=llm_backend,
            memory_repository=self.get_memory_repository(),
            max_recall=self._settings.memory_max_recall_per_query,
            max_tokens=self._settings.memory_recall_max_tokens,
        )

    def create_recall_memory_use_case(self, llm_backend: LLMBackendRepository):
        """Create the memory recall use case."""
        from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
        return RecallMemoryUseCase(
            recall_selector=self.create_memory_recall_selector(llm_backend),
        )

    def get_embedding_adapter(self):
        """Retorna o adapter do modelo local de embeddings."""
        if not self._settings.operational_memory_embedding_enabled:
            return None
        if self._embedding_adapter is None:
            from personagent.infrastructure.llm.embedding_adapter import (
                OpenAICompatibleEmbeddingAdapter,
            )

            self._embedding_adapter = OpenAICompatibleEmbeddingAdapter(
                base_url=self._settings.embedding_server_url,
                api_key=self._settings.embedding_server_api_key,
                model=self._settings.embedding_model,
                timeout=self._settings.embedding_timeout_seconds,
                dimensions=self._settings.embedding_dimensions,
            )
        return self._embedding_adapter

    def get_operational_memory_repository(self):
        """Return the PostgreSQL operational-memory repository."""
        if self._operational_memory_repository is None:
            from personagent.infrastructure.persistence.operational_memory_repository import (
                OperationalMemoryRepository,
            )

            self._operational_memory_repository = OperationalMemoryRepository(AsyncSessionLocal)
        return self._operational_memory_repository

    def get_operational_memory_service(self) -> OperationalMemoryService | None:
        """Return the operational RAG service when enabled."""
        if not self._settings.operational_memory_enabled:
            return None
        if self._operational_memory_service is None:
            self._operational_memory_service = OperationalMemoryService(
                repository=self.get_operational_memory_repository(),
                embedding_adapter=self.get_embedding_adapter(),
                embedding_model=self._settings.embedding_model,
                embeddings_enabled=self._settings.operational_memory_embedding_enabled,
                recall_enabled=self._settings.operational_memory_recall_enabled,
                capture_tools_enabled=self._settings.operational_memory_capture_tools_enabled,
                max_capture_chars=self._settings.operational_memory_max_capture_chars,
                chunk_max_chars=self._settings.operational_memory_chunk_max_chars,
                recall_top_k=self._settings.operational_memory_recall_top_k,
                hot_cache_size=self._settings.operational_memory_hot_cache_size,
                semantic_candidate_limit=(
                    self._settings.operational_memory_semantic_candidate_limit
                ),
                recent_candidate_limit=self._settings.operational_memory_recent_candidate_limit,
                context_budget_tokens=self._settings.operational_memory_context_budget_tokens,
            )
        return self._operational_memory_service

    def create_extract_memory_worker(self):
        """Create the memory extraction worker."""
        from contextlib import asynccontextmanager

        from personagent.application.jobs.workers.extract_memory_worker import ExtractMemoryWorker
        from personagent.domain.memory.services.memory_extractor import MemoryExtractor

        @asynccontextmanager
        async def conversation_repo_factory():
            async with AsyncSessionLocal() as session:
                yield PostgresConversationRepository(session)

        return ExtractMemoryWorker(
            memory_repository=self.get_memory_repository(),
            memory_extractor=MemoryExtractor(
                llm_backend=self.get_llm_backend("llama"),
                memory_repository=self.get_memory_repository(),
            ),
            conversation_repo_factory=conversation_repo_factory,
        )

    def create_consolidate_memory_worker(self):
        """Create the memory consolidation worker."""
        from personagent.application.jobs.workers.consolidate_memory_worker import (
            ConsolidateMemoryWorker,
        )
        from personagent.domain.memory.services.memory_consolidator import MemoryConsolidator
        return ConsolidateMemoryWorker(
            memory_repository=self.get_memory_repository(),
            memory_consolidator=MemoryConsolidator(
                llm_backend=self.get_llm_backend("llama"),
                memory_repository=self.get_memory_repository(),
            ),
        )

    def get_lightpanda_browser_worker(self) -> LightPandaBrowserWorker:
        """Retorna o worker LightPanda usado pelas ferramentas de browser."""
        if self._lightpanda_browser_worker is None:
            self._lightpanda_browser_worker = LightPandaBrowserWorker(
                enabled=self._settings.lightpanda_enabled,
                cdp_url=self._settings.browser_cdp_url or self._settings.lightpanda_cdp_url,
                timeout_ms=self._settings.lightpanda_timeout_ms,
                search_base_url=self._settings.lightpanda_search_base_url,
                session_ttl_seconds=self._settings.lightpanda_session_ttl_seconds,
                max_sessions=self._settings.lightpanda_max_sessions,
                auto_start_lightpanda=not bool(self._settings.browser_cdp_url),
            )
        return self._lightpanda_browser_worker

    def get_tool_runtime_config(self) -> ToolRuntimeConfig:
        """Return the tool runtime configuration."""
        if self._tool_runtime_config is None:
            self._tool_runtime_config = ToolRuntimeConfig.from_values(
                workspace_root=self._settings.tool_workspace_root_path,
                allowed_roots=self._settings.tool_allowed_root_paths,
                max_tool_iterations=self._settings.tools_max_iterations,
                max_concurrency=self._settings.tools_max_concurrency,
                read_max_bytes=self._settings.tools_read_max_bytes,
                read_default_limit=self._settings.tools_read_default_limit,
                read_max_lines=self._settings.tools_read_max_lines,
                search_timeout_ms=self._settings.tools_search_timeout_ms,
                shell_timeout_ms=self._settings.tools_shell_timeout_ms,
                web_timeout_ms=self._settings.tools_web_timeout_ms,
                web_max_bytes=self._settings.tools_web_max_bytes,
                result_max_chars=self._settings.tools_result_max_chars,
                tool_result_storage_root=self._settings.tools_result_storage_root,
                web_allowed_domains=self._settings.tool_web_allowed_domain_list,
                web_blocked_domains=self._settings.tool_web_blocked_domain_list,
                skill_roots=self._settings.tool_skill_root_paths,
                lsp_enabled=self._settings.tools_lsp_enabled,
            )
        return self._tool_runtime_config

    async def get_db_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Return a database session."""
        session = AsyncSessionLocal()
        try:
            yield session
        finally:
            await session.close()

    async def get_conversation_repo(self, session: AsyncSession) -> ConversationRepository:
        """Return the conversation repository."""
        return PostgresConversationRepository(session)

    async def close_llm_backends(self) -> None:
        """Close all initialized LLM adapters."""
        for backend in self._llm_backends.values():
            close = getattr(backend, "close", None)
            if close is not None:
                await close()
        self._llm_backends.clear()
        if self._embedding_adapter is not None:
            close = getattr(self._embedding_adapter, "close", None)
            if close is not None:
                await close()
            self._embedding_adapter = None

    async def close_browser_workers(self) -> None:
        """Close browser workers initialized by tools."""
        if self._lightpanda_browser_worker is not None:
            await self._lightpanda_browser_worker.close()
            self._lightpanda_browser_worker = None


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
