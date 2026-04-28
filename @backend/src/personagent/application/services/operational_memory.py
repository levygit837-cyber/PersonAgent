"""Application service for persistent operational RAG memory."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

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
    OperationalMemoryFormatter,
    OperationalMemoryRedactor,
    stable_hash,
)
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext

if TYPE_CHECKING:
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
        self._redactor = OperationalMemoryRedactor()
        self._hot_cache: dict[str, deque[RecallFinding]] = defaultdict(
            lambda: deque(maxlen=max(1, hot_cache_size))
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
    ) -> str:
        if not self._recall_enabled:
            return ""
        if not _should_recall_operational_memory(query):
            logger.debug("operational_memory_recall_skipped", reason="query_intent_gate")
            return ""
        query_embedding = await self._embed_query(query)
        findings: list[RecallFinding] = []
        try:
            findings = await self._repository.recall(
                project_slug=project_slug,
                query=self._redactor.redact_text(query),
                query_embedding=query_embedding,
                top_k=top_k or self._recall_top_k,
                filters={"candidate_limit": 500},
                provider=provider,
                model=model,
            )
        except Exception:
            logger.warning("operational_memory_recall_failed", exc_info=True)
        findings = self._merge_hot_findings(project_slug, query, findings, top_k or self._recall_top_k)
        return OperationalMemoryFormatter.format_findings(findings)

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
        return stats

    async def _capture_event(
        self,
        event: MemoryEvent,
        *,
        content: str,
        file_path: str | None = None,
    ) -> None:
        try:
            await self._repository.record_event(event)
            chunks = self._chunker.chunk_text(
                project_slug=event.project_slug,
                source_type=event.event_type.value,
                source_id=str(event.id),
                content=content,
                file_path=file_path,
                event_id=event.id,
            )
            chunks = await self._repository.record_chunks(chunks)
            self._remember_hot(event, chunks)
            await self._embed_chunks(chunks)
        except Exception:
            logger.warning(
                "operational_memory_capture_failed",
                event_type=event.event_type.value,
                project_slug=event.project_slug,
                exc_info=True,
            )

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
        except Exception:
            logger.warning("operational_memory_query_embedding_failed", exc_info=True)
            return None
        return vectors[0] if vectors else None

    async def _safe_record_decision(self, decision: DecisionMemory) -> None:
        try:
            await self._repository.record_decision(decision)
        except Exception:
            logger.warning("operational_memory_decision_record_failed", exc_info=True)

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

    def _merge_hot_findings(
        self,
        project_slug: str,
        query: str,
        findings: list[RecallFinding],
        top_k: int,
    ) -> list[RecallFinding]:
        seen = {source_id for finding in findings for source_id in finding.source_ids}
        query_terms = {
            term.lower().strip(".,:;()[]{}'\"`")
            for term in query.replace("_", " ").replace("-", " ").split()
            if len(term) >= 3
        }
        for finding in self._hot_cache.get(project_slug, ()):
            if any(source_id in seen for source_id in finding.source_ids):
                continue
            text = " ".join([finding.finding, *finding.evidence, *finding.paths]).lower()
            if query_terms and not any(term in text for term in query_terms):
                continue
            findings.append(finding)
            seen.update(finding.source_ids)
            if len(findings) >= top_k:
                break
        return findings[:top_k]

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

    def _compact_json(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)


def project_slug_from_workspace(workspace_root: str | None) -> str:
    if not workspace_root:
        return "default"
    name = Path(workspace_root).name
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).lower() or "default"


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
