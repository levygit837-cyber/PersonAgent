"""Browser page lifecycle operations extracted from the LightPanda god file."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog

from personagent.infrastructure.browser.models import BrowserError
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)


class BrowserPageLifecycle:
    """Tab management: open, close, switch, reload, history, list."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # open
    # ------------------------------------------------------------------

    async def open(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        result_index: int | None = None,
        search_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        """Open a URL or one of the last search results."""

        session = await self._w.session_manager.get_session(conversation_id)
        target_url = _clean_browser_url(url) if isinstance(url, str) else url
        matched_search_id = None
        matched_search_title = ""
        if target_url is None and result_index is not None:
            target_url, matched_search_id = self._w.search_result_cache.result_url(
                conversation_id,
                session,
                result_index,
                search_id=search_id,
            )
            matched_search_title = self._w.search_result_cache.result_title(
                conversation_id,
                result_index,
                search_id=matched_search_id or search_id,
            )
        elif target_url and search_id:
            matched_search_id = self._w.search_result_cache.match_search_result_url(
                conversation_id,
                target_url,
                search_id=search_id,
            )
            if matched_search_id:
                matched_search_title = self._w.search_result_cache.match_search_result_title(
                    conversation_id,
                    target_url,
                    search_id=matched_search_id,
                )
        if target_url is None:
            raise BrowserError("BrowserOpen requires url or result_index.")
        existing_opened_page = self._w.opened_pages.opened_page_by_url(conversation_id, target_url)
        existing_page = (
            session.pages.get(existing_opened_page.page_id)
            if existing_opened_page is not None
            else None
        )
        if existing_opened_page is not None and existing_page is not None and self._w.session_manager.page_is_open(existing_page):
            session.page = existing_page
            session.current_url = existing_opened_page.final_url
            session.last_open_url = existing_opened_page.final_url
            session.last_open_page_id = existing_opened_page.page_id
            session.current_page_id = existing_opened_page.page_id
            self._w._last_open_cache[conversation_id] = existing_opened_page
            self._w.search_result_cache.remember_current_url(conversation_id, existing_opened_page.final_url)
            self._w.console.attach_page_console_listeners(conversation_id, existing_opened_page.page_id, existing_page)
            session.touch()
            return self._w.opened_pages.browser_open_response(
                conversation_id=conversation_id,
                opened_page=existing_opened_page,
                requested_url=target_url,
                title=existing_opened_page.title,
                search_id=matched_search_id or existing_opened_page.source_search_id,
                reused_existing_page=True,
            )
        page = await self._w.session_manager.new_session_page(session)
        close_failed_page = page is not None
        if page is None:
            page = self._w.session_manager.preferred_session_page(session)
        try:
            await self._w._goto_page(page, target_url, allow_partial=True)
            await self._w.block_detector.raise_if_search_blocked(page)
        except Exception:
            if close_failed_page:
                await self._w.session_manager.best_effort_resource_call("browser_open_failed_page_close", page.close)
            raise
        title = await self._w.page_helpers.safe_title(page)
        if not title:
            title = matched_search_title
        final_url = str(getattr(page, "url", target_url) or target_url)
        session.current_url = final_url
        self._w.search_result_cache.remember_current_url(conversation_id, final_url)
        opened_page, reused_existing_page = self._w.opened_pages.cache_opened_page(
            conversation_id=conversation_id,
            url=target_url,
            final_url=final_url,
            title=title,
            source_search_id=matched_search_id,
            opener_tool_call_id=tool_call_id,
        )
        previous_page = session.pages.get(opened_page.page_id)
        if previous_page is not None and previous_page is not page and self._w.session_manager.page_is_open(previous_page):
            await self._w.session_manager.best_effort_resource_call("browser_reused_previous_page_close", previous_page.close)
        session.pages[opened_page.page_id] = page
        session.page = page
        session.last_open_url = opened_page.final_url
        session.last_open_page_id = opened_page.page_id
        session.current_page_id = opened_page.page_id
        self._w.console.attach_page_console_listeners(conversation_id, opened_page.page_id, page)
        await self._w.session_manager.cleanup_live_pages(conversation_id, session, keep_page_id=opened_page.page_id)
        session.touch()
        return self._w.opened_pages.browser_open_response(
            conversation_id=conversation_id,
            opened_page=opened_page,
            requested_url=target_url,
            title=title,
            search_id=matched_search_id,
            reused_existing_page=reused_existing_page,
        )

    # ------------------------------------------------------------------
    # list_tabs
    # ------------------------------------------------------------------

    async def list_tabs(
        self,
        *,
        conversation_id: str,
        max_tabs: int,
    ) -> dict[str, Any]:
        """Return logical browser tabs opened during the conversation."""

        await self._w.session_manager.cleanup_sessions()
        max_tabs = min(max(1, int(max_tabs)), 50)
        session = self._w._sessions.get(conversation_id)
        current_url = self._w._current_url_cache.get(conversation_id)
        if session is not None:
            current_url = session.current_url or current_url
        last_open = self._w._last_open_cache.get(conversation_id)
        pages = self._w._opened_pages_cache.get(conversation_id, [])[:max_tabs]
        if session is None and not current_url and not pages:
            panel_tabs = await self._w.snapshot.panel_session_tabs(max_tabs=max_tabs, exclude_conversation_id=conversation_id)
            if panel_tabs:
                first_tab = panel_tabs[0]
                return {
                    "type": "browser_tabs",
                    "browser_id": first_tab.get("browser_id"),
                    "tab_count": len(panel_tabs),
                    "max_tabs": max_tabs,
                    "current_url": first_tab.get("final_url") or first_tab.get("url"),
                    "last_open_page_id": first_tab.get("page_id"),
                    "last_open_window_id": first_tab.get("window_id"),
                    "tabs": panel_tabs,
                    "source": "shared_panel_sessions",
                }
        tabs = [
            self._w.opened_pages.opened_page_tab(
                page,
                index=index,
                current_url=current_url,
                last_open_page_id=last_open.page_id if last_open is not None else None,
            )
            for index, page in enumerate(pages, start=1)
        ]
        active_page_id = (
            (session.current_page_id or session.last_open_page_id)
            if session is not None
            else None
        )
        if not tabs and current_url:
            active_page_id = active_page_id or conversation_id
            title = ""
            if session is not None:
                with suppress(Exception):
                    title = await self._w.page_helpers.safe_title(session.page)
            parsed = urlparse(current_url)
            domain = parsed.netloc
            tabs.append(
                {
                    "index": 1,
                    "page_id": active_page_id,
                    "window_id": active_page_id,
                    "tab_id": active_page_id,
                    "id": active_page_id,
                    "url": current_url,
                    "final_url": current_url,
                    "domain": domain,
                    "title": title,
                    "summary": title or domain or current_url,
                    "source_search_id": None,
                    "opener_tool_call_id": None,
                    "extraction_count": 0,
                    "already_read": False,
                    "read_status": "unread",
                    "is_last_open": True,
                    "is_current_page": True,
                    "active": True,
                    "is_active": True,
                    "history": [current_url] if current_url != "about:blank" else [],
                    "source": "shared_browser_current",
                }
            )
        if len(tabs) < max_tabs:
            seen_tab_ids = {
                str(tab.get("page_id") or tab.get("tab_id") or tab.get("browser_id") or "").strip()
                for tab in tabs
                if isinstance(tab, Mapping)
            }
            panel_tabs = await self._w.snapshot.panel_session_tabs(
                max_tabs=max_tabs,
                exclude_conversation_id=conversation_id,
            )
            for panel_tab in panel_tabs:
                tab_id = str(
                    panel_tab.get("page_id")
                    or panel_tab.get("tab_id")
                    or panel_tab.get("browser_id")
                    or ""
                ).strip()
                if tab_id and tab_id in seen_tab_ids:
                    continue
                next_tab = dict(panel_tab)
                next_tab["index"] = len(tabs) + 1
                tabs.append(next_tab)
                if tab_id:
                    seen_tab_ids.add(tab_id)
                if len(tabs) >= max_tabs:
                    break
        last_open_page_id = last_open.page_id if last_open is not None else active_page_id
        return {
            "type": "browser_tabs",
            "tab_count": len(tabs),
            "max_tabs": max_tabs,
            "current_url": current_url,
            "last_open_page_id": last_open_page_id,
            "last_open_window_id": last_open.window_id if last_open is not None else last_open_page_id,
            "tabs": tabs,
        }

    # ------------------------------------------------------------------
    # close_tab
    # ------------------------------------------------------------------

    async def close_tab(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        max_tabs: int = 20,
    ) -> dict[str, Any]:
        """Close one logical browser tab and return the updated tab list."""

        session = await self._w.session_manager.get_session(conversation_id)
        target_page_id = str(page_id or session.current_page_id or session.last_open_page_id or "").strip()
        if not target_page_id:
            last_open = self._w._last_open_cache.get(conversation_id)
            target_page_id = last_open.page_id if last_open is not None else ""
        if not target_page_id:
            raise BrowserError("No browser page selected. Run BrowserOpen first.")
        live_page = session.pages.pop(target_page_id, None)
        if live_page is None and self._w._is_session_page_alias(conversation_id, session, target_page_id):
            live_page = self._w.session_manager.preferred_session_page(session)
        closed = False
        if live_page is not None:
            await self._w.session_manager.best_effort_resource_call("browser_control_close_page", live_page.close)
            closed = True
        pages = self._w._opened_pages_cache.get(conversation_id, [])
        remaining_pages = [opened_page for opened_page in pages if opened_page.page_id != target_page_id]
        self._w._opened_pages_cache[conversation_id] = remaining_pages
        if self._w._last_open_cache.get(conversation_id) is not None and self._w._last_open_cache[conversation_id].page_id == target_page_id:
            if remaining_pages:
                self._w._last_open_cache[conversation_id] = remaining_pages[0]
            else:
                self._w._last_open_cache.pop(conversation_id, None)
        self._w._console_cache.get(conversation_id, {}).pop(target_page_id, None)
        self._w._element_map_cache.pop(conversation_id, None)
        if session.current_page_id == target_page_id:
            next_page_id = next((candidate for candidate in session.pages if candidate != target_page_id), None)
            if next_page_id:
                session.current_page_id = next_page_id
                session.last_open_page_id = next_page_id
                session.page = session.pages[next_page_id]
            elif remaining_pages:
                session.current_page_id = remaining_pages[0].page_id
                session.last_open_page_id = remaining_pages[0].page_id
            else:
                session.current_page_id = None
                session.last_open_page_id = None
        session.touch()
        tabs = await self.list_tabs(conversation_id=conversation_id, max_tabs=max_tabs)
        tabs.update(
            {
                "type": "browser_close_tab",
                "closed_page_id": target_page_id,
                "closed_window_id": target_page_id,
                "closed": closed or len(remaining_pages) != len(pages),
            }
        )
        return tabs

    # ------------------------------------------------------------------
    # reload
    # ------------------------------------------------------------------

    async def reload(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        view = await self._w.view_reload(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_reload",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": True,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------

    async def history(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        direction: int = -1,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        safe_direction = -1 if int(direction) < 0 else 1
        view = await self._w.view_history(
            browser_id=conversation_id,
            direction=safe_direction,
            width=width,
            height=height,
        )
        view.update(
            {
                "type": "browser_history",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "direction": safe_direction,
                "navigated": True,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    # ------------------------------------------------------------------
    # switch_tab
    # ------------------------------------------------------------------

    async def switch_tab(
        self,
        *,
        conversation_id: str,
        page_id: str,
        max_tabs: int = 20,
    ) -> dict[str, Any]:
        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        session.current_url = _clean_browser_url(str(getattr(page, "url", "") or session.current_url or ""))
        session.touch()
        tabs = await self.list_tabs(conversation_id=conversation_id, max_tabs=max_tabs)
        tabs.update(
            {
                "type": "browser_switch_tab",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "active_tab_id": resolved_page_id,
                "navigated": False,
            }
        )
        return tabs
