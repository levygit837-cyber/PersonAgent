"""Standalone browser viewport routes (no conversation context).

Thin wrappers around ``_browser_worker().view_*()`` with uniform error
handling.  These endpoints are mounted under ``/sessions/browser/...``
and do not load or persist any conversation state.

``_browser_worker`` resolves ``get_container`` via the parent sessions
module so that test monkeypatches on ``sessions.get_container`` are
picked up at call time (late-binding, same pattern used in
``chat/completion.py``).
"""

from typing import Any

from fastapi import HTTPException, Query

import personagent.interfaces.api.routes.sessions as _sessions
from personagent.infrastructure.browser.lightpanda import BrowserError, BrowserUnavailableError
from personagent.interfaces.api.routes.sessions.models import (
    SessionBrowserActionRequest,
    SessionBrowserHistoryRequest,
    SessionBrowserKeyboardRequest,
    SessionBrowserNavigateRequest,
    SessionBrowserPointerRequest,
    SessionBrowserScrollRequest,
    SessionBrowserViewport,
)


def _browser_worker():
    return _sessions.get_container().get_lightpanda_browser_worker()


def register_browser_viewport_routes(router) -> None:
    """Register standalone browser viewport endpoints on the sessions router."""

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
