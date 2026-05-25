"""Application service for persistent operational RAG memory."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

import structlog

from personagent.application.services.operational_memory.extraction import (
    OperationalMemoryExtractor,
)
from personagent.domain.memory.models.operational import (
    DecisionMemory,
    EmbeddingStatus,
    MemoryChunk,
    MemoryContextBudget,
    MemoryEvent,
    OperationalMemoryEventType,
    RecallFinding,
    StructuredMemoryPackage,
)
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
    stable_hash,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext

if TYPE_CHECKING:
    from personagent.application.services.operational_memory_queue import OperationalMemoryQueue
    from personagent.infrastructure.llm.embedding_adapter import OpenAICompatibleEmbeddingAdapter
    from personagent.infrastructure.persistence.operational_memory_repository import (
        OperationalMemoryRepository,
    )

logger = structlog.get_logger(__name__)


_MEMORY_META_TERMS = {
    "lembranca",
    "lembrancas",
    "lembra",
    "lembrar",
    "memoria",
    "memorias",
    "memory",
    "memories",
    "remember",
}
_MEMORY_CAPABILITY_TERMS = {
    "acessa",
    "acessar",
    "acesso",
    "access",
    "available",
    "capacidade",
    "capabilities",
    "disponivel",
    "disponiveis",
    "possui",
    "tem",
}
_QUERY_STOPWORDS = {
    "a",
    "as",
    "com",
    "como",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "eu",
    "me",
    "na",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "qual",
    "quais",
    "que",
    "se",
    "sua",
    "suas",
    "tem",
    "tenho",
    "voce",
    "voces",
    "what",
    "which",
    "you",
    "your",
}
_OPERATIONAL_ANCHOR_TERMS = {
    "agent",
    "agente",
    "api",
    "arquivo",
    "arquivos",
    "arquitetura",
    "auth",
    "backend",
    "backpressure",
    "benchmark",
    "budget",
    "chunk",
    "chunks",
    "codigo",
    "comando",
    "comandos",
    "cookie",
    "decisao",
    "decisoes",
    "dependencia",
    "dependencias",
    "diff",
    "diffs",
    "duplicar",
    "duplicata",
    "erro",
    "erros",
    "executor",
    "ferramenta",
    "ferramentas",
    "fetch",
    "file",
    "finding",
    "findings",
    "frontend",
    "header",
    "http",
    "idempotency",
    "incidente",
    "incidentes",
    "jwt",
    "marcador",
    "planner",
    "registry",
    "retry",
    "solucao",
    "solucoes",
    "timeout",
    "tool",
    "tools",
}
_CODE_ANCHOR_RE = re.compile(
    r"(`[^`]+`|[\w./-]+\.(?:py|ts|tsx|js|jsx|json|md|toml|ya?ml|css|html|sql)|"
    r"\b[a-z]+_[a-z0-9_]+\b|[A-Z][A-Z0-9_]{3,})"
)


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
        content = self._redactor.redact_text(message)[: self._max_capture_chars]
        await self._capture_event(
            MemoryEvent(
                project_slug=project_slug,
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                event_type=OperationalMemoryEventType.USER_MESSAGE,
                task=content[:1_000],
                input={"message": content},
                metadata=metadata or {},
                source_hash=stable_hash(content),
            ),
            content=content,
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
        redacted_content = self._redactor.redact_text(content)[: self._max_capture_chars]
        redacted_reasoning = self._redactor.redact_text(reasoning_content)[:4_000]
        payload = {
            "content": redacted_content,
            "explicit_provider_reasoning": redacted_reasoning or None,
        }
        text = self._compact_json(payload)
        await self._capture_event(
            MemoryEvent(
                project_slug=project_slug,
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                event_type=OperationalMemoryEventType.ASSISTANT_MESSAGE,
                status=finish_reason,
                output=payload,
                metadata={"provider": provider, "model": model},
                source_hash=stable_hash(text),
            ),
            content=text,
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
        if not self._capture_tools_enabled:
            return

        data = self._redactor.redact_data(result.data)
        arguments = self._redactor.redact_data(call.arguments)
        content = self._redactor.redact_text(result.content)[: self._max_capture_chars]
        event_type = self._event_type_from_tool_result(call, result, data)
        paths = self._paths_from_payload(arguments, data)
        workspace = workspace_root or (str(context.workspace_root) if context else None)
        error = content[:2_000] if result.is_error else None
        source = self._tool_memory_text(call, result, arguments, data, content)

        event = MemoryEvent(
            project_slug=project_slug,
            workspace_root=workspace,
            conversation_id=conversation_id,
            event_type=event_type,
            task=task,
            tool_name=result.tool_name or call.name,
            status=result.status.value,
            input={"tool_call_id": call.id, "arguments": arguments},
            output={"content": content, "data": data},
            error=error,
            paths=paths,
            metadata={
                "cwd": str(context.cwd) if context else None,
                "is_error": result.is_error,
                "permission_required": result.status == ToolExecutionStatus.PERMISSION_REQUIRED,
            },
            source_hash=stable_hash(source),
        )
        await self._capture_event(event, content=source, file_path=paths[0] if paths else None)

        decision = self._decision_from_tool_payload(project_slug, conversation_id, event, data, content)
        if decision is not None:
            await self._safe_record_decision(decision)

    async def capture_turn_summary(
        self,
        *,
        project_slug: str,
        workspace_root: str | None,
        conversation_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        content = self._redactor.redact_text(summary)[: self._max_capture_chars]
        await self._capture_event(
            MemoryEvent(
                project_slug=project_slug,
                workspace_root=workspace_root,
                conversation_id=conversation_id,
                event_type=OperationalMemoryEventType.OPERATIONAL_SUMMARY,
                output={"summary": content},
                metadata=metadata or {},
                source_hash=stable_hash(content),
            ),
            content=content,
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
        package = await self.recall_package_for_prompt(
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
        return package.formatted

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
        if not self._recall_enabled:
            await self._repository.record_recall_skip(
                project_slug=project_slug,
                query=self._redactor.redact_text(query),
                filters={
                    "conversation_id": conversation_id,
                    "current_conversation_id": current_conversation_id,
                    "session_id": session_id,
                    "workspace_root": workspace_root,
                    "source_types": source_types or [],
                    "file_paths": file_paths or [],
                    "latest_only": latest_only,
                    "active_only": active_only,
                    "statuses": include_statuses or [],
                },
                reason="recall_disabled",
                provider=provider,
                model=model,
            )
            return _empty_structured_package()
        if not _should_recall_operational_memory(query):
            logger.debug("operational_memory_recall_skipped", reason="query_intent_gate")
            await self._repository.record_recall_skip(
                project_slug=project_slug,
                query=self._redactor.redact_text(query),
                filters={
                    "conversation_id": conversation_id,
                    "current_conversation_id": current_conversation_id,
                    "session_id": session_id,
                    "workspace_root": workspace_root,
                    "source_types": source_types or [],
                    "file_paths": file_paths or [],
                    "latest_only": latest_only,
                    "active_only": active_only,
                    "statuses": include_statuses or [],
                },
                reason="query_intent_gate",
                provider=provider,
                model=model,
            )
            return _empty_structured_package()
        query_embedding = await self._embed_query(query)
        try:
            budget = MemoryContextBudget.for_context_window(
                context_window_tokens,
                total_tokens=budget_tokens or self._context_budget_tokens,
            )
            return await self._repository.recall_structured_package(
                project_slug=project_slug,
                query=self._redactor.redact_text(query),
                query_embedding=query_embedding,
                top_k=top_k or self._recall_top_k,
                filters={
                    "conversation_id": conversation_id,
                    "current_conversation_id": current_conversation_id,
                    "session_id": session_id,
                    "workspace_root": workspace_root,
                    "source_types": source_types or [],
                    "file_paths": file_paths or [],
                    "created_after": created_after,
                    "created_before": created_before,
                    "latest_only": latest_only,
                    "active_only": active_only,
                    "statuses": include_statuses or [],
                    "semantic_candidate_limit": self._semantic_candidate_limit,
                    "recent_candidate_limit": self._recent_candidate_limit,
                },
                budget=budget,
                provider=provider,
                model=model,
            )
        except Exception:
            logger.warning("operational_memory_recall_failed", exc_info=True)
            return _empty_structured_package()

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

    async def _capture_event(
        self,
        event: MemoryEvent,
        *,
        content: str,
        file_path: str | None = None,
    ) -> None:
        try:
            if self._queue_enabled and self._queue is not None:
                payload = {
                    "event_id": str(event.id),
                    "content": content,
                    "file_path": file_path,
                }
                _, outbox = await self._repository.record_event_with_outbox(
                    event,
                    job_type="index_operational_memory_event",
                    payload=payload,
                    dedupe_key=f"{event.id}:index_operational_memory_event",
                )
                try:
                    await self._queue.publish(outbox)
                    await self._repository.mark_outbox_published(outbox["id"])
                    self._remember_hot_event(event, content, file_path)
                    return
                except Exception as exc:
                    logger.warning("operational_memory_queue_publish_failed", error=str(exc))
                    if not self._queue_fallback_sync:
                        await self._repository.mark_outbox_failed(outbox["id"], str(exc))
                        return
                    await self._process_indexing_event(event, content=content, file_path=file_path)
                    await self._repository.mark_outbox_completed(outbox["id"])
                    return

            await self._repository.record_event(event)
            await self._process_indexing_event(event, content=content, file_path=file_path)
        except Exception:
            logger.warning(
                "operational_memory_capture_failed",
                event_type=event.event_type.value,
                project_slug=event.project_slug,
                exc_info=True,
            )

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
            await self._process_indexing_event(
                event,
                content=str(payload.get("content") or ""),
                file_path=payload.get("file_path"),
            )
            await self._repository.mark_outbox_completed(outbox_id)
        except Exception as exc:
            await self._repository.mark_outbox_failed(outbox_id, str(exc))
            raise

    async def _process_indexing_event(
        self,
        event: MemoryEvent,
        *,
        content: str,
        file_path: str | None = None,
    ) -> None:
        chunks = self._chunker.chunk_text(
            project_slug=event.project_slug,
            source_type=event.event_type.value,
            source_id=str(event.id),
            content=content,
            file_path=file_path,
            event_id=event.id,
        )
        chunks = await self._repository.record_chunks(chunks)
        await self._safe_record_structured_items(event, chunks)
        self._remember_hot(event, chunks)
        await self._embed_chunks(chunks)

    async def _embed_chunks(self, chunks: list[MemoryChunk]) -> None:
        pending = [
            chunk
            for chunk in chunks
            if chunk.embedding_status == EmbeddingStatus.PENDING and chunk.content.strip()
        ]
        if not pending or not self._embeddings_enabled or self._embedding_adapter is None:
            return
        try:
            vectors = await self._embedding_adapter.embed([chunk.content for chunk in pending])
            await self._repository.record_embeddings(
                chunks=pending,
                vectors=vectors,
                embedding_model=self._embedding_model,
            )
        except Exception as exc:
            await self._repository.mark_chunks_failed(pending, str(exc))
            logger.warning("operational_memory_embedding_failed", error=str(exc))

    async def _embed_query(self, query: str) -> list[float] | None:
        if not self._embeddings_enabled or self._embedding_adapter is None:
            return None
        try:
            vectors = await self._embedding_adapter.embed([self._redactor.redact_text(query)])
        except Exception as exc:
            logger.warning("operational_memory_query_embedding_failed", error=str(exc))
            return None
        return vectors[0] if vectors else None

    async def _safe_record_decision(self, decision: DecisionMemory) -> None:
        try:
            await self._repository.record_decision(decision)
        except Exception:
            logger.warning("operational_memory_decision_record_failed", exc_info=True)

    async def _safe_record_structured_items(
        self,
        event: MemoryEvent,
        chunks: list[MemoryChunk],
    ) -> None:
        try:
            await self._repository.record_structured_items(
                self._extractor.structured_items_from_event(event, chunks)
            )
        except Exception:
            logger.warning("operational_memory_structured_record_failed", exc_info=True)

    async def backfill_structured_memory(
        self,
        project_slug: str,
        *,
        limit: int = 5_000,
    ) -> dict[str, Any]:
        return await self._repository.backfill_structured_items(project_slug, limit=limit)


def _should_recall_operational_memory(query: str) -> bool:
    """Return whether a user query is specific enough for execution-memory recall."""

    normalized = _normalize_query(query)
    if not normalized:
        return False

    has_code_anchor = bool(_CODE_ANCHOR_RE.search(query))
    tokens = _query_tokens(normalized)
    if has_code_anchor:
        return True

    if _is_memory_capability_query(tokens):
        return False

    if tokens & _OPERATIONAL_ANCHOR_TERMS:
        return True

    signal_tokens = [
        token
        for token in tokens
        if token not in _QUERY_STOPWORDS
        and token not in _MEMORY_META_TERMS
        and token not in _MEMORY_CAPABILITY_TERMS
        and len(token) >= 4
    ]
    asks_about_specific_memory = bool(tokens & _MEMORY_META_TERMS) and "sobre" in tokens
    return asks_about_specific_memory and bool(signal_tokens)


def _is_memory_capability_query(tokens: set[str]) -> bool:
    if not tokens & _MEMORY_META_TERMS:
        return False
    if tokens & _OPERATIONAL_ANCHOR_TERMS:
        return False
    non_generic = tokens - _QUERY_STOPWORDS - _MEMORY_META_TERMS - _MEMORY_CAPABILITY_TERMS
    return not non_generic or non_generic <= {"sistema", "tipo", "tipos"}


def _normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKD", query)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return ascii_text.lower().strip()


def _query_tokens(normalized_query: str) -> set[str]:
    return {
        token
        for raw in normalized_query.replace("_", " ").replace("-", " ").split()
        for token in [raw.strip(".,:;()[]{}'\"`!?")]
        if token
    }
