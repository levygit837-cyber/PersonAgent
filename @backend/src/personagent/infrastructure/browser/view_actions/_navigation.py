from __future__ import annotations

from contextlib import suppress
from typing import Any

import structlog

from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.search.url_utils import (
    normalize_navigation_url as _normalize_navigation_url,
)

logger = structlog.get_logger(__name__)


class _NavigationMixin:
    async def view_navigate(
        self,
        *,
        browser_id: str,
        url: str,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        """Navigate the session-panel browser and return the rendered view."""

        session = await self._w.session_manager.get_session(browser_id)
        target_url = _normalize_navigation_url(url)
        await self._w._goto(browser_id, session, target_url, allow_partial=True, wait_for_styles=wait_for_styles)
        final_url = _clean_browser_url(str(getattr(session.page, "url", target_url) or target_url))
        session.current_url = final_url
        session.last_open_url = final_url
        self._w.session_manager.ensure_session_page_alias(browser_id, session)
        self._w.search_result_cache.remember_current_url(browser_id, final_url)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    async def view_history(
        self,
        *,
        browser_id: str,
        direction: int,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        """Move the session-panel browser back or forward in its real page history."""

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        operation = getattr(page, "go_back" if direction < 0 else "go_forward", None)
        if not callable(operation):
            raise BrowserUnavailableError("LightPanda history navigation is unavailable.")
        with suppress(Exception):
            await operation(
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self._w.timeout_ms,
            )
        if wait_for_styles:
            await self._w.page_helpers.wait_for_page_visual_ready(page)
        final_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if final_url:
            session.current_url = final_url
            session.last_open_url = final_url
            self._w.search_result_cache.remember_current_url(browser_id, final_url)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    async def view_reload(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        """Reload the current session-panel browser page and return the rendered view."""

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        current_url = _clean_browser_url(
            str(getattr(page, "url", "") or session.current_url or session.last_open_url or "")
        )
        operation = getattr(page, "reload", None)
        if callable(operation):
            try:
                await operation(
                    wait_until="load" if wait_for_styles else "domcontentloaded",
                    timeout=self._w.timeout_ms,
                )
            except Exception as exc:
                if current_url.startswith(("http://", "https://")):
                    logger.warning("lightpanda_reload_falling_back_to_goto", url=current_url, error=str(exc))
                    await self._w._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
                else:
                    raise BrowserUnavailableError("LightPanda reload is unavailable.") from exc
        elif current_url.startswith(("http://", "https://")):
            await self._w._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
        else:
            raise BrowserUnavailableError("LightPanda reload is unavailable.")
        if wait_for_styles:
            await self._w.page_helpers.wait_for_page_visual_ready(page)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )
