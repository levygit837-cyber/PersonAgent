"""Browser content extraction (extract_content, get_html).

Extracted from ``lightpanda.py`` as part of Slice 8.
``BrowserContent`` receives a back-reference to the worker
(``self._w``) and delegates infrastructure calls through it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from personagent.infrastructure.browser.content._html import _HtmlExtractionMixin
from personagent.infrastructure.browser.content._links import _LinkExtractionMixin
from personagent.infrastructure.browser.content._markdown import _MarkdownExtractionMixin
from personagent.infrastructure.browser.content._preparation import _PagePreparationMixin
from personagent.infrastructure.browser.content._target import _ContentTargetMixin
from personagent.infrastructure.browser.models import (
    BrowserError,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker


class BrowserContent(
    _ContentTargetMixin,
    _PagePreparationMixin,
    _MarkdownExtractionMixin,
    _HtmlExtractionMixin,
    _LinkExtractionMixin,
):
    """Content extraction methods extracted from ``LightPandaBrowserWorker``."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def extract_content(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        """Return organized markdown/text content for the current or provided URL."""
        session = self._w.session_manager.cached_usable_session(conversation_id)
        target_url, target_page_id = self._w._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._w.session_manager.get_session(conversation_id)
            target_url, target_page_id = self._w._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        if session is None and url and not target_page_id:
            session = await self._w.session_manager.get_session(conversation_id)
        final_url = _clean_browser_url(str(target_url))
        page = await self._content_page_for_target(
            conversation_id=conversation_id,
            session=session,
            target_url=final_url,
            target_page_id=target_page_id,
            allow_navigation=bool(url and not target_page_id),
        )
        title = self._w.opened_pages.target_title(conversation_id, target_page_id)
        if page is not None:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                final_url = page_url
            if not title:
                title = await self._w.page_helpers.safe_title(page)
            content, extraction_method, content_cleanup = await self._markdown_or_text_page(
                page,
                fallback_url=final_url,
            )
        else:
            if not title and session is not None:
                title = await self._w.page_helpers.safe_title(session.page)
            content, extraction_method, content_cleanup = await self._markdown_or_text_url(
                final_url
            )
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip()
        links = self._extract_links_from_content(content) if include_links else []
        buttons: list[dict[str, str]] = []
        if session is not None:
            session.current_url = final_url
        self._w.search_result_cache.remember_current_url(conversation_id, final_url)
        opened_page = self._w.opened_pages.opened_page(conversation_id, target_page_id) if target_page_id else None
        already_read = opened_page.extraction_count > 0 if opened_page is not None else False
        if opened_page is not None:
            if session is not None:
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
            self._mark_opened_page_extracted(opened_page)
            if session is not None:
                await self._w.session_manager.cleanup_live_pages(
                    conversation_id,
                    session,
                    keep_page_id=opened_page.page_id,
                    close_read_pages=True,
                )
        if session is not None:
            session.touch()
        return {
            "type": "browser_extract_content",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "content": content,
            "extraction_method": extraction_method,
            "content_cleanup": content_cleanup,
            "links": links,
            "buttons": buttons,
            "truncated": truncated,
            "already_read": already_read,
            "read_status": "already_read" if already_read else "read",
            "extraction_count": opened_page.extraction_count if opened_page is not None else 0,
        }

    async def get_html(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
    ) -> dict[str, Any]:
        """Return raw HTML for the current or provided URL."""
        session = self._w.session_manager.cached_usable_session(conversation_id)
        target_url, target_page_id = self._w._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._w.session_manager.get_session(conversation_id)
            target_url, target_page_id = self._w._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        if session is None and url and not target_page_id:
            session = await self._w.session_manager.get_session(conversation_id)
        final_url = _clean_browser_url(str(target_url))
        page = await self._content_page_for_target(
            conversation_id=conversation_id,
            session=session,
            target_url=final_url,
            target_page_id=target_page_id,
            allow_navigation=bool(url and not target_page_id),
        )
        title = self._w.opened_pages.target_title(conversation_id, target_page_id)
        if page is not None:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                final_url = page_url
            if not title:
                title = await self._w.page_helpers.safe_title(page)
            html, html_method = await self._html_or_empty_page(page, fallback_url=final_url)
        else:
            if not title and session is not None:
                title = await self._w.page_helpers.safe_title(session.page)
            html, html_method = await self._html_or_empty_url(final_url)
        truncated = len(html) > max_chars
        if truncated:
            html = html[:max_chars].rstrip()
        if session is not None:
            session.current_url = final_url
        self._w.search_result_cache.remember_current_url(conversation_id, final_url)
        opened_page = None
        if session is not None and target_page_id:
            opened_page = self._w.opened_pages.opened_page(conversation_id, target_page_id)
            if opened_page is not None:
                already_read = opened_page.extraction_count > 0
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
                self._mark_opened_page_extracted(opened_page)
                await self._w.session_manager.cleanup_live_pages(
                    conversation_id,
                    session,
                    keep_page_id=opened_page.page_id,
                    close_read_pages=True,
                )
            else:
                already_read = False
        else:
            already_read = False
        if session is not None:
            session.touch()
        return {
            "type": "browser_get_html",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "html": html,
            "html_method": html_method,
            "truncated": truncated,
            "already_read": already_read,
            "read_status": "already_read" if already_read else "read",
            "extraction_count": opened_page.extraction_count
            if session is not None and target_page_id and opened_page is not None
            else 0,
        }
