"""Intelligent Memory System mixin."""

from contextlib import asynccontextmanager

from personagent.application.services import OperationalMemoryService
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.postgres_conversation_repository import (
    PostgresConversationRepository,
)


class _MemoryMixin:
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

    def get_operational_memory_queue(self):
        """Return the RabbitMQ operational-memory queue adapter when enabled."""
        if not self._settings.operational_memory_queue_enabled:
            return None
        if self._operational_memory_queue is None:
            from personagent.application.services.operational_memory_queue import (
                OperationalMemoryQueue,
            )

            self._operational_memory_queue = OperationalMemoryQueue(
                url=self._settings.operational_memory_queue_url,
                exchange_name=self._settings.operational_memory_queue_exchange,
                queue_name=self._settings.operational_memory_queue_name,
                prefetch=self._settings.operational_memory_queue_prefetch,
            )
        return self._operational_memory_queue

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
                queue=self.get_operational_memory_queue(),
                queue_enabled=self._settings.operational_memory_queue_enabled,
                queue_fallback_sync=self._settings.operational_memory_queue_fallback_sync,
            )
        return self._operational_memory_service

    def create_extract_memory_worker(self):
        """Create the memory extraction worker."""
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
