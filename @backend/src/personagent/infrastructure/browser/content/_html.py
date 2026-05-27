"""HTML extraction helpers for BrowserContent."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)

logger = structlog.get_logger(__name__)


class _HtmlExtractionMixin:
    """Methods for extracting HTML from pages and URLs."""

    async def _html_or_empty(self, session: _BrowserSession) -> tuple[str, str]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._html_or_empty_url(url)

    async def _html_or_empty_page(self, page: Any, *, fallback_url: str) -> tuple[str, str]:
        try:
            await asyncio.wait_for(
                self._prepare_page_for_extraction(page),
                timeout=min(max(self._w.timeout_ms / 1000, 1.0), 22.0),
            )
        except Exception as exc:
            logger.debug("browser_page_html_prepare_failed", error=str(exc))
            return await self._html_or_empty_url(fallback_url)
        try:
            content = getattr(page, "content", None)
            if callable(content):
                html = await asyncio.wait_for(
                    content(),
                    timeout=min(self._w.timeout_ms / 1000, 10),
                )
                if isinstance(html, str):
                    return html, "prepared_playwright_page_content"
        except Exception as exc:
            logger.debug("browser_page_html_failed", error=str(exc))
        return await self._html_or_empty_url(fallback_url)

    async def _html_or_empty_url(self, url: str) -> tuple[str, str]:
        url = _clean_browser_url(url)
        value = await self._w._cdp_runtime.raw_runtime_evaluate_value(
            url,
            "document.documentElement ? document.documentElement.outerHTML : ''",
            label="html",
            timeout=min(self._w.timeout_ms / 1000, 10),
        )
        if isinstance(value, str):
            return value, "raw_cdp_runtime_evaluate"
        return "", "raw_cdp_runtime_unavailable"
