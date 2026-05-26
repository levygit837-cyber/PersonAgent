"""Data mapper functions for QA service ORM-to-DTO conversions."""

from __future__ import annotations

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
