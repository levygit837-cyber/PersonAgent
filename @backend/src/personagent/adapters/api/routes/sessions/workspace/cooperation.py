"""Browser Cooperation routes — mode control, event ingestion, real-time WS."""

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

import personagent.adapters.api.routes.sessions as _sessions
from personagent.adapters.api.routes.sessions.panel.models import (
    SessionBrowserCooperationRequest,
    SessionBrowserEventBatchRequest,
)
from personagent.adapters.api.routes.sessions.workspace.infra import (
    _browser_cooperation_service,
)
from personagent.application.services.browser_cooperation import (
    BROWSER_COOPERATION_MODES,
)


def register_cooperation_routes(router) -> None:
    """Register Browser Cooperation endpoints on the sessions router."""

    @router.post("/{conversation_id}/browser/{browser_id}/cooperation")
    async def set_conversation_browser_cooperation(
        conversation_id: str,
        browser_id: str,
        request: SessionBrowserCooperationRequest,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Enable/disable Browser Cooperation and set the action-control mode."""

        if request.mode not in BROWSER_COOPERATION_MODES:
            raise HTTPException(status_code=400, detail="Invalid browser cooperation mode.")
        conversation = await _sessions._load_conversation(conversation_id, session)
        service = _browser_cooperation_service(session)
        if service is None:
            raise HTTPException(status_code=409, detail="Browser cooperation persistence is unavailable.")
        result = await service.set_cooperation(
            conversation,
            browser_id=browser_id,
            enabled=request.enabled,
            mode=request.mode,
        )
        await _sessions._save_conversation(conversation, session)
        return result

    @router.post("/{conversation_id}/browser/{browser_id}/events")
    async def ingest_conversation_browser_events(
        conversation_id: str,
        browser_id: str,
        request: SessionBrowserEventBatchRequest,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Ingest normalized/redacted Browser -> Agent cooperation events."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        service = _browser_cooperation_service(session)
        if service is None:
            raise HTTPException(status_code=409, detail="Browser cooperation persistence is unavailable.")
        result = await service.ingest_events(
            conversation,
            browser_id=browser_id,
            events=[event.model_dump(exclude_none=True) for event in request.events],
        )
        await _sessions._save_conversation(conversation, session)
        return result

    @router.websocket("/{conversation_id}/browser/{browser_id}/cooperation/ws")
    async def session_browser_cooperation_ws(
        websocket: WebSocket,
        conversation_id: str,
        browser_id: str,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> None:
        """Realtime Browser Cooperation transport for UI/debug state only."""

        await websocket.accept()
        try:
            conversation = await _sessions._load_conversation(conversation_id, session)
            service = _browser_cooperation_service(session)
            if service is None:
                await _send_ws_json_safely(websocket, {"type": "error", "error": "Browser cooperation persistence is unavailable."})
                await websocket.close(code=1011)
                return
            await _send_ws_json_safely(
                websocket,
                await service.get_snapshot(conversation, browser_id=browser_id),
            )
            while True:
                message = await websocket.receive_json()
                message_type = str(message.get("type") or "")
                if message_type == "ping":
                    await _send_ws_json_safely(websocket, {"type": "pong", "timestamp": datetime.now(UTC).isoformat()})
                    await _send_ws_json_safely(
                        websocket,
                        await service.get_snapshot(conversation, browser_id=browser_id),
                    )
                    continue
                if message_type == "event_batch":
                    events = message.get("events")
                    if not isinstance(events, list):
                        await _send_ws_json_safely(websocket, {"type": "error", "error": "event_batch requires an events list."})
                        continue
                    result = await service.ingest_events(
                        conversation,
                        browser_id=browser_id,
                        events=[event for event in events if isinstance(event, dict)],
                    )
                    await _sessions._save_conversation(conversation, session)
                    await _send_ws_json_safely(websocket, {"type": "event_batch.accepted", **result})
                    cooperation = result.get("state_patch", {}).get("cooperation") if isinstance(result.get("state_patch"), dict) else None
                    if cooperation:
                        await _send_ws_json_safely(
                            websocket,
                            {
                                "type": "timeline.patch",
                                "state_patch": result.get("state_patch"),
                                "useful_timeline": cooperation.get("useful_timeline", []),
                                "recent_user_events": cooperation.get("recent_user_events", []),
                                "recent_agent_events": cooperation.get("recent_agent_events", []),
                            },
                        )
                    continue
                if message_type == "mode.set":
                    mode = str(message.get("mode") or "observe_only")
                    if mode not in BROWSER_COOPERATION_MODES:
                        await _send_ws_json_safely(websocket, {"type": "error", "error": "Invalid browser cooperation mode."})
                        continue
                    result = await service.set_cooperation(
                        conversation,
                        browser_id=browser_id,
                        enabled=bool(message.get("enabled", True)),
                        mode=mode,
                    )
                    await _sessions._save_conversation(conversation, session)
                    await _send_ws_json_safely(websocket, {"type": "mode.changed", **result})
                    continue
                if message_type in {"proposal.approve", "proposal.deny", "proposal.dismiss"}:
                    proposal_id = str(message.get("proposal_id") or message.get("proposalId") or "")
                    if not proposal_id:
                        await _send_ws_json_safely(websocket, {"type": "error", "error": "proposal_id is required."})
                        continue
                    status = {
                        "proposal.approve": "approved",
                        "proposal.deny": "denied",
                        "proposal.dismiss": "dismissed",
                    }[message_type]
                    result = await service.resolve_proposal(
                        conversation,
                        browser_id=browser_id,
                        proposal_id=proposal_id,
                        status=status,
                    )
                    await _sessions._save_conversation(conversation, session)
                    await _send_ws_json_safely(websocket, result)
                    continue
                await _send_ws_json_safely(websocket, {"type": "error", "error": f"Unsupported cooperation WS message: {message_type}"})
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await _send_ws_json_safely(websocket, {"type": "error", "error": str(exc)})
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                return


async def _send_ws_json_safely(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except RuntimeError:
        return False
