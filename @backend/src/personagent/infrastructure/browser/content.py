"""Browser content extraction (extract_content, get_html).

Extracted from ``lightpanda.py`` as part of Slice 8.
``BrowserContent`` receives a back-reference to the worker
(``self._w``) and delegates infrastructure calls through it.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.content_cleanup import (
    MARKDOWN_LINK_PATTERN as _MARKDOWN_LINK_PATTERN,
)
from personagent.infrastructure.browser.content_cleanup import (
    clean_extracted_content as _clean_extracted_content,
)
from personagent.infrastructure.browser.content_cleanup import (
    should_prefer_readable_dom as _should_prefer_readable_dom,
)
from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserOpenedPage,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.scripts import (
    _INCREMENTAL_SCROLL_SCRIPT,
    _POPUP_DISMISS_SCRIPT,
    _READABLE_DOM_SCRIPT,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)


class BrowserContent:
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

    # ------------------------------------------------------------------
    # Content-target resolution & page lookup
    # ------------------------------------------------------------------

    async def _content_page_for_target(
        self,
        *,
        conversation_id: str,
        session: _BrowserSession | None,
        target_url: str,
        target_page_id: str | None,
        allow_navigation: bool,
    ) -> Any | None:
        if session is None:
            return None
        clean_target_url = _clean_browser_url(target_url)
        if target_page_id:
            page = session.pages.get(target_page_id)
            if page is None and self._w._is_session_page_alias(conversation_id, session, target_page_id):
                page = self._w._preferred_session_page(session)
                if page is not None and self._w._page_is_open(page):
                    session.pages[target_page_id] = page
            if page is not None and self._is_live_page_for_url(page, clean_target_url):
                return page
            return None

        preferred_page = self._w._preferred_session_page(session)
        if self._is_live_page_for_url(preferred_page, clean_target_url):
            return preferred_page
        if not allow_navigation or not clean_target_url.startswith(("http://", "https://")):
            return None

        page = await self._w.session_manager.new_session_page(session)
        if page is None:
            page = preferred_page
        await self._w._goto_page(page, clean_target_url, allow_partial=True)
        session.page = page
        session.current_url = _clean_browser_url(
            str(getattr(page, "url", clean_target_url) or clean_target_url)
        )
        self._w.search_result_cache.remember_current_url(conversation_id, session.current_url)
        session.touch()
        return page

    def _is_live_page_for_url(self, page: Any, target_url: str) -> bool:
        with suppress(Exception):
            if page.is_closed():
                return False
        page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        return bool(page_url and _urls_equivalent(page_url, target_url))

    # ------------------------------------------------------------------
    # Page preparation (popup dismiss + incremental scroll)
    # ------------------------------------------------------------------

    async def _prepare_page_for_extraction(self, page: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "prepared_page": True,
            "popup_dismissed_count": 0,
            "popup_dismissed_labels": [],
            "scroll_steps": 0,
        }
        await self._wait_for_page_settle(page)
        with suppress(Exception):
            await page.wait_for_timeout(350)

        first_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, first_dismiss)
        if first_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(350)

        scroll = await self._scroll_page_incrementally(page)
        metadata.update(scroll)

        second_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, second_dismiss)
        if second_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(250)
        return metadata

    async def _wait_for_page_settle(self, page: Any) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state("domcontentloaded", timeout=min(self._w.timeout_ms, 8_000))
        with suppress(Exception):
            await wait_for_load_state("load", timeout=min(self._w.timeout_ms, 2_000))

    async def _dismiss_page_popups(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._w._evaluate_page(page, _POPUP_DISMISS_SCRIPT),
                timeout=min(self._w.timeout_ms / 1000, 3),
            )
        except Exception as exc:
            logger.debug("browser_popup_dismiss_failed", error=str(exc))
            return {"clicked_count": 0, "clicked_labels": [], "error": str(exc)}
        if isinstance(value, dict):
            labels = value.get("clicked_labels")
            return {
                "clicked_count": int(value.get("clicked_count") or 0),
                "clicked_labels": labels if isinstance(labels, list) else [],
            }
        return {"clicked_count": 0, "clicked_labels": []}

    def _merge_popup_dismissal(
        self,
        metadata: dict[str, Any],
        dismissed: dict[str, Any],
    ) -> None:
        clicked_count = int(dismissed.get("clicked_count") or 0)
        metadata["popup_dismissed_count"] = (
            int(metadata.get("popup_dismissed_count") or 0) + clicked_count
        )
        labels = metadata.setdefault("popup_dismissed_labels", [])
        if isinstance(labels, list):
            labels.extend(str(label) for label in dismissed.get("clicked_labels") or [])
            del labels[8:]

    async def _scroll_page_incrementally(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._w._evaluate_page(
                    page,
                    _INCREMENTAL_SCROLL_SCRIPT,
                    {
                        "maxSteps": 36,
                        "delayMs": 180,
                        "stepRatio": 0.82,
                    },
                ),
                timeout=min(max(self._w.timeout_ms / 1000, 1.0), 8.0),
            )
        except Exception as exc:
            logger.debug("browser_incremental_scroll_failed", error=str(exc))
            return {"scroll_error": str(exc)}
        if not isinstance(value, dict):
            return {}
        return {
            "scroll_steps": int(value.get("steps") or 0),
            "scroll_y": int(value.get("scroll_y") or 0),
            "scroll_height": int(value.get("scroll_height") or 0),
            "viewport_height": int(value.get("viewport_height") or 0),
            "scroll_at_bottom": bool(value.get("at_bottom")),
        }

    # ------------------------------------------------------------------
    # Markdown / text extraction
    # ------------------------------------------------------------------

    async def _markdown_or_text_page(
        self,
        page: Any,
        *,
        fallback_url: str,
    ) -> tuple[str, str, dict[str, Any]]:
        try:
            preparation = await asyncio.wait_for(
                self._prepare_page_for_extraction(page),
                timeout=min(max(self._w.timeout_ms / 1000, 1.0), 22.0),
            )
        except Exception as exc:
            fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
                fallback_url
            )
            return (
                fallback_content,
                fallback_method,
                {
                    **fallback_stats,
                    "prepared_page": False,
                    "prepare_error": str(exc),
                    "fallback": fallback_method,
                },
            )
        value: Any = None
        with suppress(Exception):
            value = await self._w._evaluate_page(page, _READABLE_DOM_SCRIPT)
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                cleaned, stats = _clean_extracted_content(content)
                if cleaned:
                    return (
                        cleaned,
                        "prepared_readable_dom_text",
                        {
                            **stats,
                            **preparation,
                            "selected_tag": value.get("selected_tag"),
                            "readable_score": value.get("score"),
                        },
                    )
        elif isinstance(value, str):
            cleaned, stats = _clean_extracted_content(value)
            if cleaned:
                return cleaned, "prepared_dom_text", {**stats, **preparation}

        text = ""
        with suppress(Exception):
            value = await self._w._evaluate_page(
                page,
                "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                "|| document.documentElement.textContent || '')",
            )
            if isinstance(value, str):
                text = value
        cleaned_text, text_stats = _clean_extracted_content(text)
        if cleaned_text:
            return cleaned_text, "prepared_dom_text", {**text_stats, **preparation}

        fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
            fallback_url
        )
        return (
            fallback_content,
            fallback_method,
            {
                **fallback_stats,
                **preparation,
                "fallback": fallback_method,
            },
        )

    async def _markdown_or_text(self, session: _BrowserSession) -> tuple[str, str, dict[str, Any]]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._markdown_or_text_url(url)

    async def _markdown_or_text_url(self, url: str) -> tuple[str, str, dict[str, Any]]:
        markdown = await self._w._lightpanda_markdown_url(url)
        if markdown:
            cleaned_markdown, stats = _clean_extracted_content(markdown)
            if _should_prefer_readable_dom(cleaned_markdown, stats):
                readable = await self._readable_dom_content_url(url)
                if readable:
                    return (
                        readable,
                        "readable_dom_text",
                        {
                            **stats,
                            "fallback": "readable_dom_text",
                        },
                    )
            if cleaned_markdown:
                method = (
                    "lightpanda_markdown_cleaned"
                    if stats.get("removed_link_noise_blocks")
                    else "lightpanda_markdown"
                )
                return cleaned_markdown, method, stats
        readable = await self._readable_dom_content_url(url)
        if readable:
            return readable, "readable_dom_text", {}
        text = await self._w._raw_runtime_evaluate_value(
            url,
            "(document.body && (document.body.innerText || document.body.textContent)) "
            "|| document.documentElement.textContent || ''",
            label="dom_text",
            timeout=min(self._w.timeout_ms / 1000, 5),
        )
        if not isinstance(text, str):
            return "", "dom_text_failed", {}
        cleaned_text, stats = _clean_extracted_content(text)
        return cleaned_text, "dom_text", stats

    async def _readable_dom_content_url(self, url: str) -> str:
        value = await self._w._raw_runtime_evaluate_value(
            url,
            _READABLE_DOM_SCRIPT,
            label="readable_dom",
            timeout=min(self._w.timeout_ms / 1000, 8),
        )
        if not isinstance(value, dict):
            return ""
        content = value.get("content")
        if not isinstance(content, str):
            return ""
        cleaned, _stats = _clean_extracted_content(content)
        return cleaned



    def _extract_markdown_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("markdown", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str):
            return payload
        return ""

    # ------------------------------------------------------------------
    # HTML extraction
    # ------------------------------------------------------------------

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
        value = await self._w._raw_runtime_evaluate_value(
            url,
            "document.documentElement ? document.documentElement.outerHTML : ''",
            label="html",
            timeout=min(self._w.timeout_ms / 1000, 10),
        )
        if isinstance(value, str):
            return value, "raw_cdp_runtime_evaluate"
        return "", "raw_cdp_runtime_unavailable"

    # ------------------------------------------------------------------
    # Link extraction
    # ------------------------------------------------------------------

    def _extract_links_from_content(self, content: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in _MARKDOWN_LINK_PATTERN.finditer(content):
            text = " ".join(match.group(1).split())
            url = match.group(2).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"url": url, "text": text})
            if len(links) >= 50:
                break
        return links

    # ------------------------------------------------------------------
    # Opened-page bookkeeping (content-specific)
    # ------------------------------------------------------------------

    def _mark_opened_page_extracted(self, opened_page: BrowserOpenedPage) -> None:
        opened_page.extraction_count += 1
        import time

        opened_page.last_extracted_at = time.monotonic()
