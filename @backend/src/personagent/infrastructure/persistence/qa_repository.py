"""Postgres implementation of QA repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.qa.contracts import (
    CodeEdgeData,
    CodeNodeData,
    QARequestRunData,
    QARequestRunStatus,
    QARuntimeEventData,
    QASessionData,
    QASessionStatus,
    TraceMode,
)
from personagent.infrastructure.persistence.models import (
    QACodeEdgeORM,
    QACodeNodeORM,
    QARequestRunORM,
    QARuntimeEventORM,
    QASessionORM,
)


def _session_data(orm: QASessionORM) -> QASessionData:
    return QASessionData(
        id=str(orm.id),
        repo_root=str(orm.repo_root),
        sandbox_path=str(orm.sandbox_path) if orm.sandbox_path else None,
        base_commit=str(orm.base_commit) if orm.base_commit else None,
        branch_name=str(orm.branch_name) if orm.branch_name else None,
        branch_mode=str(orm.branch_mode),
        env_profile=orm.env_profile,
        trace_mode=TraceMode(str(orm.trace_mode or TraceMode.FUNCTION.value)),
        agent_id=str(orm.agent_id) if orm.agent_id else None,
        status=QASessionStatus(str(orm.status or QASessionStatus.ACTIVE.value)),
        metadata=dict(orm.metadata_ or {}),
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _code_node_data(orm: QACodeNodeORM) -> CodeNodeData:
    return CodeNodeData(
        id=str(orm.node_key),
        kind=orm.kind,
        name=str(orm.name),
        file_path=str(orm.file_path) if orm.file_path else None,
        start_line=orm.start_line,
        end_line=orm.end_line,
        metadata=dict(orm.metadata_ or {}),
    )


def _code_edge_data(orm: QACodeEdgeORM) -> CodeEdgeData:
    return CodeEdgeData(
        id=str(orm.edge_key),
        kind=orm.kind,
        source_id=str(orm.source_node_key),
        target_id=str(orm.target_node_key),
        metadata=dict(orm.metadata_ or {}),
    )


def _runtime_event_data(orm: QARuntimeEventORM) -> QARuntimeEventData:
    return QARuntimeEventData(
        id=str(orm.event_key),
        session_id=str(orm.session_id),
        request_id=str(orm.request_id) if orm.request_id else None,
        sequence=int(orm.sequence or 0),
        trace_id=str(orm.trace_id),
        span_id=str(orm.span_id) if orm.span_id else None,
        parent_id=str(orm.parent_id) if orm.parent_id else None,
        event_type=orm.event_type,
        function=str(orm.function) if orm.function else None,
        file=str(orm.file_path) if orm.file_path else None,
        line=orm.line,
        duration_ms=float(orm.duration_ms) if orm.duration_ms is not None else None,
        exception=str(orm.exception) if orm.exception else None,
        sanitized_payload=dict(orm.sanitized_payload or {}),
        created_at=orm.created_at,
    )


def _request_run_data(orm: QARequestRunORM) -> QARequestRunData:
    return QARequestRunData(
        id=str(orm.id),
        session_id=str(orm.session_id),
        method=str(orm.method),
        path=str(orm.path),
        status=QARequestRunStatus(str(orm.status)),
        trace_id=str(orm.trace_id or ""),
        status_code=orm.status_code,
        duration_ms=float(orm.duration_ms) if orm.duration_ms is not None else None,
        request=dict(orm.request_payload or {}),
        response=dict(orm.response_payload or {}),
        error=str(orm.error) if orm.error else None,
        created_at=orm.created_at,
        finished_at=orm.finished_at,
    )


class QARepository:
    """Encapsulates all QA-related SQLAlchemy persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(self, session_data: dict[str, Any]) -> QASessionData:
        orm = QASessionORM(**session_data)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _session_data(orm)

    async def get_session(self, session_id: UUID) -> QASessionORM | None:
        return await self._session.get(QASessionORM, session_id)

    async def update_session_metadata(self, session_id: UUID, metadata: dict[str, Any]) -> None:
        orm = await self._session.get(QASessionORM, session_id)
        if orm is not None:
            orm.metadata_ = metadata
            orm.updated_at = datetime.now(UTC)

    async def clear_code_graph(self, session_id: UUID) -> None:
        await self._session.execute(delete(QACodeEdgeORM).where(QACodeEdgeORM.session_id == session_id))
        await self._session.execute(delete(QACodeNodeORM).where(QACodeNodeORM.session_id == session_id))

    async def add_code_nodes(self, nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            self._session.add(QACodeNodeORM(**node))

    async def add_code_edges(self, edges: list[dict[str, Any]]) -> None:
        for edge in edges:
            self._session.add(QACodeEdgeORM(**edge))

    async def create_request_run(self, run_data: dict[str, Any]) -> QARequestRunData:
        orm = QARequestRunORM(**run_data)
        self._session.add(orm)
        await self._session.commit()
        return _request_run_data(orm)

    async def update_request_run(self, run_id: UUID, fields: dict[str, Any]) -> None:
        orm = await self._session.get(QARequestRunORM, run_id)
        if orm is None:
            return
        for key, value in fields.items():
            if hasattr(orm, key):
                setattr(orm, key, value)

    async def persist_events(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            self._session.add(QARuntimeEventORM(**event))

    async def load_nodes(self, session_id: UUID) -> list[CodeNodeData]:
        result = await self._session.execute(
            select(QACodeNodeORM)
            .where(QACodeNodeORM.session_id == session_id)
            .order_by(QACodeNodeORM.file_path, QACodeNodeORM.start_line)
        )
        return [_code_node_data(orm) for orm in result.scalars().all()]

    async def load_edges(self, session_id: UUID) -> list[CodeEdgeData]:
        result = await self._session.execute(
            select(QACodeEdgeORM)
            .where(QACodeEdgeORM.session_id == session_id)
            .order_by(QACodeEdgeORM.kind, QACodeEdgeORM.edge_key)
        )
        return [_code_edge_data(orm) for orm in result.scalars().all()]

    async def list_events(self, session_id: UUID, *, limit: int = 500) -> list[QARuntimeEventData]:
        result = await self._session.execute(
            select(QARuntimeEventORM)
            .where(QARuntimeEventORM.session_id == session_id)
            .order_by(QARuntimeEventORM.created_at.desc(), QARuntimeEventORM.sequence.desc())
            .limit(max(1, min(limit, 5_000)))
        )
        events = [_runtime_event_data(orm) for orm in result.scalars().all()]
        return list(reversed(events))

    async def recent_runs(self, session_id: UUID, *, limit: int) -> list[QARequestRunData]:
        result = await self._session.execute(
            select(QARequestRunORM)
            .where(QARequestRunORM.session_id == session_id)
            .order_by(QARequestRunORM.created_at.desc())
            .limit(limit)
        )
        return [_request_run_data(orm) for orm in result.scalars().all()]

    async def commit(self) -> None:
        await self._session.commit()
