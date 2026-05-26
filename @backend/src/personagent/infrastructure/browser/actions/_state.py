from __future__ import annotations

from contextlib import suppress
from typing import Any


class _StateMixin:
    async def scroll(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        delta_x: float = 0.0,
        delta_y: float = 600.0,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        view = await self._w.view_scroll(
            browser_id=conversation_id,
            delta_x=delta_x,
            delta_y=delta_y,
            width=width,
            height=height,
        )
        view.update(
            {
                "type": "browser_scroll",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": False,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    async def wait(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        timeout_ms: int = 1_000,
        state: str | None = None,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        safe_timeout_ms = min(max(int(timeout_ms), 1), 120_000)
        state_value = str(state or "").strip()
        if state_value:
            wait_for_load_state = getattr(page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                with suppress(Exception):
                    await wait_for_load_state(state_value, timeout=safe_timeout_ms)
        else:
            with suppress(Exception):
                await page.wait_for_timeout(safe_timeout_ms)
        view = await self._w.snapshot.browser_view_snapshot(conversation_id, session, width=width, height=height)
        view.update(
            {
                "type": "browser_wait",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "timeout_ms": safe_timeout_ms,
                "state": state_value or None,
                "navigated": False,
            }
        )
        return view
