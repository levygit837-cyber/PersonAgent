"""Browser navigation helpers — goto and page-level navigation."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserBlockedError,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.url_utils import clean_browser_url as _clean_browser_url

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
    from personagent.infrastructure.browser.models import BrowserSession as _BrowserSession

logger = structlog.get_logger(__name__)


class BrowserNavigation:
    """Page navigation and goto helpers."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    async def goto(
        self,
        conversation_id: str,
        session: _BrowserSession,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        try:
            await self._w._goto_page(
                session.page, url, allow_partial=allow_partial, wait_for_styles=wait_for_styles
            )
        except Exception:
            await self._w.session_manager.close_session(conversation_id, session)
            raise

    async def goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        clean_url = _clean_browser_url(url)
        try:
            await page.goto(
                clean_url,
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self._w.timeout_ms,
            )
            if wait_for_styles:
                await self._w.page_helpers.wait_for_page_visual_ready(page)
            await self._w.console.install_console_capture(page)
        except Exception as exc:
            from urllib.parse import urlparse

            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if allow_partial and page_url.startswith(("http://", "https://")):
                logger.warning(
                    "lightpanda_navigation_partial",
                    url=clean_url,
                    page_url=page_url,
                    error=str(exc),
                )
                with suppress(Exception):
                    await self._w.console.install_console_capture(page)
                return
            if "RobotsBlocked" in str(exc):
                raise BrowserBlockedError(
                    "LightPanda blocked navigation because `--obey-robots` is enabled.",
                    provider=urlparse(clean_url).hostname or "",
                    reason="robots_txt",
                    url=clean_url,
                ) from exc
            raise BrowserUnavailableError(
                f"LightPanda navigation failed for {clean_url}: {exc}"
            ) from exc
