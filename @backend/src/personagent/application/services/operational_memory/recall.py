"""Operational memory recall and ranking logic."""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from typing import TYPE_CHECKING, Any

import structlog

from personagent.domain.memory.models.operational import (
    MemoryContextBudget,
    RecallFinding,
    StructuredMemoryPackage,
)

if TYPE_CHECKING:
    from personagent.domain.memory.services.operational_memory import (
        OperationalMemoryRedactor,
    )
    from personagent.infrastructure.llm.embedding_adapter import (
        OpenAICompatibleEmbeddingAdapter,
    )
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


class OperationalMemoryRecall:
    """Coordinates operational memory recall and ranking."""

    def __init__(
        self,
        *,
        repository: OperationalMemoryRepository,
        redactor: OperationalMemoryRedactor,
        embedding_adapter: OpenAICompatibleEmbeddingAdapter | None,
        embeddings_enabled: bool,
        recall_enabled: bool,
        recall_top_k: int,
        context_budget_tokens: int | None,
        semantic_candidate_limit: int,
        recent_candidate_limit: int,
        hot_cache: dict[str, deque[RecallFinding]],
    ) -> None:
        self._repository = repository
        self._redactor = redactor
        self._embedding_adapter = embedding_adapter
        self._embeddings_enabled = embeddings_enabled
        self._recall_enabled = recall_enabled
        self._recall_top_k = recall_top_k
        self._context_budget_tokens = context_budget_tokens
        self._semantic_candidate_limit = semantic_candidate_limit
        self._recent_candidate_limit = recent_candidate_limit
        self._hot_cache = hot_cache

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

    async def _embed_query(self, query: str) -> list[float] | None:
        if not self._embeddings_enabled or self._embedding_adapter is None:
            return None
        try:
            vectors = await self._embedding_adapter.embed([self._redactor.redact_text(query)])
        except Exception as exc:
            logger.warning("operational_memory_query_embedding_failed", error=str(exc))
            return None
        return vectors[0] if vectors else None

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


def _empty_structured_package() -> StructuredMemoryPackage:
    return StructuredMemoryPackage(
        formatted="",
        items=[],
        filters_applied={},
        budget_used=0,
        budget_tokens=0,
        omitted_count=0,
        latency_ms=0,
    )


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
