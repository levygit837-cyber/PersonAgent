"""Session panel routes."""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.browser_cooperation import (
    BROWSER_COOPERATION_MODES,
    BrowserCooperationService,
)
from personagent.application.services.browser_workspace import BrowserWorkspaceService
from personagent.application.services.session_panel import SessionPanelService
from personagent.infrastructure.browser.lightpanda import BrowserError, BrowserUnavailableError
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.api.routes.sessions.models import (
    SessionBrowserActionRequest,
    SessionBrowserAnnotationRequest,
    SessionBrowserCooperationRequest,
    SessionBrowserEventBatchRequest,
    SessionBrowserHistoryRequest,
    SessionBrowserKeyboardRequest,
    SessionBrowserNavigateRequest,
    SessionBrowserPointerRequest,
    SessionBrowserScrollRequest,
    SessionBrowserViewport,
    SessionTitleVerifyRequest,
)
from personagent.interfaces.api.workspace_grants import resolve_workspace_root
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)


@router.get("/browser/{browser_id}/view")
async def get_session_browser_view(
    browser_id: str,
    width: int = Query(default=1024, ge=320, le=2400),
    height: int = Query(default=720, ge=240, le=1800),
    cache_mode: str = Query(default="prefer_live", pattern="^(prefer_live|prefer_cached)$"),
    wait_for_styles: bool = Query(default=True),
) -> dict[str, Any]:
    """Return the current LightPanda-rendered browser viewport."""

    try:
        return await _browser_worker().view_snapshot(
            browser_id=browser_id,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{conversation_id}/browser/{browser_id}/cooperation")
async def set_conversation_browser_cooperation(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserCooperationRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Enable/disable Browser Cooperation and set the action-control mode."""

    if request.mode not in BROWSER_COOPERATION_MODES:
        raise HTTPException(status_code=400, detail="Invalid browser cooperation mode.")
    conversation = await _load_conversation(conversation_id, session)
    service = _browser_cooperation_service(session)
    if service is None:
        raise HTTPException(status_code=409, detail="Browser cooperation persistence is unavailable.")
    result = await service.set_cooperation(
        conversation,
        browser_id=browser_id,
        enabled=request.enabled,
        mode=request.mode,
    )
    await _save_conversation(conversation, session)
    return result


@router.post("/{conversation_id}/browser/{browser_id}/events")
async def ingest_conversation_browser_events(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserEventBatchRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Ingest normalized/redacted Browser -> Agent cooperation events."""

    conversation = await _load_conversation(conversation_id, session)
    service = _browser_cooperation_service(session)
    if service is None:
        raise HTTPException(status_code=409, detail="Browser cooperation persistence is unavailable.")
    result = await service.ingest_events(
        conversation,
        browser_id=browser_id,
        events=[event.model_dump(exclude_none=True) for event in request.events],
    )
    await _save_conversation(conversation, session)
    return result


@router.websocket("/{conversation_id}/browser/{browser_id}/cooperation/ws")
async def session_browser_cooperation_ws(
    websocket: WebSocket,
    conversation_id: str,
    browser_id: str,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> None:
    """Realtime Browser Cooperation transport for UI/debug state only."""

    await websocket.accept()
    try:
        conversation = await _load_conversation(conversation_id, session)
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
                await _save_conversation(conversation, session)
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
                await _save_conversation(conversation, session)
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
                await _save_conversation(conversation, session)
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


@router.post("/browser/{browser_id}/navigate")
async def navigate_session_browser(
    browser_id: str,
    request: SessionBrowserNavigateRequest,
) -> dict[str, Any]:
    """Navigate a LightPanda-backed browser viewport."""

    try:
        return await _browser_worker().view_navigate(
            browser_id=browser_id,
            url=request.url,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/history")
async def move_session_browser_history(
    browser_id: str,
    request: SessionBrowserHistoryRequest,
) -> dict[str, Any]:
    """Move a LightPanda-backed browser viewport through real page history."""

    if request.direction == 0:
        raise HTTPException(status_code=400, detail="Browser history direction must be -1 or 1.")
    try:
        return await _browser_worker().view_history(
            browser_id=browser_id,
            direction=request.direction,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/reload")
async def reload_session_browser(
    browser_id: str,
    request: SessionBrowserViewport,
) -> dict[str, Any]:
    """Reload the current LightPanda-backed browser viewport."""

    try:
        return await _browser_worker().view_reload(
            browser_id=browser_id,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/click")
async def click_session_browser(
    browser_id: str,
    request: SessionBrowserPointerRequest,
) -> dict[str, Any]:
    """Click inside the current LightPanda-rendered browser viewport."""

    try:
        return await _browser_worker().view_click(
            browser_id=browser_id,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            button=request.button,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/key")
async def key_session_browser(
    browser_id: str,
    request: SessionBrowserKeyboardRequest,
) -> dict[str, Any]:
    """Send keyboard input to the current LightPanda-backed browser viewport."""

    if not request.text and not request.key:
        raise HTTPException(status_code=400, detail="Browser keyboard input requires text or key.")
    try:
        return await _browser_worker().view_key(
            browser_id=browser_id,
            width=request.width,
            height=request.height,
            text=request.text,
            key=request.key,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/scroll")
async def scroll_session_browser(
    browser_id: str,
    request: SessionBrowserScrollRequest,
) -> dict[str, Any]:
    """Scroll the current LightPanda-backed browser viewport."""

    try:
        return await _browser_worker().view_scroll(
            browser_id=browser_id,
            delta_x=request.delta_x,
            delta_y=request.delta_y,
            width=request.width,
            height=request.height,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/browser/{browser_id}/action")
async def act_session_browser(
    browser_id: str,
    request: SessionBrowserActionRequest,
) -> dict[str, Any]:
    """Execute a mapped DOM action in a runtime-only session-panel browser."""

    try:
        return await _browser_worker().view_act(
            browser_id=browser_id,
            node_id=request.node_id,
            action=request.action,
            value=request.value,
            key=request.key,
            target_node_id=request.target_node_id,
            timeout_ms=request.timeout_ms,
            files=request.files,
            text=request.text,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{conversation_id}/browser/{browser_id}/view")
async def get_conversation_browser_view(
    conversation_id: str,
    browser_id: str,
    width: int = Query(default=1024, ge=320, le=2400),
    height: int = Query(default=720, ge=240, le=1800),
    cache_mode: str = Query(default="prefer_live", pattern="^(prefer_live|prefer_cached)$"),
    wait_for_styles: bool = Query(default=True),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return a Browser Workspace view enriched with conversation annotations/timeline."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_snapshot(
            browser_id=browser_id,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/navigate")
async def navigate_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserNavigateRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Navigate a conversation Browser Workspace and return the enriched snapshot."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_navigate(
            browser_id=browser_id,
            url=request.url,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="navigate",
        source="user",
        label=f"Navigated to {view.get('url') or request.url}",
        payload={"url": view.get("url") or request.url, "title": view.get("title") or ""},
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="navigation",
        source="user",
        label=f"navigated to {view.get('url') or request.url}",
        payload={"url": view.get("url") or request.url, "title": view.get("title") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/history")
async def move_conversation_browser_history(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserHistoryRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Move conversation Browser Workspace history."""

    if request.direction == 0:
        raise HTTPException(status_code=400, detail="Browser history direction must be -1 or 1.")
    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_history(
            browser_id=browser_id,
            direction=request.direction,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="history",
        source="user",
        label="Moved browser history",
        payload={"direction": request.direction, "url": view.get("url") or ""},
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="history",
        source="user",
        label="moved browser history",
        payload={"direction": request.direction, "url": view.get("url") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/reload")
async def reload_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserViewport,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Reload conversation Browser Workspace."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_reload(
            browser_id=browser_id,
            width=request.width,
            height=request.height,
            cache_mode=request.cache_mode,
            wait_for_styles=request.wait_for_styles,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="reload",
        source="user",
        label="Reloaded page",
        payload={"url": view.get("url") or ""},
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="reload",
        source="user",
        label="reloaded page",
        payload={"url": view.get("url") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/click")
async def click_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserPointerRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Click conversation Browser Workspace by viewport coordinates."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_click(
            browser_id=browser_id,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            button=request.button,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="click",
        source="user",
        label="Clicked viewport",
        payload={"x": request.x, "y": request.y, "url": view.get("url") or ""},
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="click",
        source="user",
        label="clicked viewport",
        payload={"x": request.x, "y": request.y, "url": view.get("url") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/key")
async def key_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserKeyboardRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Send keyboard input to conversation Browser Workspace."""

    if not request.text and not request.key:
        raise HTTPException(status_code=400, detail="Browser keyboard input requires text or key.")
    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_key(
            browser_id=browser_id,
            width=request.width,
            height=request.height,
            text=request.text,
            key=request.key,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="key",
        source="user",
        label="Sent keyboard input",
        payload={
            "key": request.key or "",
            "text_char_count": len(request.text or ""),
            "url": view.get("url") or "",
        },
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="keydown",
        source="user",
        label="sent keyboard input",
        payload={"key": request.key or "", "text": request.text or "", "url": view.get("url") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/scroll")
async def scroll_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserScrollRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Scroll conversation Browser Workspace."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_scroll(
            browser_id=browser_id,
            delta_x=request.delta_x,
            delta_y=request.delta_y,
            width=request.width,
            height=request.height,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="scroll",
        source="user",
        label="Scrolled page",
        payload={"delta_x": request.delta_x, "delta_y": request.delta_y, "url": view.get("url") or ""},
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="scroll",
        source="user",
        label="scrolled page",
        payload={"delta_x": request.delta_x, "delta_y": request.delta_y, "url": view.get("url") or ""},
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/action")
async def act_conversation_browser(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserActionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Execute a mapped DOM action in the Browser Workspace."""

    conversation = await _load_conversation(conversation_id, session)
    try:
        view = await _browser_worker().view_act(
            browser_id=browser_id,
            node_id=request.node_id,
            action=request.action,
            value=request.value,
            key=request.key,
            target_node_id=request.target_node_id,
            timeout_ms=request.timeout_ms,
            files=request.files,
            text=request.text,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
        )
    except BrowserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="action",
        source=_safe_event_source(request.source),
        label=f"{request.action.title()} {request.node_id}",
        payload={
            "node_id": request.node_id,
            "action": request.action,
            "url": view.get("url") or "",
            "title": view.get("title") or "",
        },
    )
    await _record_canonical_browser_event(
        session,
        conversation,
        browser_id=browser_id,
        kind="action",
        source=_safe_event_source(request.source),
        label=f"{request.action} {request.node_id}",
        payload={
            "node_id": request.node_id,
            "action": request.action,
            "url": view.get("url") or "",
            "title": view.get("title") or "",
        },
    )
    return await _persist_browser_workspace_view(conversation, session, browser_id, view)


@router.post("/{conversation_id}/browser/{browser_id}/annotations")
async def create_conversation_browser_annotation(
    conversation_id: str,
    browser_id: str,
    request: SessionBrowserAnnotationRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Persist an annotation linked to a Browser Workspace element."""

    conversation = await _load_conversation(conversation_id, session)
    service = _browser_workspace_service(session)
    if service is not None:
        return await service.create_annotation(
            conversation,
            browser_id=browser_id,
            node_id=request.node_id,
            body=request.body,
            quote=request.quote,
            url=request.url,
            title=request.title,
            selector=request.selector,
            frame_id=request.frame_id,
            selector_chain=request.selector_chain,
            shadow_path=request.shadow_path,
            tab_id=request.tab_id,
        )
    workspace = _browser_workspace(conversation)
    annotation = {
        "id": f"ann_{uuid4().hex[:12]}",
        "browser_id": browser_id,
        "tab_id": request.tab_id or browser_id,
        "node_id": request.node_id,
        "body": request.body.strip(),
        "quote": (request.quote or "").strip(),
        "url": (request.url or "").strip(),
        "title": (request.title or "").strip(),
        "selector": (request.selector or "").strip(),
        "frame_id": (request.frame_id or "main").strip(),
        "selector_chain": request.selector_chain or [],
        "shadow_path": request.shadow_path or [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    annotations = _coerce_list(workspace.get("annotations"))
    annotations.append(annotation)
    workspace["annotations"] = annotations[-100:]
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="annotation",
        source="user",
        label="Added annotation",
        payload={"node_id": request.node_id, "annotation_id": annotation["id"]},
    )
    await _save_conversation(conversation, session)
    return {"annotation": annotation, **_workspace_payload(conversation, browser_id)}


@router.delete("/{conversation_id}/browser/{browser_id}/annotations/{annotation_id}")
async def delete_conversation_browser_annotation(
    conversation_id: str,
    browser_id: str,
    annotation_id: str,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Delete a persisted Browser Workspace annotation."""

    conversation = await _load_conversation(conversation_id, session)
    service = _browser_workspace_service(session)
    if service is not None:
        return await service.delete_annotation(
            conversation,
            browser_id=browser_id,
            annotation_id=annotation_id,
        )
    workspace = _browser_workspace(conversation)
    annotations = [
        item
        for item in _coerce_list(workspace.get("annotations"))
        if str(item.get("id") or "") != annotation_id
    ]
    workspace["annotations"] = annotations
    await _record_timeline_event(
        session,
        conversation,
        browser_id=browser_id,
        event_type="annotation_deleted",
        source="user",
        label="Deleted annotation",
        payload={"annotation_id": annotation_id},
    )
    await _save_conversation(conversation, session)
    return _workspace_payload(conversation, browser_id)


@router.delete("/{conversation_id}/browser/{browser_id}/timeline")
async def clear_conversation_browser_timeline(
    conversation_id: str,
    browser_id: str,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Clear Browser Workspace timeline events for the current conversation."""

    conversation = await _load_conversation(conversation_id, session)
    service = _browser_workspace_service(session)
    if service is not None:
        return await service.clear_timeline(conversation, browser_id=browser_id)
    workspace = _browser_workspace(conversation)
    workspace["timeline_events"] = [
        item
        for item in _coerce_list(workspace.get("timeline_events"))
        if str(item.get("browser_id") or "") != browser_id
    ]
    await _save_conversation(conversation, session)
    return _workspace_payload(conversation, browser_id)


@router.get("/{conversation_id}/browser/mentions")
async def list_conversation_browser_mentions(
    conversation_id: str,
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> list[dict[str, Any]]:
    """Return Browser tab mention suggestions for the shared conversation browser."""

    conversation = await _load_conversation(conversation_id, session)
    metadata_workspace = _browser_workspace(conversation)
    browser_id = str(metadata_workspace.get("active_browser_id") or conversation_id)
    service = _browser_workspace_service(session)
    if service is not None:
        payload = await service.payload(conversation, browser_id)
    else:
        payload = _workspace_payload(conversation, browser_id)
    return _browser_tab_mention_suggestions(
        payload,
        browser_id=browser_id,
        query=q,
        limit=limit,
    )


@router.post("/titles/verify")
async def verify_session_titles(
    request: SessionTitleVerifyRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Run cached LLM title verification across persisted sessions."""

    container = get_container()
    service = getattr(container, "get_session_title_service", lambda: None)()
    if service is None:
        raise HTTPException(status_code=409, detail="Session title verification is disabled.")
    repo = await container.get_conversation_repo(session)
    result = await service.verify_all(
        repo,
        limit=request.limit,
        offset=request.offset,
        batch_size=request.batch_size,
        force=request.force,
        dry_run=request.dry_run,
    )
    return result.to_dict()


@router.post("/titles/dedupe")
async def dedupe_session_titles(
    force: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Repair duplicate or near-duplicate persisted session titles."""

    container = get_container()
    service = getattr(container, "get_session_title_service", lambda: None)()
    if service is None:
        raise HTTPException(status_code=409, detail="Session title verification is disabled.")
    repo = await container.get_conversation_repo(session)
    result = await service.maybe_repair_duplicate_titles(repo, force=force, dry_run=dry_run)
    return result.to_dict()


@router.get("/{conversation_id}/panel")
async def get_session_panel(
    conversation_id: str,
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return the aggregated session panel snapshot for one conversation."""

    conversation = await _load_conversation(conversation_id, session)
    return await SessionPanelService(
        _resolve_optional_workspace(workspace_root, workspace_id)
    ).panel_snapshot(conversation)


@router.get("/{conversation_id}/project/details")
async def get_session_project_detail(
    conversation_id: str,
    type: str = Query(..., description="Detail type: commit, push, pr or branch."),
    id: str = Query(..., description="Project item identifier."),
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return detail content for a project item in the floating panel window."""

    await _load_conversation(conversation_id, session)
    return SessionPanelService(_resolve_optional_workspace(workspace_root, workspace_id)).project_detail(type, id)


def _resolve_optional_workspace(workspace_root: str | None, workspace_id: str | None) -> str | None:
    if not workspace_root and not workspace_id:
        return None
    try:
        return str(resolve_workspace_root(workspace_id=workspace_id, workspace_root=workspace_root))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _load_conversation(conversation_id: str, session: AsyncSession):
    container = get_container()
    repo = await container.get_conversation_repo(session)
    try:
        parsed = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
    conversation = await repo.get_by_id(parsed)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


async def _save_conversation(conversation, session: AsyncSession):
    container = get_container()
    repo = await container.get_conversation_repo(session)
    return await repo.update(conversation)


async def _send_ws_json_safely(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except RuntimeError:
        return False


async def _persist_browser_workspace_view(
    conversation,
    session: AsyncSession,
    browser_id: str,
    view: dict[str, Any],
) -> dict[str, Any]:
    service = _browser_workspace_service(session)
    if service is not None:
        persisted = await service.persist_view(conversation, browser_id=browser_id, view=view)
        await _ingest_view_cooperation_events(session, conversation, browser_id=browser_id, view=persisted)
        await _save_conversation(conversation, session)
        return persisted
    workspace = _browser_workspace(conversation)
    workspace["active_browser_id"] = browser_id
    workspace["active_tab_id"] = view.get("active_tab_id") or browser_id
    if view.get("url") and view.get("url") != "about:blank":
        workspace["current_url"] = view.get("url")
        workspace["current_title"] = view.get("title") or ""
    workspace["last_element_map"] = _compact_element_map(view.get("element_map"))
    tabs = _coerce_list(view.get("tabs"))[:50]
    if not tabs:
        active_tab_id = str(workspace.get("active_tab_id") or browser_id)
        current_url = str(view.get("url") or workspace.get("current_url") or "")
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": current_url,
                "title": str(view.get("title") or workspace.get("current_title") or ""),
                "runtime": str(view.get("runtime") or "lightpanda"),
                "active": True,
                "is_active": True,
                "history": [current_url] if current_url and current_url != "about:blank" else [],
            }
        ]
    workspace["tabs"] = tabs
    view.update(_workspace_payload(conversation, browser_id))
    snapshot = view.get("browser_snapshot")
    if isinstance(snapshot, dict):
        snapshot["annotations"] = view["annotations"]
        snapshot["timeline_events"] = view["timeline_events"]
        snapshot["element_map"] = view.get("element_map") or []
        snapshot["cooperation"] = view.get("cooperation") or {}
    await _ingest_view_cooperation_events(session, conversation, browser_id=browser_id, view=view)
    await _save_conversation(conversation, session)
    return view


async def _ingest_view_cooperation_events(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    view: dict[str, Any],
) -> None:
    events = _coerce_list(view.get("cooperation_events"))
    if not events:
        snapshot = _coerce_dict(view.get("browser_snapshot"))
        events = _coerce_list(snapshot.get("cooperation_events"))
    if not events:
        return
    service = _browser_cooperation_service(session)
    if service is None:
        return
    result = await service.ingest_events(
        conversation,
        browser_id=browser_id,
        events=[event for event in events if isinstance(event, dict)],
    )
    cooperation = _coerce_dict(_coerce_dict(result.get("state_patch")).get("cooperation"))
    if cooperation:
        view["cooperation"] = cooperation
        if isinstance(view.get("workspace_state"), dict):
            view["workspace_state"]["cooperation"] = cooperation
        if isinstance(view.get("browser_snapshot"), dict):
            view["browser_snapshot"]["cooperation"] = cooperation


def _browser_workspace_service(session: AsyncSession) -> BrowserWorkspaceService | None:
    if isinstance(session, AsyncSession):
        return BrowserWorkspaceService(session)
    return None


def _browser_cooperation_service(session: AsyncSession) -> BrowserCooperationService | None:
    if isinstance(session, AsyncSession):
        return BrowserCooperationService(session)
    return None


async def _record_timeline_event(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    event_type: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = _browser_workspace_service(session)
    if service is not None:
        return await service.append_timeline_event(
            conversation,
            browser_id=browser_id,
            event_type=event_type,
            source=source,
            label=label,
            payload=payload,
        )
    return _append_timeline_event(
        conversation,
        browser_id=browser_id,
        event_type=event_type,
        source=source,
        label=label,
        payload=payload,
    )


async def _record_canonical_browser_event(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    kind: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
    tab_id: str | None = None,
    page_id: str | None = None,
    url: str | None = None,
) -> None:
    service = _browser_cooperation_service(session)
    if service is None:
        return
    result = await service.record_canonical_event(
        conversation,
        browser_id=browser_id,
        kind=kind,
        source=source,
        label=label,
        payload=payload,
        tab_id=tab_id,
        page_id=page_id,
        url=url,
    )
    if result is not None:
        await _save_conversation(conversation, session)


def _browser_workspace(conversation) -> dict[str, Any]:
    metadata = conversation.metadata
    workspace = metadata.get("browser_workspace")
    if not isinstance(workspace, dict):
        workspace = {}
        metadata["browser_workspace"] = workspace
    workspace.setdefault("annotations", [])
    workspace.setdefault("timeline_events", [])
    workspace.setdefault("last_element_map", [])
    return workspace


def _workspace_payload(conversation, browser_id: str) -> dict[str, Any]:
    workspace = _browser_workspace(conversation)
    annotations = [
        item
        for item in _coerce_list(workspace.get("annotations"))
        if str(item.get("browser_id") or "") == browser_id
    ]
    timeline_events = [
        item
        for item in _coerce_list(workspace.get("timeline_events"))
        if str(item.get("browser_id") or "") == browser_id
    ]
    return {
        "annotations": annotations[-100:],
        "timeline_events": timeline_events[-120:],
        "cooperation": _coerce_dict(
            _coerce_dict(conversation.metadata.get("browser_cooperation")).get(browser_id)
        ),
        "tabs": _coerce_list(workspace.get("tabs")),
        "active_tab_id": str(workspace.get("active_tab_id") or browser_id),
        "workspace_state": {
            "active_browser_id": str(workspace.get("active_browser_id") or ""),
            "active_tab_id": str(workspace.get("active_tab_id") or browser_id),
            "current_url": str(workspace.get("current_url") or ""),
            "current_title": str(workspace.get("current_title") or ""),
            "last_element_map": _coerce_list(workspace.get("last_element_map"))[:220],
            "cooperation": _coerce_dict(
                _coerce_dict(conversation.metadata.get("browser_cooperation")).get(browser_id)
            ),
        },
    }


def _browser_tab_mention_suggestions(
    payload: dict[str, Any],
    *,
    browser_id: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    workspace_state = _coerce_dict(payload.get("workspace_state"))
    tabs = _coerce_list(payload.get("tabs"))
    active_tab_id = str(payload.get("active_tab_id") or workspace_state.get("active_tab_id") or browser_id)
    if not tabs and str(workspace_state.get("current_url") or ""):
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": str(workspace_state.get("current_url") or ""),
                "title": str(workspace_state.get("current_title") or ""),
                "runtime": str(workspace_state.get("runtime") or "lightpanda"),
                "active": True,
                "is_active": True,
                "state": {},
            }
        ]
    normalized_query = _normalize_browser_mention_query(query)
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tab in enumerate(tabs[:50]):
        tab_id = str(tab.get("tab_id") or tab.get("id") or active_tab_id or browser_id)
        url = str(tab.get("url") or tab.get("final_url") or "")
        title = str(tab.get("title") or "")
        domain = _domain_from_url(url)
        haystack = " ".join([domain, url, title, tab_id]).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        if tab_id in seen:
            continue
        seen.add(tab_id)
        active = bool(tab.get("active") or tab.get("is_active") or tab_id == active_tab_id)
        score = _browser_mention_score(normalized_query, domain, url, title, active, index)
        label_domain = domain or "tab"
        suggestions.append(
            {
                "type": "browser_tab",
                "id": f"browser_tab:{browser_id}:{tab_id}",
                "label": f"@Browser:{label_domain}",
                "token": f"@Browser:{label_domain}",
                "browser_id": browser_id,
                "tab_id": tab_id,
                "page_id": tab_id,
                "window_id": tab_id,
                "url": url,
                "title": title,
                "runtime": str(tab.get("runtime") or workspace_state.get("runtime") or ""),
                "active": active,
                "is_active": active,
                "display_path": title or url or tab_id,
                "domain": domain,
                "state": _coerce_dict(tab.get("state")),
                "updated_at": str(tab.get("updated_at") or ""),
                "score": score,
            }
        )
    return sorted(suggestions, key=lambda item: (float(item.get("score") or 99), str(item.get("display_path") or "")))[:limit]


def _normalize_browser_mention_query(query: str) -> str:
    normalized = str(query or "").strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if normalized.startswith("browser:"):
        normalized = normalized[len("browser:") :]
    elif normalized == "browser":
        normalized = ""
    return normalized.strip()


def _browser_mention_score(
    query: str,
    domain: str,
    url: str,
    title: str,
    active: bool,
    index: int,
) -> float:
    score = 0.0 if active else 1.0
    if not query:
        return score + index * 0.01
    if domain.lower() == query:
        return score
    if domain.lower().startswith(query):
        return score + 0.1
    if query in domain.lower():
        return score + 0.2
    if title.lower().startswith(query):
        return score + 0.4
    if query in title.lower():
        return score + 0.6
    if query in url.lower():
        return score + 0.8
    return score + 2.0


def _domain_from_url(url: str) -> str:
    try:
        return str(urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def _append_timeline_event(
    conversation,
    *,
    browser_id: str,
    event_type: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = _browser_workspace(conversation)
    event = {
        "id": f"evt_{uuid4().hex[:12]}",
        "browser_id": browser_id,
        "source": _safe_event_source(source),
        "event_type": event_type,
        "label": label,
        "payload": payload or {},
        "created_at": _now_iso(),
    }
    events = _coerce_list(workspace.get("timeline_events"))
    events.append(event)
    workspace["timeline_events"] = events[-120:]
    return event


def _compact_element_map(raw_map: Any) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in _coerce_list(raw_map):
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        compact.append(
            {
                "node_id": node_id,
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": str(item.get("text") or "")[:240],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": _coerce_list(item.get("selector_chain")),
                "shadow_path": _coerce_list(item.get("shadow_path")),
                "stable_key": str(item.get("stable_key") or ""),
                "interactable": bool(item.get("interactable")),
            }
        )
        if len(compact) >= 220:
            break
    return compact


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_event_source(value: str) -> str:
    source = str(value or "").strip().lower()
    return source if source in {"user", "agent", "system"} else "user"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _browser_worker():
    return get_container().get_lightpanda_browser_worker()
