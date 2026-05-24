"""Chunk, embedding, structured-item, and decision persistence.

Extracted from ``OperationalMemoryRepository`` (Slice 3).
Owns write-path persistence for all memory artifacts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from personagent.domain.memory.models.operational import (
    DecisionMemory,
    EmbeddingStatus,
    MemoryChunk,
    OperationalMemoryFilter,
    StructuredMemoryItem,
    StructuredMemoryType,
)
from personagent.domain.memory.services.operational_memory import (
    stable_hash,
)
from personagent.infrastructure.persistence.models import (
    MemoryDecisionORM,
    MemoryEmbeddingORM,
    MemoryRecallLogORM,
    OperationalMemoryChunkORM,
    OperationalMemoryEventORM,
    StructuredMemoryItemORM,
)
from personagent.infrastructure.persistence.operational_memory.event_outbox import (
    _uuid_or_none,
)


class StructuredItemStore:
    """Write-path persistence for chunks, embeddings, structured items,
    decisions, and recall-skip audit logs."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_chunks(self, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        if not chunks:
            return []
        stored: list[MemoryChunk] = []
        async with self._session_factory() as session:
            for chunk in chunks:
                existing = await session.scalar(
                    select(OperationalMemoryChunkORM).where(
                        OperationalMemoryChunkORM.project_slug == chunk.project_slug,
                        OperationalMemoryChunkORM.source_type == chunk.source_type,
                        OperationalMemoryChunkORM.content_hash == chunk.content_hash,
                    )
                )
                if existing is not None:
                    chunk.id = existing.id
                    chunk.embedding_status = EmbeddingStatus(str(existing.embedding_status))
                    stored.append(chunk)
                    continue
                row = OperationalMemoryChunkORM(
                    id=chunk.id,
                    event_id=chunk.event_id,
                    project_slug=chunk.project_slug,
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                    file_path=chunk.file_path,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=chunk.content_hash or "",
                    language=chunk.language,
                    symbols=chunk.symbols,
                    imports=chunk.imports,
                    token_count=chunk.token_count,
                    embedding_status=chunk.embedding_status.value,
                    embedding_error=chunk.embedding_error,
                    created_at=chunk.created_at,
                    updated_at=chunk.updated_at,
                )
                session.add(row)
                stored.append(chunk)
            await session.commit()
        return stored

    async def record_embeddings(
        self,
        *,
        chunks: list[MemoryChunk],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> None:
        if not chunks or not vectors:
            return
        async with self._session_factory() as session:
            for chunk, vector in zip(chunks, vectors, strict=False):
                if not vector:
                    continue
                existing_embedding = await session.scalar(
                    select(MemoryEmbeddingORM).where(
                        MemoryEmbeddingORM.chunk_id == chunk.id,
                        MemoryEmbeddingORM.embedding_model == embedding_model,
                    )
                )
                if existing_embedding is not None:
                    row = await session.get(OperationalMemoryChunkORM, chunk.id)
                    if row is not None:
                        row.embedding_status = EmbeddingStatus.EMBEDDED.value
                        row.embedding_error = None
                    continue
                session.add(
                    MemoryEmbeddingORM(
                        chunk_id=chunk.id,
                        project_slug=chunk.project_slug,
                        embedding_model=embedding_model,
                        dimensions=len(vector),
                        embedding=vector,
                        content_hash=chunk.content_hash or "",
                    )
                )
                row = await session.get(OperationalMemoryChunkORM, chunk.id)
                if row is not None:
                    row.embedding_status = EmbeddingStatus.EMBEDDED.value
                    row.embedding_error = None
            await session.commit()

    async def mark_chunks_failed(self, chunks: list[MemoryChunk], error: str) -> None:
        if not chunks:
            return
        async with self._session_factory() as session:
            for chunk in chunks:
                row = await session.get(OperationalMemoryChunkORM, chunk.id)
                if row is not None:
                    row.embedding_status = EmbeddingStatus.FAILED.value
                    row.embedding_error = error[:2_000]
            await session.commit()

    async def record_structured_items(
        self, items: list[StructuredMemoryItem]
    ) -> list[StructuredMemoryItem]:
        if not items:
            return []
        stored: list[StructuredMemoryItem] = []
        async with self._session_factory() as session:
            for item in items:
                project_slug = str(item.metadata.get("project_slug") or "").strip()
                if not project_slug:
                    continue
                source_chunk_id = _uuid_or_none((item.source_ids or [None])[0])
                content_hash = str(item.metadata.get("content_hash") or stable_hash(item.summary))
                event_type = item.event_types[0] if item.event_types else None
                source_type = str(item.metadata.get("source_type") or event_type or item.type.value)
                existing = await session.scalar(
                    select(StructuredMemoryItemORM).where(
                        StructuredMemoryItemORM.project_slug == project_slug,
                        StructuredMemoryItemORM.content_hash == content_hash,
                    )
                )
                if existing is not None:
                    continue
                primary_path = item.paths[0] if item.paths else None
                search_text = _structured_search_text(item, primary_path, source_type)
                if item.metadata.get("is_latest", True) and primary_path:
                    await session.execute(
                        update(StructuredMemoryItemORM)
                        .where(
                            StructuredMemoryItemORM.project_slug == project_slug,
                            StructuredMemoryItemORM.item_type == item.type.value,
                            StructuredMemoryItemORM.primary_path == primary_path,
                        )
                        .values(is_latest=False)
                    )
                session.add(
                    StructuredMemoryItemORM(
                        project_slug=project_slug,
                        conversation_id=_uuid_or_none(item.metadata.get("conversation_id")),
                        session_id=item.metadata.get("session_id"),
                        workspace_root=item.metadata.get("workspace_root"),
                        item_type=item.type.value,
                        status=item.status,
                        trust_level=item.trust_level,
                        importance=float(item.importance),
                        source_type=source_type,
                        source_id=str(item.metadata.get("source_id") or source_chunk_id or ""),
                        source_chunk_id=source_chunk_id,
                        primary_path=primary_path,
                        summary=item.summary,
                        evidence=item.evidence,
                        paths=item.paths,
                        source_ids=item.source_ids,
                        metadata_=item.metadata,
                        content_hash=content_hash,
                        search_text=search_text,
                        search_vector=func.to_tsvector(text("'simple'"), search_text),
                        state_reason=item.metadata.get("state_reason"),
                        superseded_by_id=_uuid_or_none(item.metadata.get("superseded_by_id")),
                        last_verified_at=item.metadata.get("last_verified_at"),
                        ranking_metadata=item.metadata.get("ranking_metadata") or {},
                        is_latest=bool(item.metadata.get("is_latest", True)),
                        created_at=item.created_at,
                    )
                )
                stored.append(item)
            await session.commit()
        return stored

    async def backfill_structured_items(
        self, project_slug: str, *, limit: int = 5_000
    ) -> dict[str, Any]:
        """Create prompt-facing structured records from already stored raw chunks."""

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(OperationalMemoryChunkORM, OperationalMemoryEventORM)
                    .join(
                        OperationalMemoryEventORM,
                        OperationalMemoryChunkORM.event_id == OperationalMemoryEventORM.id,
                        isouter=True,
                    )
                    .where(OperationalMemoryChunkORM.project_slug == project_slug)
                    .order_by(desc(OperationalMemoryChunkORM.created_at))
                    .limit(max(1, min(50_000, limit)))
                )
            ).all()

        items = [
            _structured_item_from_chunk_event(chunk, event)
            for chunk, event in rows
            if chunk.content and chunk.content.strip()
        ]
        stored = await self.record_structured_items(
            [item for item in items if item is not None]
        )
        return {
            "project_slug": project_slug,
            "examined_chunks": len(rows),
            "derived_items": len(items),
            "stored_items": len(stored),
        }

    async def record_decision(self, decision: DecisionMemory) -> DecisionMemory:
        async with self._session_factory() as session:
            row = MemoryDecisionORM(
                id=decision.id,
                project_slug=decision.project_slug,
                conversation_id=_uuid_or_none(decision.conversation_id),
                decision=decision.decision,
                context=decision.context,
                alternatives_considered=decision.alternatives_considered,
                reason=decision.reason,
                status=decision.status.value,
                source_event_id=decision.source_event_id,
                embedding_status=decision.embedding_status.value,
                created_at=decision.created_at,
                updated_at=decision.updated_at,
            )
            session.add(row)
            await session.commit()
        return decision

    async def record_recall_skip(
        self,
        *,
        project_slug: str,
        query: str,
        filters: dict[str, Any],
        reason: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        memory_filter = OperationalMemoryFilter.from_mapping(filters)
        async with self._session_factory() as session:
            session.add(
                MemoryRecallLogORM(
                    project_slug=project_slug,
                    workspace_root=memory_filter.workspace_root,
                    conversation_id=_uuid_or_none(memory_filter.current_conversation_id),
                    recall_scope="skipped",
                    query_intent=reason,
                    query=query,
                    filters=memory_filter.to_log_dict(),
                    result_ids=[],
                    scores={},
                    candidate_count=0,
                    selected_count=0,
                    discarded_candidates=[],
                    included_reasons=[],
                    ranking_breakdown={"skipped": reason},
                    token_usage={"budget_tokens": 0, "budget_used": 0},
                    budget_tokens=0,
                    budget_used=0,
                    latency_ms=0,
                    provider=provider,
                    model=model,
                )
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Module-level helpers (moved from operational_memory_repository.py)
# ---------------------------------------------------------------------------


def _structured_search_text(
    item: StructuredMemoryItem,
    primary_path: str | None,
    source_type: str,
) -> str:
    return " ".join(
        part
        for part in [
            item.summary,
            primary_path or "",
            source_type,
            item.type.value,
            item.status,
            item.trust_level,
            " ".join(item.paths),
            " ".join(item.evidence),
            " ".join(item.event_types),
        ]
        if part
    )[:20_000]


def _trust_level_from_event_type(event_type: str) -> str:
    if event_type in {"user_message", "assistant_message"}:
        return "low"
    if event_type in {"tool_call", "tool_result", "command_executed", "file_read"}:
        return "medium"
    return "high"


def _importance_from_event_type(event_type: str) -> float:
    if event_type in {"decision", "agent_state", "diff_applied", "error_found", "solution_attempted"}:
        return 0.95
    if event_type in {"test_result", "file_created", "file_edited", "dependency_installed"}:
        return 0.8
    if event_type in {"command_executed", "tool_result"}:
        return 0.6
    if event_type in {"user_message", "assistant_message"}:
        return 0.2
    return 0.5


def _structured_type_from_event_type(event_type: str) -> StructuredMemoryType:
    if event_type == "operational_summary":
        return StructuredMemoryType.SESSION_SUMMARY
    if event_type == "decision":
        return StructuredMemoryType.DECISION
    if event_type == "agent_state":
        return StructuredMemoryType.LATEST_STATE
    if event_type in {"error_found", "solution_attempted"}:
        return StructuredMemoryType.ERROR_SOLUTION
    if event_type in {"file_created", "file_edited", "file_read", "diff_applied"}:
        return StructuredMemoryType.FILE_STATE
    if event_type == "test_result":
        return StructuredMemoryType.TEST_RESULT
    if event_type in {"command_executed", "dependency_installed"}:
        return StructuredMemoryType.COMMAND_RESULT
    if event_type in {"tool_call", "tool_result"}:
        return StructuredMemoryType.TOOL_TRACE
    return StructuredMemoryType.FACT


def _summary_from_structured_source(
    *,
    item_type: StructuredMemoryType,
    event_type: str,
    tool_name: str | None,
    path: str | None,
    text: str,
) -> str:
    prefix_by_type = {
        StructuredMemoryType.SESSION_SUMMARY: "Session summary",
        StructuredMemoryType.DECISION: "Decision",
        StructuredMemoryType.LATEST_STATE: "Latest state",
        StructuredMemoryType.ERROR_SOLUTION: "Error or fix",
        StructuredMemoryType.FILE_STATE: "File state",
        StructuredMemoryType.COMMAND_RESULT: "Command result",
        StructuredMemoryType.TEST_RESULT: "Test result",
        StructuredMemoryType.TOOL_TRACE: "Tool trace",
        StructuredMemoryType.FACT: "Operational fact",
    }
    source = event_type.replace("_", " ")
    if tool_name:
        source = f"{source} via {tool_name}"
    if path:
        source = f"{source} in {path}"
    return f"{prefix_by_type[item_type]} from {source}: {_excerpt(text, limit=420)}"


def _excerpt(text: str, limit: int = 420, query_terms: set[str] | None = None) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    if query_terms:
        lower = compact.lower()
        best: tuple[int, int, int] | None = None
        for term in query_terms:
            if not term:
                continue
            position = lower.find(term)
            while position >= 0:
                start = max(0, position - max(40, limit // 5))
                end = min(len(compact), start + limit)
                if end - start < limit:
                    start = max(0, end - limit)
                window = lower[start:end]
                matched_terms = sum(1 for candidate in query_terms if candidate in window)
                identifier_bonus = 1 if _has_identifier(compact[start:end]) else 0
                score = matched_terms + identifier_bonus
                candidate_window = (score, position, start)
                if best is None or candidate_window > best:
                    best = candidate_window
                position = lower.find(term, position + len(term))
        if best is not None:
            start = best[2]
            end = min(len(compact), start + limit)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(compact) else ""
            return f"{prefix}{compact[start:end]}{suffix}"
    head_size = max(120, limit // 2 - 3)
    tail_size = max(120, limit - head_size - 5)
    return f"{compact[:head_size]} ... {compact[-tail_size:]}"


def _has_identifier(text: str) -> bool:
    for token in text.replace("`", " ").split():
        stripped = token.strip(".,:;()[]{}'\"")
        if "_" in stripped and stripped.upper() == stripped and len(stripped) >= 6:
            return True
    return False


def _structured_item_from_chunk_event(
    chunk: OperationalMemoryChunkORM,
    event: OperationalMemoryEventORM | None,
) -> StructuredMemoryItem | None:
    content = " ".join(str(chunk.content or "").split())
    if not content:
        return None
    event_type = str(event.event_type if event else chunk.source_type)
    item_type = _structured_type_from_event_type(event_type)
    primary_path = chunk.file_path or ((event.paths or [None])[0] if event else None)
    paths = [path for path in [primary_path, *((event.paths or []) if event else [])] if path]
    paths = list(dict.fromkeys(str(path) for path in paths))
    summary = _summary_from_structured_source(
        item_type=item_type,
        event_type=event_type,
        tool_name=event.tool_name if event else None,
        path=primary_path,
        text=content,
    )
    evidence = [_excerpt(content, limit=350)]
    metadata = {
        "project_slug": chunk.project_slug,
        "conversation_id": str(event.conversation_id) if event and event.conversation_id else None,
        "session_id": event.session_id if event else None,
        "workspace_root": event.workspace_root if event else None,
        "source_type": event_type,
        "source_id": str(event.id) if event else chunk.source_id,
        "content_hash": stable_hash("|".join([item_type.value, summary, str(chunk.id)])),
        "is_latest": item_type
        in {
            StructuredMemoryType.LATEST_STATE,
            StructuredMemoryType.DECISION,
            StructuredMemoryType.FILE_STATE,
        },
    }
    return StructuredMemoryItem(
        type=item_type,
        summary=summary,
        evidence=evidence,
        paths=paths,
        source_ids=[str(chunk.id)],
        event_types=[event_type],
        status="active",
        trust_level=_trust_level_from_event_type(event_type),
        importance=_importance_from_event_type(event_type),
        created_at=chunk.created_at,
        metadata=metadata,
    )
