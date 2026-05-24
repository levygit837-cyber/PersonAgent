"""Team chat WebSocket endpoint and persistence helpers.

The WebSocket handler accesses ``get_container`` and ``resolve_model``
through the ``_chat`` module reference so that test monkeypatches are
resolved at call time.
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

# Late-binding module reference.  See module docstring for rationale.
import personagent.interfaces.api.routes.chat as _chat
from personagent.application.team_chat import (
    TeamChatOrchestrator,
    TeamChatRequest,
    TeamValidationError,
    parse_team_config,
    serialize_team_config,
)
from personagent.domain.exceptions import (
    DatabaseError,
    LLMBackendError,
    TeamValidationSystemError,
)
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.models import (
    TeamBlackboardEventORM,
    TeamMemorySnapshotORM,
    TeamRunORM,
)
from personagent.interfaces.api.errors import error_event
from personagent.interfaces.api.routes.chat.helpers import (
    TeamRunStartRequest,
    resolve_provider,
    resolve_reasoning_budget,
    resolve_team_workspace_id,
    resolve_tool_context,
)

logger = structlog.get_logger(__name__)

MAX_TEAM_WS_ERROR_LENGTH = 600


def register_team_chat_routes(router: APIRouter) -> None:
    """Register the Team Mode WebSocket endpoint."""

    @router.websocket("/team/ws")
    async def team_chat_websocket(websocket: WebSocket) -> None:
        """Run Team Mode over a bidirectional WebSocket."""

        await websocket.accept()
        trace_events: list[dict[str, Any]] = []
        status = "running"
        final_output: str | None = None
        final_output_parts: list[str] = []
        consensus: dict[str, Any] | None = None
        blackboard_snapshot: dict[str, Any] | None = None
        team_memory_snapshot: dict[str, Any] | None = None
        error_message: str | None = None
        conversation_id: str | None = None
        run_id: str | None = None
        workspace_id: str | None = None
        team_config_payload: dict[str, Any] | None = None
        stop_event = asyncio.Event()

        try:
            raw_start = await websocket.receive_json()
            start = TeamRunStartRequest.model_validate(raw_start)
            if start.type != "team.run.start":
                raise ValueError("First Team Mode WebSocket message must be team.run.start")

            provider = resolve_provider(start.provider)
            model = _chat.resolve_model(provider, start.model)
            team = parse_team_config(start.team_id, start.team_config)
            team_config_payload = serialize_team_config(team)
            container = _chat.get_container()
            llm_backend = container.get_llm_backend(provider)
            initial_tool_context = resolve_tool_context(start)
            workspace_id = resolve_team_workspace_id(start, initial_tool_context)
            loaded_memory = await _chat.load_team_memory_snapshot(workspace_id)
            if loaded_memory:
                initial_tool_context["team_memory_snapshot"] = loaded_memory
            if workspace_id:
                initial_tool_context["workspace_id"] = workspace_id

            async with AsyncSessionLocal() as session:
                conv_repo = await container.get_conversation_repo(session)
                tool_registry = getattr(container, "get_tool_registry", lambda: None)() if start.tools_enabled else None
                tool_runtime_config = (
                    getattr(container, "get_tool_runtime_config", lambda: None)()
                    if start.tools_enabled
                    else None
                )
                orchestrator = TeamChatOrchestrator(
                    conversation_repo=conv_repo,
                    llm_backend=llm_backend,
                    tool_registry=tool_registry,
                    tool_runtime_config=tool_runtime_config,
                    session_title_service=getattr(container, "get_session_title_service", lambda: None)(),
                )
                request = TeamChatRequest(
                    conversation_id=UUID(start.conversation_id) if start.conversation_id else None,
                    message=start.message,
                    system_prompt=start.system_prompt,
                    provider=provider,
                    model=model,
                    temperature=start.temperature,
                    max_tokens=start.max_tokens,
                    reasoning_level=start.reasoning_level,
                    reasoning_budget_tokens=resolve_reasoning_budget(start),
                    workspace_root=start.workspace_root,
                    tool_context=initial_tool_context,
                    allowed_tools=start.allowed_tools,
                    max_tool_iterations=start.max_tool_iterations,
                )
                stop_task = asyncio.create_task(_watch_team_stop(websocket, stop_event))
                try:
                    async for event in orchestrator.execute(
                        request=request,
                        team=team,
                        cancel_event=stop_event,
                    ):
                        trace_event = _chat._team_trace_event_for_storage(event)
                        if trace_event is not None:
                            trace_events.append(trace_event)
                        if event.get("run_id"):
                            run_id = str(event.get("run_id"))
                        conversation_id = str(event.get("conversation_id") or conversation_id or "")
                        if event.get("event") == "team_run_started" and run_id:
                            await _chat.persist_team_run_started(
                                run_id=run_id,
                                conversation_id=conversation_id,
                                workspace_id=workspace_id,
                                team_config=team_config_payload,
                            )
                        if event.get("event") == "blackboard_event" and run_id:
                            await _chat.persist_team_blackboard_event(
                                run_id=run_id,
                                conversation_id=conversation_id,
                                workspace_id=workspace_id,
                                event=event,
                            )
                        if event.get("event") == "blackboard_snapshot" and isinstance(
                            event.get("snapshot"), dict
                        ):
                            blackboard_snapshot = event.get("snapshot")
                        if event.get("event") == "final_delta":
                            final_output_parts.append(str(event.get("content") or ""))
                        if event.get("event") == "consensus_reached":
                            consensus = (
                                event.get("consensus")
                                if isinstance(event.get("consensus"), dict)
                                else None
                            )
                        if event.get("event") == "team_run_completed":
                            status = "completed"
                            final_output = str(
                                event.get("final_output") or "".join(final_output_parts) or ""
                            )
                            consensus = (
                                event.get("consensus")
                                if isinstance(event.get("consensus"), dict)
                                else consensus
                            )
                            blackboard_snapshot = (
                                event.get("blackboard_snapshot")
                                if isinstance(event.get("blackboard_snapshot"), dict)
                                else blackboard_snapshot
                            )
                            team_memory_snapshot = (
                                event.get("team_memory_snapshot")
                                if isinstance(event.get("team_memory_snapshot"), dict)
                                else team_memory_snapshot
                            )
                        if event.get("event") == "team_consensus_failed":
                            status = "failed"
                            consensus = (
                                event.get("consensus")
                                if isinstance(event.get("consensus"), dict)
                                else consensus
                            )
                            blackboard_snapshot = (
                                event.get("blackboard_snapshot")
                                if isinstance(event.get("blackboard_snapshot"), dict)
                                else blackboard_snapshot
                            )
                            team_memory_snapshot = (
                                event.get("team_memory_snapshot")
                                if isinstance(event.get("team_memory_snapshot"), dict)
                                else team_memory_snapshot
                            )
                        if event.get("event") == "team_run_cancelled":
                            status = "cancelled"
                        await websocket.send_json(event)
                finally:
                    stop_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await stop_task

        except WebSocketDisconnect:
            status = "cancelled"
        except (TeamValidationError, ValueError) as exc:
            status = "failed"
            error = TeamValidationSystemError(str(exc))
            error_message = error.user_message
            event = error_event(error)
            trace_events.append(event)
            await _send_ws_json_safely(websocket, event)
        except LLMBackendError as exc:
            status = "failed"
            error_message = exc.user_message
            event = error_event(exc)
            trace_events.append(event)
            await _send_ws_json_safely(websocket, event)
        except SQLAlchemyError as exc:
            logger.exception("team_chat_websocket_database_error")
            status = "failed"
            error_message = _compact_team_error_message("Team Mode database error", exc)
            event = error_event(DatabaseError(error_message, cause=exc))
            trace_events.append(event)
            await _send_ws_json_safely(websocket, event)
        except Exception as exc:
            logger.exception("team_chat_websocket_unhandled_error")
            status = "failed"
            error_message = _compact_team_error_message("Unexpected Team Mode error", exc)
            event = error_event(exc, default_message=error_message)
            trace_events.append(event)
            await _send_ws_json_safely(websocket, event)
        finally:
            if team_config_payload is not None:
                if final_output is None and final_output_parts:
                    final_output = "".join(final_output_parts)
                await _chat.persist_team_run(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    workspace_id=workspace_id,
                    status=status,
                    team_config=team_config_payload,
                    trace_events=trace_events,
                    blackboard_snapshot=blackboard_snapshot,
                    team_memory_snapshot=team_memory_snapshot,
                    final_output=final_output,
                    consensus=consensus,
                    error_message=error_message,
                )
                if workspace_id and team_memory_snapshot is not None:
                    await _chat.persist_team_memory_snapshot(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        snapshot=team_memory_snapshot,
                    )
            await _close_ws_safely(websocket)


async def _watch_team_stop(websocket: WebSocket, stop_event) -> None:
    while not stop_event.is_set():
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            stop_event.set()
            return
        except RuntimeError:
            stop_event.set()
            return
        if isinstance(message, dict) and message.get("type") == "team.run.stop":
            stop_event.set()
            return


async def _send_ws_json_safely(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except RuntimeError:
        return


def _compact_team_error_message(prefix: str, exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if "team_runs.run_id" in text and "UndefinedColumnError" in text:
        return (
            f"{prefix}: local database schema is missing Team Mode columns. "
            "Restart the backend or run database initialization to apply the Team Mode schema."
        )
    if len(text) > MAX_TEAM_WS_ERROR_LENGTH:
        text = f"{text[:MAX_TEAM_WS_ERROR_LENGTH].rstrip()}..."
    return f"{prefix}: {text}"


async def _close_ws_safely(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except RuntimeError:
        return


async def persist_team_run_started(
    *,
    run_id: str,
    conversation_id: str | None,
    team_config: dict[str, Any] | None,
    workspace_id: str | None = None,
) -> None:
    """Create the Team Mode run row while the WebSocket is still active."""

    try:
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(select(TeamRunORM).where(TeamRunORM.run_id == run_id))
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                TeamRunORM(
                    run_id=run_id,
                    conversation_id=UUID(conversation_id) if conversation_id else None,
                    workspace_id=workspace_id,
                    status="running",
                    team_config=team_config or {},
                    trace_events=[],
                )
            )
            await session.commit()
    except Exception:
        logger.exception("team_run_started_persist_failed", run_id=run_id)


async def persist_team_blackboard_event(
    *,
    run_id: str,
    conversation_id: str | None,
    event: dict[str, Any],
    workspace_id: str | None = None,
) -> None:
    """Persist one Blackboard journal event as soon as it is emitted."""

    try:
        async with AsyncSessionLocal() as session:
            session.add(
                TeamBlackboardEventORM(
                    run_id=run_id,
                    conversation_id=UUID(conversation_id) if conversation_id else None,
                    workspace_id=workspace_id,
                    sequence=int(event.get("sequence") or 0),
                    phase=str(event.get("phase") or ""),
                    round=event.get("round") if isinstance(event.get("round"), int) else None,
                    agent_id=str(event.get("agent_id") or "") or None,
                    event_type=str(event.get("event_type") or "blackboard_event"),
                    payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
                )
            )
            await session.commit()
    except Exception:
        logger.exception("team_blackboard_event_persist_failed", run_id=run_id)


async def load_team_memory_snapshot(workspace_id: str | None) -> dict[str, Any] | None:
    """Load the compact Team memory snapshot for a workspace."""

    if not workspace_id:
        return None
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(TeamMemorySnapshotORM).where(
                        TeamMemorySnapshotORM.workspace_id == workspace_id
                    )
                )
            ).scalar_one_or_none()
            snapshot = row.snapshot if row is not None else None
            return snapshot if isinstance(snapshot, dict) else None
    except Exception:
        logger.exception("team_memory_snapshot_load_failed", workspace_id=workspace_id)
        return None


async def persist_team_memory_snapshot(
    *,
    workspace_id: str,
    run_id: str | None,
    snapshot: dict[str, Any],
) -> None:
    """Upsert the compact Team memory snapshot for a workspace."""

    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(TeamMemorySnapshotORM).where(
                        TeamMemorySnapshotORM.workspace_id == workspace_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = TeamMemorySnapshotORM(workspace_id=workspace_id)
                session.add(row)
            row.snapshot = snapshot
            row.last_run_id = run_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        logger.exception("team_memory_snapshot_persist_failed", workspace_id=workspace_id)


async def persist_team_run(
    *,
    run_id: str | None,
    conversation_id: str | None,
    status: str,
    team_config: dict[str, Any],
    trace_events: list[dict[str, Any]],
    blackboard_snapshot: dict[str, Any] | None,
    final_output: str | None,
    consensus: dict[str, Any] | None,
    error_message: str | None,
    workspace_id: str | None = None,
    team_memory_snapshot: dict[str, Any] | None = None,
) -> None:
    """Persist a Team Mode run after the WebSocket closes."""

    try:
        compact_trace_events = [
            compact_event
            for event in trace_events
            if (compact_event := _chat._team_trace_event_for_storage(event)) is not None
        ]
        async with AsyncSessionLocal() as session:
            run = None
            if run_id:
                run = (
                    await session.execute(select(TeamRunORM).where(TeamRunORM.run_id == run_id))
                ).scalar_one_or_none()
            if run is None:
                run = TeamRunORM(run_id=run_id)
                session.add(run)
            run.conversation_id = UUID(conversation_id) if conversation_id else None
            run.workspace_id = workspace_id
            run.status = status
            run.team_config = team_config
            run.trace_events = compact_trace_events
            run.blackboard_snapshot = blackboard_snapshot or team_memory_snapshot
            run.final_output = final_output
            run.consensus = consensus
            run.error_message = error_message
            run.finished_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        logger.exception("team_run_persist_failed", conversation_id=conversation_id)


def _team_trace_event_for_storage(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep Team Mode history useful without persisting token-by-token payloads."""

    if event.get("event") in {"agent_delta", "final_delta"}:
        return None

    compact = dict(event)
    if compact.get("event") == "blackboard_snapshot":
        snapshot = compact.pop("snapshot", None)
        if isinstance(snapshot, dict):
            compact["snapshot_entry_count"] = snapshot.get("entry_count", 0)
            compact["snapshot_latest_sequence"] = snapshot.get("latest_sequence", 0)
    for field in ("content", "reasoning_content", "final_output"):
        value = compact.pop(field, None)
        if isinstance(value, str) and value:
            compact[f"{field}_length"] = len(value)
        elif value not in (None, ""):
            compact[f"{field}_present"] = True
    return compact
