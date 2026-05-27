"""QA execution-to-code graph API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.qa.contracts import (
    QACodeGraph,
    QAContextResponse,
    QAGraphResponse,
    QAIndexRequest,
    QARequestRunData,
    QARequestRunRequest,
    QARuntimeEventData,
    QASessionCreateRequest,
    QASessionData,
)
from personagent.application.qa.runtime_tracer import PythonRuntimeTracer, QARuntimeEventBus
from personagent.application.qa.service import QASessionService
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.qa_repository import QARepository

router = APIRouter(prefix="/qa", tags=["qa"])
_EVENT_BUS = QARuntimeEventBus()


async def get_db() -> AsyncIterator[AsyncSession]:
    """Provide a database session for QA routes."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


DB_SESSION_DEPENDENCY = Depends(get_db)


def _service(session: AsyncSession) -> QASessionService:
    return QASessionService(QARepository(session), tracer=None)


@router.post("/sessions", response_model=QASessionData)
async def create_qa_session(
    payload: QASessionCreateRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> QASessionData:
    """Create a QA session bound to a repo/workspace."""
    return await _service(session).create_session(payload)


@router.post("/sessions/{session_id}/index", response_model=QACodeGraph)
async def index_qa_session(
    session_id: UUID,
    request: Request,
    payload: QAIndexRequest | None = None,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> QACodeGraph:
    """Build or refresh the static code graph for a QA session."""
    return await _service(session).index_session(
        session_id,
        payload or QAIndexRequest(),
        app=request.app,
    )


@router.post("/sessions/{session_id}/requests", response_model=QARequestRunData)
async def execute_qa_request(
    session_id: UUID,
    payload: QARequestRunRequest,
    request: Request,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> QARequestRunData:
    """Execute an ASGI request through the active backend under QA tracing."""
    service = QASessionService(QARepository(session), tracer=_qa_tracer())
    return await service.execute_request(session_id, payload, app=request.app)


@router.get("/sessions/{session_id}/graph", response_model=QAGraphResponse)
async def get_qa_graph(
    session_id: UUID,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> QAGraphResponse:
    """Return static graph and runtime overlay for a QA session."""
    return await _service(session).graph_response(session_id)


@router.get("/sessions/{session_id}/events", response_model=list[QARuntimeEventData])
async def list_qa_events(
    session_id: UUID,
    limit: int = Query(default=500, ge=1, le=5_000),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> list[QARuntimeEventData]:
    """Return persisted runtime events for a QA session."""
    events: list[QARuntimeEventData] = await _service(session).list_events(session_id, limit=limit)
    return events


@router.get("/sessions/{session_id}/context", response_model=QAContextResponse)
async def get_qa_context(
    session_id: UUID,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> QAContextResponse:
    """Return compact agent-ready debugging context for a QA session."""
    return await _service(session).context_response(session_id)


@router.get("/sessions/{session_id}/stream")
async def stream_qa_events(session_id: UUID) -> StreamingResponse:
    """Stream runtime events for the given QA session as SSE."""

    async def stream() -> AsyncIterator[str]:
        async with _EVENT_BUS.subscribe(str(session_id)) as queue:
            yield _encode_sse({"event": "qa.stream.open", "session_id": str(session_id)})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _encode_sse({"event": "qa.runtime", "data": event.model_dump(mode="json")})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _qa_tracer() -> PythonRuntimeTracer:
    return PythonRuntimeTracer(event_bus=_EVENT_BUS)


def _encode_sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
