"""Application service for QA sessions, code graphs, and traced requests."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.qa.contracts import (
    CodeEdgeData,
    CodeEdgeKind,
    CodeNodeData,
    QACodeGraph,
    QAContextResponse,
    QAGraphResponse,
    QAIndexRequest,
    QARequestRunData,
    QARequestRunRequest,
    QARequestRunStatus,
    QARuntimeEventData,
    QASessionCreateRequest,
    QASessionData,
    QASessionStatus,
    RuntimeEventType,
    TraceMode,
)
from personagent.application.qa.indexer import PythonCodeIndexer
from personagent.application.qa.redaction import redact_mapping, redact_value
from personagent.application.qa.runtime_tracer import PythonRuntimeTracer
from personagent.domain.exceptions import InvalidRequestError
from personagent.infrastructure.persistence.models import (
    QACodeEdgeORM,
    QACodeNodeORM,
    QARequestRunORM,
    QARuntimeEventORM,
    QASessionORM,
)


class QASessionService:
    """Coordinates QA session persistence, indexing, and runtime tracing."""

    def __init__(self, session: AsyncSession, *, tracer: PythonRuntimeTracer | None = None) -> None:
        self._session = session
        self._tracer = tracer or _GLOBAL_TRACER

    async def create_session(self, request: QASessionCreateRequest) -> QASessionData:
        repo_root = Path(request.repo_root).expanduser().resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            raise InvalidRequestError(
                f"Repository root not found: {repo_root}",
                code="qa.repo_not_found",
                http_status=404,
            )
        session_id = uuid4()
        base_commit = request.base_commit or await asyncio.to_thread(_git_output, repo_root, ["rev-parse", "HEAD"])
        branch_name: str | None = None
        sandbox_path = str(repo_root)
        metadata: dict[str, Any] = {
            "git_available": bool(base_commit),
            "env_profile": _safe_env_profile(request.env_profile),
        }
        if request.branch_mode == "worktree":
            branch_name = f"codex/qa/{session_id.hex[:10]}"
            sandbox_path = await asyncio.to_thread(
                _create_worktree,
                repo_root,
                branch_name,
                base_commit or "HEAD",
                session_id.hex,
            )
            metadata["sandbox_created"] = True

        orm = QASessionORM(
            id=session_id,
            repo_root=str(repo_root),
            sandbox_path=sandbox_path,
            base_commit=base_commit,
            branch_name=branch_name,
            branch_mode=request.branch_mode,
            env_profile=_safe_env_profile(request.env_profile),
            trace_mode=request.trace_mode.value,
            agent_id=request.agent_id,
            status=QASessionStatus.ACTIVE.value,
            metadata_=metadata,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _session_data(orm)

    async def index_session(
        self,
        session_id: UUID,
        request: QAIndexRequest,
        *,
        app: FastAPI | None = None,
    ) -> QACodeGraph:
        qa_session = await self._get_session(session_id)
        repo_root = Path(str(qa_session.sandbox_path or qa_session.repo_root)).resolve()
        graph = PythonCodeIndexer(repo_root, app=app).build(include_tests=request.include_tests)

        await self._session.execute(delete(QACodeEdgeORM).where(QACodeEdgeORM.session_id == session_id))
        await self._session.execute(delete(QACodeNodeORM).where(QACodeNodeORM.session_id == session_id))
        for node in graph.nodes:
            self._session.add(
                QACodeNodeORM(
                    session_id=session_id,
                    node_key=node.id,
                    kind=node.kind.value,
                    name=node.name,
                    file_path=node.file_path,
                    start_line=node.start_line,
                    end_line=node.end_line,
                    metadata_=node.metadata,
                )
            )
        for edge in graph.edges:
            self._session.add(
                QACodeEdgeORM(
                    session_id=session_id,
                    edge_key=edge.id,
                    kind=edge.kind.value,
                    source_node_key=edge.source_id,
                    target_node_key=edge.target_id,
                    metadata_=edge.metadata,
                )
            )
        qa_session.metadata_ = {**dict(qa_session.metadata_ or {}), "last_index": graph.stats}
        qa_session.updated_at = datetime.now(UTC)
        await self._session.commit()
        return graph

    async def execute_request(
        self,
        session_id: UUID,
        request: QARequestRunRequest,
        *,
        app: FastAPI,
    ) -> QARequestRunData:
        qa_session = await self._get_session(session_id)
        if request.path.startswith("/qa"):
            raise InvalidRequestError(
                "QA routes cannot be recursively executed through the QA tracer.",
                code="qa.recursive_request_denied",
                http_status=400,
            )
        request_id = uuid4()
        trace_mode = request.trace_mode or TraceMode(str(qa_session.trace_mode))
        run = QARequestRunORM(
            id=request_id,
            session_id=session_id,
            method=request.method.upper(),
            path=request.path,
            status=QARequestRunStatus.RUNNING.value,
            trace_id="",
            request_payload=_request_payload(request),
        )
        self._session.add(run)
        await self._session.commit()

        source_root = _source_root(Path(str(qa_session.sandbox_path or qa_session.repo_root)))
        started = time.perf_counter()

        async def operation() -> Response:
            headers = {**request.headers, "x-qa-session-id": str(session_id)}
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://qa.local") as client:
                return await client.request(
                    request.method.upper(),
                    request.path,
                    params=request.query,
                    headers=headers,
                    json=request.json_body,
                    content=request.body if request.json_body is None else None,
                    timeout=request.timeout_seconds,
                )

        try:
            response, events, trace_id = await self._tracer.capture(
                session_id=str(session_id),
                request_id=str(request_id),
                source_roots=[source_root],
                mode=trace_mode,
                request_payload=_request_payload(request),
                operation=operation,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            response_payload = {
                "status_code": response.status_code,
                "headers": redact_mapping(dict(response.headers)),
                "body": _safe_response_text(response.text),
            }
            events.append(
                QARuntimeEventData(
                    id=f"evt_{len(events):06d}",
                    session_id=str(session_id),
                    request_id=str(request_id),
                    sequence=len(events),
                    trace_id=trace_id,
                    event_type=RuntimeEventType.RESPONSE,
                    function="qa.response",
                    duration_ms=duration_ms,
                    sanitized_payload=response_payload,
                )
            )
            self._tracer.event_bus.publish(str(session_id), events[-1])
            run.status = QARequestRunStatus.COMPLETED.value
            run.trace_id = trace_id
            run.status_code = response.status_code
            run.duration_ms = duration_ms
            run.response_payload = response_payload
            run.finished_at = datetime.now(UTC)
            await self._persist_events(session_id, request_id, events)
            await self._session.commit()
            return _request_run_data(run)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            run.status = QARequestRunStatus.FAILED.value
            run.trace_id = run.trace_id or ""
            run.duration_ms = duration_ms
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise

    async def graph_response(self, session_id: UUID) -> QAGraphResponse:
        qa_session = await self._get_session(session_id)
        nodes = await self._load_nodes(session_id)
        edges = await self._load_edges(session_id)
        runtime_edges = await self._runtime_edges(session_id, nodes)
        return QAGraphResponse(
            session=_session_data(qa_session),
            graph=QACodeGraph(
                nodes=nodes,
                edges=edges,
                stats={
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "runtime_edge_count": len(runtime_edges),
                },
            ),
            runtime_edges=runtime_edges,
        )

    async def list_events(self, session_id: UUID, *, limit: int = 500) -> list[QARuntimeEventData]:
        await self._get_session(session_id)
        result = await self._session.execute(
            select(QARuntimeEventORM)
            .where(QARuntimeEventORM.session_id == session_id)
            .order_by(QARuntimeEventORM.created_at.desc(), QARuntimeEventORM.sequence.desc())
            .limit(max(1, min(limit, 5_000)))
        )
        events = [_runtime_event_data(orm) for orm in result.scalars().all()]
        return list(reversed(events))

    async def context_response(self, session_id: UUID) -> QAContextResponse:
        qa_session = await self._get_session(session_id)
        nodes = await self._load_nodes(session_id)
        endpoint_nodes = [node for node in nodes if node.kind.value == "endpoint"]
        events = await self.list_events(session_id, limit=80)
        runs = await self._recent_runs(session_id, limit=10)
        files = sorted({event.file for event in events if event.file})
        summary = (
            f"QA session {qa_session.id} traced {len(runs)} request(s), "
            f"{len(events)} recent runtime event(s), and {len(endpoint_nodes)} indexed endpoint(s)."
        )
        return QAContextResponse(
            session=_session_data(qa_session),
            summary=summary,
            endpoints=[node.model_dump() for node in endpoint_nodes[:80]],
            recent_requests=runs,
            relevant_events=events,
            files=files,
        )

    async def _get_session(self, session_id: UUID) -> QASessionORM:
        orm = await self._session.get(QASessionORM, session_id)
        if orm is None:
            raise InvalidRequestError(
                f"QA session not found: {session_id}",
                code="qa.session_not_found",
                http_status=404,
            )
        return orm

    async def _persist_events(
        self,
        session_id: UUID,
        request_id: UUID,
        events: list[QARuntimeEventData],
    ) -> None:
        for event in events:
            self._session.add(
                QARuntimeEventORM(
                    session_id=session_id,
                    request_id=request_id,
                    event_key=event.id,
                    sequence=event.sequence,
                    trace_id=event.trace_id,
                    span_id=event.span_id,
                    parent_id=event.parent_id,
                    event_type=event.event_type.value,
                    function=event.function,
                    file_path=event.file,
                    line=event.line,
                    duration_ms=event.duration_ms,
                    exception=event.exception,
                    sanitized_payload=event.sanitized_payload,
                )
            )

    async def _load_nodes(self, session_id: UUID) -> list[CodeNodeData]:
        result = await self._session.execute(
            select(QACodeNodeORM)
            .where(QACodeNodeORM.session_id == session_id)
            .order_by(QACodeNodeORM.file_path, QACodeNodeORM.start_line)
        )
        return [_code_node_data(orm) for orm in result.scalars().all()]

    async def _load_edges(self, session_id: UUID) -> list[CodeEdgeData]:
        result = await self._session.execute(
            select(QACodeEdgeORM)
            .where(QACodeEdgeORM.session_id == session_id)
            .order_by(QACodeEdgeORM.kind, QACodeEdgeORM.edge_key)
        )
        return [_code_edge_data(orm) for orm in result.scalars().all()]

    async def _runtime_edges(
        self,
        session_id: UUID,
        nodes: list[CodeNodeData],
    ) -> list[CodeEdgeData]:
        by_location = {
            (node.file_path, node.name): node.id
            for node in nodes
            if node.kind.value in {"controller", "service", "repository", "function"}
        }
        events = await self.list_events(session_id, limit=1_000)
        edges: dict[str, CodeEdgeData] = {}
        previous_node_id: str | None = None
        for event in events:
            if event.event_type.value != "call" or not event.file or not event.function:
                continue
            node_id = by_location.get((event.file, event.function))
            if node_id is None:
                continue
            if previous_node_id and previous_node_id != node_id:
                edge = CodeEdgeData(
                    id=f"runtime:{previous_node_id}:{node_id}",
                    kind=CodeEdgeKind.RUNTIME_CALLED,
                    source_id=previous_node_id,
                    target_id=node_id,
                    metadata={"trace_id": event.trace_id},
                )
                edges[edge.id] = edge
            previous_node_id = node_id
        return list(edges.values())

    async def _recent_runs(self, session_id: UUID, *, limit: int) -> list[QARequestRunData]:
        result = await self._session.execute(
            select(QARequestRunORM)
            .where(QARequestRunORM.session_id == session_id)
            .order_by(QARequestRunORM.created_at.desc())
            .limit(limit)
        )
        return [_request_run_data(orm) for orm in result.scalars().all()]


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


def _request_payload(request: QARequestRunRequest) -> dict[str, Any]:
    return {
        "method": request.method.upper(),
        "path": request.path,
        "query": redact_mapping(request.query),
        "headers": redact_mapping(request.headers),
        "json": redact_value(request.json_body),
        "body": redact_value(request.body),
        "trace_mode": (request.trace_mode.value if request.trace_mode else None),
    }


def _safe_response_text(text: str) -> str:
    return str(redact_value(text, max_string=8_000))


def _safe_env_profile(env_profile: dict[str, str] | str | None) -> dict[str, Any] | str | None:
    if isinstance(env_profile, dict):
        return dict(redact_mapping(env_profile))
    return env_profile


def _source_root(repo_root: Path) -> Path:
    for candidate in (
        repo_root / "@backend" / "src" / "personagent",
        repo_root / "src" / "personagent",
        repo_root / "personagent",
    ):
        if candidate.exists():
            return candidate
    return repo_root


def _git_output(cwd: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _create_worktree(repo_root: Path, branch_name: str, base_commit: str, session_id: str) -> str:
    sandbox_root = Path(tempfile.gettempdir()) / "personagent-qa-sessions" / session_id
    sandbox_root.mkdir(parents=True, exist_ok=True)
    worktree_path = sandbox_root / "worktree"
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_path), base_commit],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise InvalidRequestError(
            f"Could not create QA worktree: {result.stderr.strip() or result.stdout.strip()}",
            code="qa.worktree_failed",
            http_status=500,
        )
    return str(worktree_path)


_GLOBAL_TRACER = PythonRuntimeTracer()


__all__ = ["QASessionService"]
