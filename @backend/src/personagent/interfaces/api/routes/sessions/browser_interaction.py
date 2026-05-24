"""Conversation-scoped browser interaction routes.

View, navigate, history, reload, click, key, scroll, and action endpoints
that load a conversation, interact with the browser worker, and persist
workspace state via the shared infrastructure helpers.
"""

from typing import Any

from fastapi import HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

import personagent.interfaces.api.routes.sessions as _sessions
from personagent.infrastructure.browser.lightpanda import BrowserError, BrowserUnavailableError
from personagent.interfaces.api.routes.sessions._workspace_infra import (
    _persist_browser_workspace_view,
    _record_canonical_browser_event,
    _record_timeline_event,
)
from personagent.interfaces.api.routes.sessions.models import (
    SessionBrowserActionRequest,
    SessionBrowserHistoryRequest,
    SessionBrowserKeyboardRequest,
    SessionBrowserNavigateRequest,
    SessionBrowserPointerRequest,
    SessionBrowserScrollRequest,
    SessionBrowserViewport,
)


def register_browser_interaction_routes(router) -> None:
    """Register conversation-scoped browser interaction endpoints on the sessions router."""

    @router.get("/{conversation_id}/browser/{browser_id}/view")
    async def get_conversation_browser_view(
        conversation_id: str,
        browser_id: str,
        width: int = Query(default=1024, ge=320, le=2400),
        height: int = Query(default=720, ge=240, le=1800),
        cache_mode: str = Query(default="prefer_live", pattern="^(prefer_live|prefer_cached)$"),
        wait_for_styles: bool = Query(default=True),
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Return a Browser Workspace view enriched with conversation annotations/timeline."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_snapshot(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Navigate a conversation Browser Workspace and return the enriched snapshot."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_navigate(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Move conversation Browser Workspace history."""

        if request.direction == 0:
            raise HTTPException(status_code=400, detail="Browser history direction must be -1 or 1.")
        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_history(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Reload conversation Browser Workspace."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_reload(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Click conversation Browser Workspace by viewport coordinates."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_click(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Send keyboard input to conversation Browser Workspace."""

        if not request.text and not request.key:
            raise HTTPException(status_code=400, detail="Browser keyboard input requires text or key.")
        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_key(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Scroll conversation Browser Workspace."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_scroll(
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
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Execute a mapped DOM action in the Browser Workspace."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        try:
            view = await _sessions._browser_worker().view_act(
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
            source=_sessions._safe_event_source(request.source),
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
            source=_sessions._safe_event_source(request.source),
            label=f"{request.action} {request.node_id}",
            payload={
                "node_id": request.node_id,
                "action": request.action,
                "url": view.get("url") or "",
                "title": view.get("title") or "",
            },
        )
        return await _persist_browser_workspace_view(conversation, session, browser_id, view)
