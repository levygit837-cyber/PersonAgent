"""Application service for persistent operational RAG memory."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from personagent.application.services.operational_memory.capture import (
    OperationalMemoryCapture,
)
from personagent.application.services.operational_memory.extraction import (
    OperationalMemoryExtractor,
)
from personagent.application.services.operational_memory.recall import (
    OperationalMemoryRecall,
)
from personagent.application.services.operational_memory.recall import (
    _should_recall_operational_memory as _should_recall_operational_memory,
)
from personagent.domain.memory.models.operational import (
    RecallFinding,
    StructuredMemoryPackage,
)
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
)
from personagent.domain.tools import ToolCall, ToolResult, ToolUseContext

if TYPE_CHECKING:
    from personagent.application.services.session.operational_memory_queue import (
        OperationalMemoryQueue,
    )
    from personagent.infrastructure.llm.shared.embedding_adapter import (
        OpenAICompatibleEmbeddingAdapter,
    )
    from personagent.infrastructure.persistence.operational_memory_repository import (
        OperationalMemoryRepository,
    )

logger = structlog.get_logger(__name__)


class OperationalMemoryService:
    """Captures, indexes, and recalls operational execution memory."""

    def __init__(
        self,
        *,
        repository: OperationalMemoryRepository,
        embedding_adapter: OpenAICompatibleEmbeddingAdapter | None,
        embedding_model: str,
        embeddings_enabled: bool = True,
        recall_enabled: bool = True,
        capture_tools_enabled: bool = True,
        max_capture_chars: int = 24_000,
        chunk_max_chars: int = 4_000,
        recall_top_k: int = 6,
        hot_cache_size: int = 100,
        semantic_candidate_limit: int = 80,
        recent_candidate_limit: int = 40,
        context_budget_tokens: int | None = None,
        queue: OperationalMemoryQueue | None = None,
        queue_enabled: bool = False,
        queue_fallback_sync: bool = True,
    ) -> None:
        self._repository = repository
        self._embedding_adapter = embedding_adapter
        self._embedding_model = embedding_model
        self._embeddings_enabled = embeddings_enabled
        self._recall_enabled = recall_enabled
        self._capture_tools_enabled = capture_tools_enabled
        self._max_capture_chars = max(2_000, max_capture_chars)
        self._chunker = OperationalMemoryChunker(max_chars=chunk_max_chars)
        self._recall_top_k = max(1, recall_top_k)
        self._semantic_candidate_limit = max(1, semantic_candidate_limit)
        self._recent_candidate_limit = max(0, recent_candidate_limit)
        self._context_budget_tokens = (
            max(1, context_budget_tokens) if context_budget_tokens and context_budget_tokens > 0 else None
        )
        self._queue = queue
        self._queue_enabled = queue_enabled
        self._queue_fallback_sync = queue_fallback_sync
        self._redactor = OperationalMemoryRedactor()
        self._hot_cache: dict[str, deque[RecallFinding]] = defaultdict(
            lambda: deque(maxlen=max(1, hot_cache_size))
        )
        self._extractor = OperationalMemoryExtractor()
        self._capture = OperationalMemoryCapture(
            repository=repository,
            redactor=self._redactor,
            chunker=self._chunker,
            extractor=self._extractor,
            embedding_adapter=embedding_adapter,
            embeddings_enabled=embeddings_enabled,
            embedding_model=embedding_model,
            capture_tools_enabled=capture_tools_enabled,
            max_capture_chars=self._max_capture_chars,
            queue=queue,
            queue_enabled=queue_enabled,
            queue_fallback_sync=queue_fallback_sync,
            hot_cache=self._hot_cache,
        )
        self._recall = OperationalMemoryRecall(
            repository=repository,
            redactor=self._redactor,
            embedding_adapter=embedding_adapter,
            embeddings_enabled=embeddings_enabled,
            recall_enabled=recall_enabled,
            recall_top_k=self._recall_top_k,
            context_budget_tokens=self._context_budget_tokens,
            semantic_candidate_limit=self._semantic_candidate_limit,
            recent_candidate_limit=self._recent_candidate_limit,
            hot_cache=self._hot_cache,
        )

    @property
    def repository(self) -> OperationalMemoryRepository:
        return self._repository

    async def capture_user_message(
        self,
        *,
        project_slug: str,
        workspace_root: str | None,
        conversation_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._capture.capture_user_message(
            project_slug=project_slug,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            message=message,
            metadata=metadata,
        )

    async def capture_assistant_message(
        self,
        *,
        project_slug: str,
        workspace_root: str | None,
        conversation_id: str,
        content: str,
        reasoning_content: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        await self._capture.capture_assistant_message(
            project_slug=project_slug,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            content=content,
            reasoning_content=reasoning_content,
            provider=provider,
            model=model,
            finish_reason=finish_reason,
        )

    async def capture_tool_result(
        self,
        *,
        project_slug: str,
        workspace_root: str | None,
        conversation_id: str,
        call: ToolCall,
        result: ToolResult,
        context: ToolUseContext | None = None,
        task: str | None = None,
    ) -> None:
        await self._capture.capture_tool_result(
            project_slug=project_slug,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            call=call,
            result=result,
            context=context,
            task=task,
        )

    async def capture_turn_summary(
        self,
        *,
        project_slug: str,
        workspace_root: str | None,
        conversation_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._capture.capture_turn_summary(
            project_slug=project_slug,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            summary=summary,
            metadata=metadata,
        )

    async def recall_for_prompt(
        self,
        *,
        project_slug: str,
        query: str,
        provider: str | None = None,
        model: str | None = None,
        top_k: int | None = None,
        conversation_id: str | None = None,
        current_conversation_id: str | None = None,
        session_id: str | None = None,
        workspace_root: str | None = None,
        source_types: list[str] | None = None,
        file_paths: list[str] | None = None,
        created_after: Any = None,
        created_before: Any = None,
        latest_only: bool = False,
        active_only: bool = True,
        include_statuses: list[str] | None = None,
        budget_tokens: int | None = None,
        context_window_tokens: int = 262_144,
    ) -> str:
        return await self._recall.recall_for_prompt(
            project_slug=project_slug,
            query=query,
            provider=provider,
            model=model,
            top_k=top_k,
            conversation_id=conversation_id,
            current_conversation_id=current_conversation_id,
            session_id=session_id,
            workspace_root=workspace_root,
            source_types=source_types,
            file_paths=file_paths,
            created_after=created_after,
            created_before=created_before,
            latest_only=latest_only,
            active_only=active_only,
            include_statuses=include_statuses,
            budget_tokens=budget_tokens,
            context_window_tokens=context_window_tokens,
        )

    async def recall_package_for_prompt(
        self,
        *,
        project_slug: str,
        query: str,
        provider: str | None = None,
        model: str | None = None,
        top_k: int | None = None,
        conversation_id: str | None = None,
        current_conversation_id: str | None = None,
        session_id: str | None = None,
        workspace_root: str | None = None,
        source_types: list[str] | None = None,
        file_paths: list[str] | None = None,
        created_after: Any = None,
        created_before: Any = None,
        latest_only: bool = False,
        active_only: bool = True,
        include_statuses: list[str] | None = None,
        budget_tokens: int | None = None,
        context_window_tokens: int = 262_144,
    ) -> StructuredMemoryPackage:
        return await self._recall.recall_package_for_prompt(
            project_slug=project_slug,
            query=query,
            provider=provider,
            model=model,
            top_k=top_k,
            conversation_id=conversation_id,
            current_conversation_id=current_conversation_id,
            session_id=session_id,
            workspace_root=workspace_root,
            source_types=source_types,
            file_paths=file_paths,
            created_after=created_after,
            created_before=created_before,
            latest_only=latest_only,
            active_only=active_only,
            include_statuses=include_statuses,
            budget_tokens=budget_tokens,
            context_window_tokens=context_window_tokens,
        )

    async def status(self, project_slug: str) -> dict[str, Any]:
        stats = await self._repository.stats(project_slug)
        stats["embedding_model"] = self._embedding_model
        stats["embeddings_enabled"] = self._embeddings_enabled
        stats["recall_enabled"] = self._recall_enabled
        stats["hot_cache_items"] = len(self._hot_cache.get(project_slug, ()))
        if self._embedding_adapter is not None:
            stats["embedding_service"] = await self._embedding_adapter.health_check()
        else:
            stats["embedding_service"] = {"status": "disabled"}
        stats["queue_enabled"] = self._queue_enabled
        return stats

    async def process_outbox_message(self, message: dict[str, Any]) -> None:
        """Process one RabbitMQ memory outbox message."""

        outbox_id = str(message.get("id") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        event = await self._repository.get_event(payload.get("event_id") or message.get("event_id"))
        if event is None:
            await self._repository.mark_outbox_failed(outbox_id, "event not found")
            return
        try:
            await self._repository.mark_outbox_processing(outbox_id)
            await self._capture.process_indexing_event(
                event,
                content=str(payload.get("content") or ""),
                file_path=payload.get("file_path"),
            )
            await self._repository.mark_outbox_completed(outbox_id)
        except Exception as exc:
            await self._repository.mark_outbox_failed(outbox_id, str(exc))
            raise

    async def backfill_structured_memory(
        self,
        project_slug: str,
        *,
        limit: int = 5_000,
    ) -> dict[str, Any]:
        return await self._repository.backfill_structured_items(project_slug, limit=limit)


def project_slug_from_workspace(workspace_root: str | None) -> str:
    if not workspace_root:
        return "default"
    name = Path(workspace_root).name
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).lower() or "default"
