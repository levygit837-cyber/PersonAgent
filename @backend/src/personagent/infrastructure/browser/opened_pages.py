"""Opened-page tracking for the browser worker.

Extracted from ``lightpanda.py`` (Slice 10).  The ``OpenedPageTracker``
helper owns:

* Caching opened pages per conversation (with URL dedup)
* Building ``browser_open`` response dicts
* Tab info formatting for list_tabs
* Lookup by page_id or URL
* Next-unextracted page selection for content extraction
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from personagent.infrastructure.browser.models import BrowserOpenedPage
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

_MAX_OPENED_PAGES_PER_CONVERSATION = 32


class OpenedPageTracker:
    """Manages the opened-page cache and response formatting."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def cache_opened_page(
        self,
        *,
        conversation_id: str,
        url: str,
        final_url: str,
        title: str,
        source_search_id: str | None,
        opener_tool_call_id: str | None,
    ) -> tuple[BrowserOpenedPage, bool]:
        url = _clean_browser_url(url)
        final_url = _clean_browser_url(final_url)
        pages = self._w._opened_pages_cache.setdefault(conversation_id, [])
        existing = self.opened_page_by_url(
            conversation_id, final_url
        ) or self.opened_page_by_url(conversation_id, url)
        if existing is not None:
            existing.url = url or existing.url
            existing.final_url = final_url or existing.final_url
            existing.title = title or existing.title
            existing.source_search_id = (
                source_search_id or existing.source_search_id
            )
            existing.opener_tool_call_id = (
                opener_tool_call_id or existing.opener_tool_call_id
            )
            existing.opened_at = time.monotonic()
            pages[:] = [
                page for page in pages if page.page_id != existing.page_id
            ]
            pages.insert(0, existing)
            del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
            self._w._last_open_cache[conversation_id] = existing
            return existing, True
        raw_id = f"{conversation_id}\n{final_url}\n{time.monotonic_ns()}"
        page_id = f"page_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        opened_page = BrowserOpenedPage(
            page_id=page_id,
            url=url,
            final_url=final_url,
            title=title,
            source_search_id=source_search_id,
            opener_tool_call_id=opener_tool_call_id,
        )
        pages.insert(0, opened_page)
        del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
        self._w._last_open_cache[conversation_id] = opened_page
        return opened_page, False

    # ------------------------------------------------------------------
    # Response formatting
    # ------------------------------------------------------------------

    def browser_open_response(
        self,
        *,
        conversation_id: str,
        opened_page: BrowserOpenedPage,
        requested_url: str,
        title: str,
        search_id: str | None,
        reused_existing_page: bool,
    ) -> dict[str, Any]:
        return {
            "type": "browser_open",
            "url": requested_url,
            "final_url": opened_page.final_url,
            "title": title or opened_page.title,
            "search_id": search_id,
            "page_id": opened_page.page_id,
            "window_id": opened_page.window_id,
            "opened_page_count": len(
                self._w._opened_pages_cache.get(conversation_id, [])
            ),
            "recent_opened_pages": [
                page.to_dict()
                for page in self._w._opened_pages_cache.get(
                    conversation_id, []
                )[:5]
            ],
            "reused_existing_page": reused_existing_page,
            "already_open": reused_existing_page,
            "already_read": opened_page.extraction_count > 0,
            "read_status": self.opened_page_read_status(opened_page),
            "extraction_count": opened_page.extraction_count,
        }

    @staticmethod
    def opened_page_read_status(opened_page: BrowserOpenedPage) -> str:
        return "read" if opened_page.extraction_count > 0 else "unread"

    def opened_page_tab(
        self,
        page: BrowserOpenedPage,
        *,
        index: int,
        current_url: str | None,
        last_open_page_id: str | None,
    ) -> dict[str, Any]:
        parsed = urlparse(page.final_url or page.url)
        domain = parsed.netloc
        title = page.title.strip() if page.title else ""
        summary = title or domain or page.final_url
        return {
            "index": index,
            "page_id": page.page_id,
            "window_id": page.window_id,
            "url": page.url,
            "final_url": page.final_url,
            "domain": domain,
            "title": title,
            "summary": summary,
            "source_search_id": page.source_search_id,
            "opener_tool_call_id": page.opener_tool_call_id,
            "extraction_count": page.extraction_count,
            "already_read": page.extraction_count > 0,
            "read_status": self.opened_page_read_status(page),
            "is_last_open": page.page_id == last_open_page_id,
            "is_current_page": bool(
                current_url and current_url == page.final_url
            ),
        }

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def opened_page(
        self,
        conversation_id: str,
        page_id: str,
    ) -> BrowserOpenedPage | None:
        for op in self._w._opened_pages_cache.get(conversation_id, []):
            if op.page_id == page_id:
                return op
        return None

    def opened_page_by_url(
        self,
        conversation_id: str,
        url: str,
    ) -> BrowserOpenedPage | None:
        target_url = _clean_browser_url(url)
        if not target_url:
            return None
        for op in self._w._opened_pages_cache.get(conversation_id, []):
            if _urls_equivalent(
                op.final_url, target_url
            ) or _urls_equivalent(op.url, target_url):
                return op
        return None

    def target_title(
        self, conversation_id: str, page_id: str | None
    ) -> str:
        if not page_id:
            return ""
        op = self.opened_page(conversation_id, page_id)
        return op.title if op is not None else ""

    def next_unextracted_opened_page(
        self, conversation_id: str
    ) -> BrowserOpenedPage | None:
        pages = [
            page
            for page in self._w._opened_pages_cache.get(
                conversation_id, []
            )
            if page.extraction_count == 0
        ]
        if not pages:
            return None
        return min(pages, key=lambda page: page.opened_at)
