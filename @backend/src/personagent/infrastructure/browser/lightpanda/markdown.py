"""LightPanda markdown extraction helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
    from personagent.infrastructure.browser.models import BrowserSession as _BrowserSession

logger = structlog.get_logger(__name__)


class BrowserMarkdown:
    """Extracts markdown from LightPanda pages via native CDP."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    async def lightpanda_markdown(self, session: _BrowserSession) -> str:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._w._markdown.lightpanda_markdown_url(url)

    async def lightpanda_markdown_url(self, url: str) -> str:
        url = _clean_browser_url(url)
        if not url or url == "about:blank":
            return ""
        try:
            payload = await asyncio.wait_for(
                self._w._cdp_runtime.lightpanda_raw_cdp_command(
                    url=url,
                    method="LP.getMarkdown",
                ),
                timeout=min(self._w.timeout_ms / 1000, 15),
            )
            markdown = self._w.content_module._extract_markdown_payload(payload)
            if markdown:
                return markdown
        except TimeoutError as exc:
            logger.warning("lightpanda_markdown_raw_timeout", error=str(exc), url=url)
            return ""
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        return ""
