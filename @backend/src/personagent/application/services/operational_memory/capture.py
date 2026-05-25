"""Operational memory capture and persistence logic."""

from __future__ import annotations

import json
import re
from collections import deque
from typing import TYPE_CHECKING, Any

import structlog

from personagent.application.services.operational_memory.extraction import (
    OperationalMemoryExtractor,
)
from personagent.domain.memory.models.operational import (
    DecisionMemory,
    DecisionStatus,
    EmbeddingStatus,
    MemoryChunk,
    MemoryEvent,
    OperationalMemoryEventType,
    RecallFinding,
)
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
    stable_hash,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext

if TYPE_CHECKING:
    from personagent.application.services.operational_memory_queue import (
        OperationalMemoryQueue,
    )
    from personagent.infrastructure.llm.embedding_adapter import (
        OpenAICompatibleEmbeddingAdapter,
    )
    from personagent.infrastructure.persistence.operational_memory_repository import (
        OperationalMemoryRepository,
    )

logger = structlog.get_logger(__name__)


class OperationalMemoryCapture:
    """Captures, indexes, and persists operational execution memory events."""

    def __init__(
        self,
        *,
        repository: OperationalMemoryRepository,
        redactor: OperationalMemoryRedactor,
        chunker: OperationalMemoryChunker,
        extractor: OperationalMemoryExtractor,
        embedding_adapter: OpenAICompatibleEmbeddingAdapter | None,
        embeddings_enabled: bool,
        embedding_model: str,
        capture_tools_enabled: bool,
        max_capture_chars: int,
        queue: OperationalMemoryQueue | None,
        queue_enabled: bool,
        queue_fallback_sync: bool,
        hot_cache: dict[str, deque[RecallFinding]],
    ) -> None:
        self._repository = repository
        self._redactor = redactor
        self._chunker = chunker
        self._extractor = extractor
        self._embedding_adapter = embedding_adapter
        self._embeddings_enabled = embeddings_enabled
        self._embedding_model = embedding_model
        self._capture_tools_enabled = capture_tools_enabled
        self._max_capture_chars = max_capture_chars
        self._queue = queue
        self._queue_enabled = queue_enabled
        self._queue_fallback_sync = queue_fallback_sync
        self._hot_cache = hot_cache

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

    async def process_indexing_event(
        self,
        event: MemoryEvent,
        *,
        content: str,
        file_path: str | None = None,
    ) -> None:
        """Process indexing for a single event (used by outbox worker)."""
        await self._process_indexing_event(event, content=content, file_path=file_path)

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

    def _remember_hot(self, event: MemoryEvent, chunks: list[MemoryChunk]) -> None:
        for chunk in chunks:
            self._hot_cache[event.project_slug].appendleft(
                RecallFinding(
                    finding=(
                        f"Evento recente `{event.event_type.value}`"
                        f"{f' via {event.tool_name}' if event.tool_name else ''}: "
                        f"{' '.join(chunk.content.split())[:360]}"
                    ),
                    source_ids=[str(chunk.id)],
                    evidence=[" ".join(chunk.content.split())[:360]],
                    paths=list(event.paths),
                    score=0.25,
                    event_types=[event.event_type.value],
                    created_at=event.created_at,
                )
            )

    def _remember_hot_event(
        self,
        event: MemoryEvent,
        content: str,
        file_path: str | None,
    ) -> None:
        evidence = " ".join(content.split())[:360]
        self._hot_cache[event.project_slug].appendleft(
            RecallFinding(
                finding=(
                    f"Evento recente `{event.event_type.value}`"
                    f"{f' via {event.tool_name}' if event.tool_name else ''}: "
                    f"{evidence}"
                ),
                source_ids=[str(event.id)],
                evidence=[evidence],
                paths=[file_path] if file_path else list(event.paths),
                score=0.2,
                event_types=[event.event_type.value],
                created_at=event.created_at,
            )
        )

    def _event_type_from_tool_result(
        self,
        call: ToolCall,
        result: ToolResult,
        data: dict[str, Any],
    ) -> OperationalMemoryEventType:
        if result.is_error or result.status == ToolExecutionStatus.ERROR:
            return OperationalMemoryEventType.ERROR_FOUND
        data_type = str(data.get("type") or "").lower()
        if data_type == "file_read":
            return OperationalMemoryEventType.FILE_READ
        if data_type == "file_write":
            return (
                OperationalMemoryEventType.FILE_CREATED
                if data.get("created")
                else OperationalMemoryEventType.FILE_EDITED
            )
        if data_type == "file_edit":
            return OperationalMemoryEventType.DIFF_APPLIED
        if data_type == "shell":
            command = str(data.get("command") or call.arguments.get("command") or "")
            if self._looks_like_test_command(command):
                return OperationalMemoryEventType.TEST_RESULT
            if self._looks_like_dependency_install(command):
                return OperationalMemoryEventType.DEPENDENCY_INSTALLED
            return OperationalMemoryEventType.COMMAND_EXECUTED
        if call.name.lower().startswith("task"):
            return OperationalMemoryEventType.AGENT_STATE
        return OperationalMemoryEventType.TOOL_RESULT

    def _tool_memory_text(
        self,
        call: ToolCall,
        result: ToolResult,
        arguments: Any,
        data: Any,
        content: str,
    ) -> str:
        payload = {
            "tool": result.tool_name or call.name,
            "tool_call_id": call.id,
            "status": result.status.value,
            "is_error": result.is_error,
            "arguments": arguments,
            "data": data,
            "content": content,
        }
        return self._compact_json(payload)[: self._max_capture_chars]

    def _paths_from_payload(self, *payloads: Any) -> list[str]:
        paths: list[str] = []
        for payload in payloads:
            if isinstance(payload, dict):
                for key in ("path", "file_path", "display_path"):
                    value = payload.get(key)
                    if isinstance(value, str) and value not in paths:
                        paths.append(value)
                for value in payload.values():
                    if isinstance(value, (dict, list)):
                        for nested in self._paths_from_payload(value):
                            if nested not in paths:
                                paths.append(nested)
            elif isinstance(payload, list):
                for item in payload:
                    for nested in self._paths_from_payload(item):
                        if nested not in paths:
                            paths.append(nested)
        return paths[:20]

    def _decision_from_tool_payload(
        self,
        project_slug: str,
        conversation_id: str,
        event: MemoryEvent,
        data: dict[str, Any],
        content: str,
    ) -> DecisionMemory | None:
        text = " ".join(
            str(data.get(key) or "")
            for key in ("decision", "plan_content", "summary", "content")
        )
        if not text:
            text = content
        if not re.search(r"(?i)\b(decid|decision|arquitetur|planner|executor|superseded|rejected)\b", text):
            return None
        status = DecisionStatus.ACTIVE
        if re.search(r"(?i)\bsuperseded|substitu", text):
            status = DecisionStatus.SUPERSEDED
        elif re.search(r"(?i)\brejected|rejeitad", text):
            status = DecisionStatus.REJECTED
        return DecisionMemory(
            project_slug=project_slug,
            conversation_id=conversation_id,
            decision=text[:1_000],
            context=f"Captured from {event.event_type.value}",
            reason=content[:1_000],
            status=status,
            source_event_id=event.id,
        )

    def _looks_like_dependency_install(self, command: str) -> bool:
        return bool(
            re.search(
                r"\b(pip|uv|poetry|npm|pnpm|yarn|bun|apt|dnf|brew)\b.*\b(install|add|sync)\b",
                command,
            )
        )

    def _looks_like_test_command(self, command: str) -> bool:
        return bool(
            re.search(
                r"\b(pytest|npm\s+test|pnpm\s+test|yarn\s+test|bun\s+test|uv\s+run\s+pytest|ruff|mypy|vitest)\b",
                command,
            )
        )

    def _compact_json(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)
