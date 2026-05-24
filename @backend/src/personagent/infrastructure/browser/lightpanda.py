"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from personagent.infrastructure.browser.actions import BrowserActions
from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache
from personagent.infrastructure.browser.console import BrowserConsole
from personagent.infrastructure.browser.content import BrowserContent
from personagent.infrastructure.browser.element_helpers import ElementHelpers
from personagent.infrastructure.browser.models import (
    BrowserBlockedError,
    BrowserConsoleEntry,
    BrowserError,
    BrowserOpenedPage,
    BrowserSearchResult,
    BrowserSearchSnapshot,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.opened_pages import OpenedPageTracker
from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.browser.page_lifecycle import BrowserPageLifecycle
from personagent.infrastructure.browser.scripts import (
    _STYLE_READY_SNAPSHOT_SCRIPT,
)
from personagent.infrastructure.browser.search import BrowserSearch
from personagent.infrastructure.browser.search_cache import SearchResultCache
from personagent.infrastructure.browser.snapshot import BrowserSnapshot
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    infer_search_provider as _infer_search_provider,
)
from personagent.infrastructure.browser.url_utils import (
    is_local_lightpanda_endpoint as _is_local_lightpanda_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    is_retryable_raw_cdp_error as _is_retryable_raw_cdp_error,
)
from personagent.infrastructure.browser.url_utils import (
    is_target_already_loaded_error as _is_target_already_loaded_error,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)
from personagent.infrastructure.browser.view_actions import BrowserViewActions

logger = structlog.get_logger(__name__)

Connector = Callable[[str], Awaitable[Any]]

_DEFAULT_SEARCH_BASE_URL = "https://search.yahoo.com/search"
_MAX_CACHED_SEARCHES_PER_CONVERSATION = 8
_MAX_OPENED_PAGES_PER_CONVERSATION = 32
_MAX_LIVE_PAGES_PER_SESSION = max(
    1,
    int(os.getenv("PERSONAGENT_BROWSER_MAX_LIVE_PAGES_PER_SESSION", "4")),
)
_STYLESHEET_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_TTL_SECONDS", "900"))
_MAX_STYLESHEET_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_ENTRIES", "256"))
_MAX_STYLESHEET_HREFS_PER_PAGE = int(os.getenv("PERSONAGENT_BROWSER_CSS_MAX_HREFS", "32"))
_STYLESHEET_CACHE_DIR = Path(
    os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_DIR", str(Path.home() / ".cache/personagent/browser-css"))
)
_RENDER_SNAPSHOT_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_TTL_SECONDS", "180"))
_MAX_RENDER_SNAPSHOT_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_ENTRIES", "16"))
_RAW_CDP_RETRY_DELAYS = (0.0, 0.5, 1.5, 3.0, 5.0)
_MAX_BROWSER_SCRIPT_CHARS = 10_000
_MAX_BROWSER_SCRIPT_RESULT_CHARS = 12_000
_BROWSER_SCRIPT_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}


class LightPandaBrowserWorker:
    """Keeps one CDP browser connection and per-conversation pages."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_ms: int = 30_000,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
        session_ttl_seconds: int = 600,
        max_sessions: int = 12,
        artifact_root: str | Path | None = None,
        render_cache_entries: int = _MAX_RENDER_SNAPSHOT_CACHE_ENTRIES,
        render_cache_ttl_seconds: float = _RENDER_SNAPSHOT_CACHE_TTL_SECONDS,
        css_cache_entries: int = _MAX_STYLESHEET_CACHE_ENTRIES,
        css_cache_ttl_seconds: float = _STYLESHEET_CACHE_TTL_SECONDS,
        auto_start_lightpanda: bool = True,
        connector: Connector | None = None,
    ) -> None:
        self.enabled = enabled
        self.cdp_url = cdp_url
        self.timeout_ms = max(1, int(timeout_ms))
        self.search_base_url = search_base_url or _DEFAULT_SEARCH_BASE_URL
        self.search_provider = _infer_search_provider(self.search_base_url)
        self.session_ttl_seconds = max(1, int(session_ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self.artifact_root = Path(artifact_root).expanduser() if artifact_root else None
        self._snapshot_cache = SnapshotCache(
            max_entries=max(1, int(render_cache_entries)),
            ttl_seconds=max(1.0, float(render_cache_ttl_seconds)),
        )
        self._max_stylesheet_cache_entries = max(1, int(css_cache_entries))
        self._stylesheet_cache_ttl_seconds = max(1.0, float(css_cache_ttl_seconds))
        self._stylesheet_disk_cache = StylesheetDiskCache(
            cache_dir=_STYLESHEET_CACHE_DIR,
            max_entries=self._max_stylesheet_cache_entries,
        )
        self.auto_start_lightpanda = auto_start_lightpanda
        self._connector = connector
        self.actions = BrowserActions(self)
        self.lifecycle = BrowserPageLifecycle(self)
        self.snapshot = BrowserSnapshot(self)
        self.search_module = BrowserSearch(self)
        self.view_actions = BrowserViewActions(self)
        self.content_module = BrowserContent(self)
        self.console = BrowserConsole(self)
        self.opened_pages = OpenedPageTracker(self)
        self.search_result_cache = SearchResultCache(self)
        self.element_helpers = ElementHelpers(self)
        self._lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._container_start_lock = asyncio.Lock()
        self._container_start_attempted = False
        self._playwright: Any | None = None
        self._sessions: dict[str, _BrowserSession] = {}
        self._search_cache: dict[str, list[BrowserSearchSnapshot]] = {}
        self._current_url_cache: dict[str, str] = {}
        self._last_open_cache: dict[str, BrowserOpenedPage] = {}
        self._opened_pages_cache: dict[str, list[BrowserOpenedPage]] = {}
        self._element_map_cache: dict[str, list[dict[str, Any]]] = {}
        self._stylesheet_cache: dict[str, tuple[float, str]] = {}
        self._console_cache: dict[str, dict[str, list[BrowserConsoleEntry]]] = {}
        self._console_sequence = 0
        self._console_listener_keys: set[tuple[str, str, int]] = set()
        self._cooperation_event_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._cooperation_listener_keys: set[tuple[str, str, int]] = set()

    async def warmup(self) -> bool:
        """Best-effort startup connection. Failures are logged, not raised."""

        try:
            browser = await self._connect_browser()
        except BrowserError as exc:
            logger.warning("lightpanda_warmup_failed", error=str(exc))
            return False
        await self._release_browser(browser)
        return True

    async def close(self) -> None:
        """Close pages, contexts, browser and Playwright runtime."""

        async with self._lock:
            await self._close_sessions()
            if self._playwright is not None:
                await self._best_effort_resource_call(
                    "playwright_stop",
                    self._playwright.stop,
                )
                self._playwright = None
            self._search_cache.clear()
            self._current_url_cache.clear()
            self._last_open_cache.clear()
            self._opened_pages_cache.clear()
            self._stylesheet_cache.clear()
            self._snapshot_cache.clear()
            self._console_cache.clear()
            self._console_listener_keys.clear()
            self._cooperation_event_cache.clear()
            self._cooperation_listener_keys.clear()

    @property
    def search_provider_label(self) -> str:
        return self.search_module.search_provider_label

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        return await self.search_module.search(**kwargs)

    async def extract_content(self, **kwargs: Any) -> dict[str, Any]:
        return await self.content_module.extract_content(**kwargs)

    async def get_html(self, **kwargs: Any) -> dict[str, Any]:
        return await self.content_module.get_html(**kwargs)

    async def _lightpanda_markdown(self, session: Any) -> str:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._lightpanda_markdown_url(url)

    async def _lightpanda_markdown_url(self, url: str) -> str:
        url = _clean_browser_url(url)
        if not url or url == "about:blank":
            return ""
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="LP.getMarkdown",
                ),
                timeout=min(self.timeout_ms / 1000, 15),
            )
            markdown = self.content_module._extract_markdown_payload(payload)
            if markdown:
                return markdown
        except TimeoutError as exc:
            logger.warning("lightpanda_markdown_raw_timeout", error=str(exc), url=url)
            return ""
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        return ""

    async def view_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.snapshot.view_snapshot(**kwargs)

    async def view_navigate(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_navigate(**kwargs)

    async def view_history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_history(**kwargs)

    async def view_reload(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_reload(**kwargs)

    async def view_click(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_click(**kwargs)

    async def view_key(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_key(**kwargs)

    async def view_scroll(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_scroll(**kwargs)

    async def view_act(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_act(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserActions (Slice 3)
    # ------------------------------------------------------------------

    async def click(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.click(**kwargs)

    async def type_input(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.type_input(**kwargs)

    async def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.screenshot(**kwargs)

    async def read_console(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.read_console(**kwargs)

    async def script(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.script(**kwargs)

    async def scroll(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.scroll(**kwargs)

    async def wait(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.wait(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserPageLifecycle (Slice 4)
    # ------------------------------------------------------------------

    async def open(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.open(**kwargs)

    async def list_tabs(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.list_tabs(**kwargs)

    async def close_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.close_tab(**kwargs)

    async def reload(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.reload(**kwargs)

    async def history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.history(**kwargs)

    async def switch_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.switch_tab(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserSnapshot (Slice 5)
    # ------------------------------------------------------------------

    async def _browser_view_snapshot(
        self,
        browser_id: str,
        session: Any,
        *,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    def _enrich_browser_element_map(
        self,
        raw_map: list[dict[str, Any]],
        *,
        browser_id: str,
        tab_id: str,
    ) -> list[dict[str, Any]]:
        return self.snapshot.enrich_browser_element_map(raw_map, browser_id=browser_id, tab_id=tab_id)

    async def _browser_element_map(self, page: Any) -> list[dict[str, Any]]:
        return await self.snapshot.browser_element_map(page)

    async def _panel_session_tabs(
        self,
        *,
        max_tabs: int,
        exclude_conversation_id: str,
    ) -> list[dict[str, Any]]:
        return await self.snapshot.panel_session_tabs(
            max_tabs=max_tabs,
            exclude_conversation_id=exclude_conversation_id,
        )

    async def _html_with_embedded_stylesheet_fallbacks(
        self,
        html: str,
        current_url: str,
    ) -> tuple[str, dict[str, int]]:
        return await self.snapshot.html_with_embedded_stylesheet_fallbacks(html, current_url)

    async def _fetch_stylesheet_css(self, client: Any, href: str) -> tuple[str, bool]:
        return await self.snapshot.fetch_stylesheet_css(client, href)

    @staticmethod
    def _stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
        return BrowserSnapshot.stylesheet_hrefs(html, current_url, max_hrefs=max_hrefs)

    @staticmethod
    def _html_attrs(tag: str) -> dict[str, str]:
        return BrowserSnapshot.html_attrs(tag)

    @staticmethod
    def _rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
        return BrowserSnapshot.rewrite_css_urls(css_text, stylesheet_url)

    @staticmethod
    def _css_fidelity(*, html: str, render_mode: str, embedded_stylesheet_count: int = 0) -> str:
        return BrowserSnapshot.css_fidelity(
            html=html, render_mode=render_mode, embedded_stylesheet_count=embedded_stylesheet_count
        )

    def search_url(self, query: str, *, max_results: int | None = None) -> str:
        return self.search_module.search_url(query, max_results=max_results)

    async def _wait_for_page_visual_ready(self, page: Any) -> dict[str, Any]:
        await self._wait_for_page_load_complete(page)
        metrics: dict[str, Any] = {
            "style_ready": True,
            "stylesheet_count": 0,
            "stylesheet_loaded_count": 0,
            "fonts_ready": True,
        }
        with suppress(Exception):
            value = await asyncio.wait_for(
                self._evaluate_page(page, _STYLE_READY_SNAPSHOT_SCRIPT),
                timeout=min(max(self.timeout_ms / 1000, 1.0), 5.0),
            )
            if isinstance(value, Mapping):
                metrics.update(
                    {
                        "style_ready": bool(value.get("style_ready", metrics["style_ready"])),
                        "stylesheet_count": int(value.get("stylesheet_count") or 0),
                        "stylesheet_loaded_count": int(value.get("stylesheet_loaded_count") or 0),
                        "fonts_ready": bool(value.get("fonts_ready", metrics["fonts_ready"])),
                    }
                )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        return metrics

    async def _wait_for_page_load_complete(self, page: Any, *, timeout_ms: int | None = None) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state("load", timeout=min(timeout_ms or self.timeout_ms, 5_000))

    def _element_selector(self, browser_id: str, node_id: str) -> str:
        return self.element_helpers.element_selector(browser_id, node_id)

    def _element_target(self, browser_id: str, node_id: str) -> dict[str, Any]:
        return self.element_helpers.element_target(browser_id, node_id)

    @staticmethod
    def _browser_action_target_payload(
        target: Mapping[str, Any],
        *,
        fallback_node_id: str = "",
    ) -> dict[str, Any]:
        return ElementHelpers.browser_action_target_payload(target, fallback_node_id=fallback_node_id)

    async def _action_context_for_element(self, page: Any, target: dict[str, Any]) -> Any:
        return await self.element_helpers.action_context_for_element(page, target)

    async def _page_frames(self, page: Any) -> list[Any]:
        return await self.element_helpers.page_frames(page)

    def _main_frame(self, page: Any) -> Any:
        return self.element_helpers.main_frame(page)

    def _frame_id(self, frame: Any, index: int) -> str:
        return self.element_helpers.frame_id(frame, index)

    async def _frame_viewport_offset(self, frame: Any) -> tuple[float, float]:
        return await self.element_helpers.frame_viewport_offset(frame)

    async def _upload_files(self, page: Any, selector: str, files: list[str]) -> dict[str, Any]:
        return await self.element_helpers.upload_files(page, selector, files)

    async def _drag_between_elements(
        self,
        page: Any,
        selector: str,
        *,
        target_selector: str,
        x: float | None,
        y: float | None,
    ) -> dict[str, Any]:
        return await self.element_helpers.drag_between_elements(
            page, selector, target_selector=target_selector, x=x, y=y,
        )

    async def _set_page_viewport(self, page: Any, width: int, height: int) -> None:
        await self.element_helpers.set_page_viewport(page, width, height)

    async def _safe_user_agent(self, page: Any) -> str:
        return await self.element_helpers.safe_user_agent(page)

    async def _safe_html(self, page: Any) -> str:
        return await self.element_helpers.safe_html(page)

    async def _safe_scroll_state(self, page: Any) -> dict[str, int]:
        return await self.element_helpers.safe_scroll_state(page)

    async def _get_session(self, conversation_id: str) -> _BrowserSession:
        async with self._sessions_lock:
            await self._cleanup_sessions()
            session = self._sessions.get(conversation_id)
            if session is not None:
                try:
                    browser_connected = True
                    is_connected = getattr(session.browser, "is_connected", None)
                    if callable(is_connected):
                        browser_connected = bool(is_connected())
                    if browser_connected and self._session_has_open_page(session):
                        session.page = self._preferred_session_page(session)
                        cached_results = self._latest_cached_search_results(conversation_id)
                        if cached_results:
                            session.search_results = cached_results
                        else:
                            session.search_results = []
                        session.current_url = session.current_url or self._current_url_cache.get(
                            conversation_id
                        )
                        last_open = self._last_open_cache.get(conversation_id)
                        if last_open is not None:
                            session.last_open_url = session.last_open_url or last_open.final_url
                            session.last_open_page_id = (
                                session.last_open_page_id or last_open.page_id
                            )
                        session.touch()
                        return session
                except Exception:
                    await self._close_session(conversation_id, session)
                    session = None
                if session is not None:
                    await self._close_session(conversation_id, session)

            browser = await self._connect_browser()
            try:
                context = await browser.new_context()
                new_pages_supported = True
                try:
                    page = await context.new_page()
                except Exception as exc:
                    if not _is_target_already_loaded_error(exc):
                        raise
                    page = self._first_open_context_page(context)
                    if page is None:
                        raise
                    new_pages_supported = False
                page.set_default_timeout(self.timeout_ms)
                last_open = self._last_open_cache.get(conversation_id)
                session = _BrowserSession(
                    browser=browser,
                    context=context,
                    page=page,
                    search_results=self._latest_cached_search_results(conversation_id),
                    current_url=self._current_url_cache.get(conversation_id),
                    last_open_url=last_open.final_url if last_open is not None else None,
                    last_open_page_id=last_open.page_id if last_open is not None else None,
                    current_page_id=last_open.page_id if last_open is not None else None,
                    new_pages_supported=new_pages_supported,
                )
                self._sessions[conversation_id] = session
                await self._enforce_session_limit()
                return session
            except Exception as exc:
                await self._release_browser(browser)
                raise BrowserUnavailableError(
                    f"Could not create a LightPanda browser session: {exc}"
                ) from exc

    async def _ensure_browser(self) -> Any:
        """Open one CDP browser connection.

        LightPanda currently does not behave like Chromium when many contexts are
        created on the same Playwright CDP connection. The worker therefore keeps
        the singleton at the worker level, but each conversation session owns its
        own CDP connection.
        """

        return await self._connect_browser()

    def _cached_usable_session(self, conversation_id: str) -> _BrowserSession | None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return None
        try:
            browser_connected = True
            is_connected = getattr(session.browser, "is_connected", None)
            if callable(is_connected):
                browser_connected = bool(is_connected())
            if browser_connected and self._session_has_open_page(session):
                session.page = self._preferred_session_page(session)
                return session
        except Exception:
            pass
        self._sessions.pop(conversation_id, None)
        return None

    def _session_has_open_page(self, session: _BrowserSession) -> bool:
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return True
        return False

    def _preferred_session_page(self, session: _BrowserSession) -> Any:
        if session.current_page_id:
            page = session.pages.get(session.current_page_id)
            if page is not None:
                with suppress(Exception):
                    if not page.is_closed():
                        return page
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return session.page

    def _session_pages(self, session: _BrowserSession) -> list[Any]:
        pages: list[Any] = []
        seen: set[int] = set()
        for page in (session.page, *session.pages.values()):
            marker = id(page)
            if marker in seen:
                continue
            seen.add(marker)
            pages.append(page)
        return pages

    async def _cleanup_live_pages(
        self,
        conversation_id: str,
        session: _BrowserSession,
        *,
        keep_page_id: str | None = None,
        close_read_pages: bool = False,
    ) -> None:
        live_entries = self._live_page_entries(session)
        if not live_entries:
            return
        keep_ids = {
            str(value or "").strip()
            for value in (keep_page_id, session.current_page_id, session.last_open_page_id)
            if str(value or "").strip()
        }
        candidates: list[tuple[int, float, set[str], Any]] = []
        for page_ids, page in live_entries:
            if keep_ids.intersection(page_ids):
                continue
            opened_pages = [
                opened_page
                for page_id in page_ids
                if (opened_page := self._opened_page(conversation_id, page_id)) is not None
            ]
            read = any(opened_page.extraction_count > 0 for opened_page in opened_pages)
            if close_read_pages and read:
                priority = 0
            elif len(live_entries) > _MAX_LIVE_PAGES_PER_SESSION:
                priority = 1 if read else 2
            else:
                continue
            opened_at = min((opened_page.opened_at for opened_page in opened_pages), default=time.monotonic())
            candidates.append((priority, opened_at, page_ids, page))
        live_count = len(live_entries)
        for _priority, _opened_at, page_ids, page in sorted(candidates, key=lambda item: (item[0], item[1])):
            if live_count <= _MAX_LIVE_PAGES_PER_SESSION and not close_read_pages:
                break
            await self._best_effort_resource_call("browser_live_page_close", page.close)
            for page_id in list(page_ids):
                session.pages.pop(page_id, None)
            live_count -= 1
        if session.current_page_id and session.current_page_id not in session.pages:
            session.current_page_id = keep_page_id or session.last_open_page_id
        if session.current_page_id and session.current_page_id in session.pages:
            session.page = session.pages[session.current_page_id]
        elif self._session_has_open_page(session):
            session.page = self._preferred_session_page(session)

    def _live_page_entries(self, session: _BrowserSession) -> list[tuple[set[str], Any]]:
        by_page_object: dict[int, tuple[set[str], Any]] = {}
        for page_id, page in session.pages.items():
            if not self._page_is_open(page):
                continue
            marker = id(page)
            if marker not in by_page_object:
                by_page_object[marker] = (set(), page)
            by_page_object[marker][0].add(page_id)
        return list(by_page_object.values())

    def _ensure_session_page_alias(
        self,
        conversation_id: str,
        session: _BrowserSession,
        *,
        page: Any | None = None,
        page_id: str | None = None,
    ) -> str:
        target_page_id = str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or conversation_id
            or ""
        ).strip()
        if not target_page_id:
            target_page_id = conversation_id
        target_page = page or self._preferred_session_page(session)
        if target_page is not None and self._page_is_open(target_page):
            session.pages.setdefault(target_page_id, target_page)
        session.current_page_id = session.current_page_id or target_page_id
        session.last_open_page_id = session.last_open_page_id or target_page_id
        return target_page_id

    def _is_session_page_alias(
        self,
        conversation_id: str,
        session: _BrowserSession | None,
        page_id: str | None,
    ) -> bool:
        target_page_id = str(page_id or "").strip()
        if not target_page_id or session is None:
            return False
        if target_page_id == conversation_id:
            return True
        return target_page_id in {
            str(session.current_page_id or "").strip(),
            str(session.last_open_page_id or "").strip(),
        }

    async def _resolve_live_page(
        self,
        conversation_id: str,
        *,
        page_id: str | None = None,
        activate: bool = True,
    ) -> tuple[_BrowserSession, Any, str]:
        session = await self._get_session(conversation_id)
        target_page_id = str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or (self._last_open_cache.get(conversation_id).page_id if self._last_open_cache.get(conversation_id) else "")
            or ""
        ).strip()
        page = session.pages.get(target_page_id) if target_page_id else None
        if page is not None and not self._page_is_open(page):
            session.pages.pop(target_page_id, None)
            page = None
        if page is None and target_page_id:
            if self._is_session_page_alias(conversation_id, session, target_page_id):
                page = self._preferred_session_page(session)
                if not self._page_is_open(page):
                    raise BrowserError(
                        f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                    )
                session.pages[target_page_id] = page
            else:
                opened_page = self._opened_page(conversation_id, target_page_id)
                if opened_page is None:
                    raise BrowserError(
                        f"No opened browser page with page_id {target_page_id}. Run BrowserOpen first."
                    )
                page = self._preferred_session_page(session)
                if not self._page_is_open(page):
                    raise BrowserError(
                        f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                    )
                page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
                target_url = opened_page.final_url or opened_page.url
                if target_url.startswith(("http://", "https://")) and not _urls_equivalent(page_url, target_url):
                    await self._goto_page(page, target_url, allow_partial=True)
                session.pages[target_page_id] = page
        if page is None:
            page = self._preferred_session_page(session)
            if not self._page_is_open(page):
                raise BrowserError("No live browser page is available. Run BrowserOpen first.")
            target_page_id = target_page_id or session.current_page_id or session.last_open_page_id or conversation_id
            session.pages.setdefault(target_page_id, page)
        if activate:
            session.page = page
            session.current_page_id = target_page_id
            session.last_open_page_id = target_page_id
            current_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if current_url:
                session.current_url = current_url
                self._remember_current_url(conversation_id, current_url)
            session.touch()
        self._attach_page_console_listeners(conversation_id, target_page_id, page)
        return session, page, target_page_id

    def _page_is_open(self, page: Any) -> bool:
        with suppress(Exception):
            is_closed = getattr(page, "is_closed", None)
            if callable(is_closed):
                return not bool(is_closed())
        return True

    def _attach_page_console_listeners(self, conversation_id: str, page_id: str, page: Any) -> None:
        return self.console.attach_page_console_listeners(conversation_id, page_id, page)

    def _console_message_attr(self, message: Any, name: str) -> Any:
        return BrowserConsole.console_message_attr(message, name)

    def _record_console_entry(
        self,
        conversation_id: str,
        page_id: str,
        *,
        level: str,
        text: str,
        source: str,
        url: str = "",
    ) -> None:
        return self.console.record_console_entry(
            conversation_id, page_id, level=level, text=text, source=source, url=url,
        )

    async def _page_runtime(self, page: Any) -> str:
        return "lightpanda" if await self._is_lightpanda_page(page) else "chrome_cdp"

    async def _is_lightpanda_page(self, page: Any) -> bool:
        user_agent = await self._safe_user_agent(page)
        return user_agent.lower().startswith("lightpanda/")

    def _bounded_script_result(self, value: Any) -> tuple[str, Any | None, bool]:
        try:
            result_text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            result_text = str(value)
        truncated = len(result_text) > _MAX_BROWSER_SCRIPT_RESULT_CHARS
        if truncated:
            result_text = result_text[:_MAX_BROWSER_SCRIPT_RESULT_CHARS].rstrip()
        result: Any | None
        if truncated:
            result = None
        else:
            try:
                result = json.loads(result_text)
            except Exception:
                result = result_text
        return result_text, result, truncated

    async def _cdp_command_for_page(
        self,
        page: Any,
        *,
        url: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        context = getattr(page, "context", None)
        if callable(context):
            with suppress(Exception):
                context = context()
        new_cdp_session = getattr(context, "new_cdp_session", None)
        if callable(new_cdp_session):
            cdp_session = await new_cdp_session(page)
            try:
                return await cdp_session.send(method, params or {})
            finally:
                detach = getattr(cdp_session, "detach", None)
                if callable(detach):
                    with suppress(Exception):
                        result = detach()
                        if inspect.isawaitable(result):
                            await result
        return await self._lightpanda_raw_cdp_command(
            url=url or "about:blank",
            method=method,
            params=params or {},
        )

    def _first_open_context_page(self, context: Any) -> Any | None:
        raw_pages = getattr(context, "pages", None)
        if not raw_pages:
            return None
        for page in list(raw_pages):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return None

    async def _connect_browser(self) -> Any:
        if not self.enabled:
            raise BrowserUnavailableError("LightPanda browser tools are disabled.")
        last_error: Exception | None = None
        for attempt in range(3):
            endpoint = await self._resolve_endpoint()
            try:
                if self._connector is not None:
                    return await self._connector(endpoint)
                return await self._connect_with_playwright(endpoint)
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        if await self._try_start_lightpanda_container():
            for attempt in range(4):
                endpoint = await self._resolve_endpoint()
                try:
                    if self._connector is not None:
                        return await self._connector(endpoint)
                    return await self._connect_with_playwright(endpoint)
                except Exception as exc:
                    last_error = exc
                    if attempt == 3:
                        break
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise BrowserUnavailableError(
            "Browser CDP endpoint is unavailable. Start LightPanda with "
            "`docker compose up -d lightpanda` or start Chrome/Chromium with "
            "`--remote-debugging-port=9222`, then verify /json/version."
        ) from last_error

    async def _try_start_lightpanda_container(self) -> bool:
        if (
            not self.auto_start_lightpanda
            or self._connector is not None
            or not _is_local_lightpanda_endpoint(self.cdp_url)
        ):
            return False
        async with self._container_start_lock:
            if self._container_start_attempted:
                return False
            self._container_start_attempted = True
            repo_root = Path(__file__).resolve().parents[5]
            compose_file = repo_root / "docker-compose.yml"
            if not compose_file.exists():
                return False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "compose",
                    "up",
                    "-d",
                    "lightpanda",
                    cwd=repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (OSError, TimeoutError) as exc:
                logger.warning("lightpanda_container_autostart_failed", error=str(exc))
                return False
            output = (
                stdout_data.decode("utf-8", errors="replace")
                + stderr_data.decode("utf-8", errors="replace")
            ).strip()
            if proc.returncode != 0:
                logger.warning(
                    "lightpanda_container_autostart_failed",
                    returncode=proc.returncode,
                    output=output,
                )
                return False
            logger.info("lightpanda_container_autostarted", output=output)
            return True

    async def _connect_with_playwright(self, endpoint: str) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `playwright` is required for LightPanda browser tools."
            ) from exc

        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            playwright = self._playwright
        return await playwright.chromium.connect_over_cdp(
            endpoint,
            timeout=self.timeout_ms,
        )

    async def _new_session_page(self, session: _BrowserSession) -> Any | None:
        if not session.new_pages_supported:
            return None
        async with session.new_page_lock:
            if not session.new_pages_supported:
                return None
            try:
                page = await session.context.new_page()
            except Exception as exc:
                if _is_target_already_loaded_error(exc):
                    session.new_pages_supported = False
                    if not session.new_page_unavailable_logged:
                        logger.debug("lightpanda_new_page_unavailable", error=str(exc))
                        session.new_page_unavailable_logged = True
                    return None
                raise
        with suppress(Exception):
            page.set_default_timeout(self.timeout_ms)
        return page

    async def _resolve_endpoint(self) -> str:
        version_payload = None
        if self.cdp_url.strip().startswith(("http://", "https://")):
            with suppress(Exception):
                async with httpx.AsyncClient(timeout=self.timeout_ms / 1000) as client:
                    response = await client.get(f"{self.cdp_url.rstrip('/')}/json/version")
                    response.raise_for_status()
                    version_payload = response.json()
        return normalize_lightpanda_cdp_endpoint(self.cdp_url, version_payload)

    async def _goto(
        self,
        conversation_id: str,
        session: _BrowserSession,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        try:
            await self._goto_page(session.page, url, allow_partial=allow_partial, wait_for_styles=wait_for_styles)
        except Exception:
            await self._close_session(conversation_id, session)
            raise

    async def _goto_page(
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
                timeout=self.timeout_ms,
            )
            if wait_for_styles:
                await self._wait_for_page_visual_ready(page)
            await self._install_console_capture(page)
        except Exception as exc:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if allow_partial and page_url.startswith(("http://", "https://")):
                logger.warning(
                    "lightpanda_navigation_partial",
                    url=clean_url,
                    page_url=page_url,
                    error=str(exc),
                )
                with suppress(Exception):
                    await self._install_console_capture(page)
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

    async def _evaluate_page(
        self,
        page: Any,
        script: str,
        arg: Any | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if arg is None:
                    return await page.evaluate(script)
                return await page.evaluate(script, arg)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "Execution context was destroyed" not in message:
                    raise
                if attempt == 2:
                    break
                with suppress(Exception):
                    await page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(self.timeout_ms, 5_000),
                    )
                with suppress(Exception):
                    await page.wait_for_timeout(250)
        if last_error is not None:
            raise last_error
        return None

    async def _install_console_capture(self, page: Any) -> None:
        await self.console.install_console_capture(page)

    async def _install_cooperation_capture(self, page: Any, browser_id: str, page_id: str) -> None:
        await self.console.install_cooperation_capture(page, browser_id, page_id)

    async def _drain_page_console_entries(
        self,
        page: Any,
        conversation_id: str,
        page_id: str,
    ) -> None:
        await self.console.drain_page_console_entries(page, conversation_id, page_id)

    async def _drain_cooperation_events(
        self,
        page: Any,
        browser_id: str,
        page_id: str,
    ) -> list[dict[str, Any]]:
        return await self.console.drain_cooperation_events(page, browser_id, page_id)

    def _record_cooperation_event(self, browser_id: str, page_id: str, event: Any) -> None:
        self.console.record_cooperation_event(browser_id, page_id, event)

    async def _raw_runtime_evaluate_value(
        self,
        url: str,
        expression: str,
        *,
        label: str,
        timeout: float,
    ) -> Any:
        if not url or url == "about:blank":
            return None
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="Runtime.evaluate",
                    params={
                        "expression": expression,
                        "returnByValue": True,
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_timeout", label=label, error=str(exc))
            return None
        except Exception as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_failed", label=label, error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return result.get("value")

    async def _lightpanda_raw_cdp_command(
        self,
        *,
        url: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            import websockets
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `websockets` is required for LightPanda native CDP commands."
            ) from exc

        timeout_seconds = self.timeout_ms / 1000
        last_error: Exception | None = None
        for attempt, delay in enumerate(_RAW_CDP_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                endpoint = await self._resolve_endpoint()
                async with websockets.connect(
                    endpoint,
                    open_timeout=timeout_seconds,
                    close_timeout=min(timeout_seconds, 5),
                    max_size=8 * 1024 * 1024,
                ) as websocket:
                    client = _RawCdpClient(websocket)
                    created = await client.send("Target.createTarget", {"url": "about:blank"})
                    target_id = str(created.get("targetId") or "")
                    attached = await client.send(
                        "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True},
                    )
                    session_id = str(attached.get("sessionId") or "")
                    try:
                        with suppress(Exception):
                            await client.send("Page.enable", session_id=session_id)
                        await client.send("Page.navigate", {"url": url}, session_id=session_id)
                        with suppress(TimeoutError, asyncio.TimeoutError):
                            await client.wait_for_event(
                                "Page.domContentEventFired",
                                session_id=session_id,
                                timeout=timeout_seconds,
                            )
                        await asyncio.sleep(0.25)
                        return await client.send(method, params or {}, session_id=session_id)
                    finally:
                        if target_id:
                            with suppress(Exception):
                                await client.send("Target.closeTarget", {"targetId": target_id})
            except Exception as exc:
                last_error = exc
                if attempt == len(_RAW_CDP_RETRY_DELAYS) - 1 or not _is_retryable_raw_cdp_error(
                    exc
                ):
                    raise
                logger.debug(
                    "lightpanda_raw_cdp_retry",
                    attempt=attempt + 1,
                    method=method,
                    url=url,
                    error=str(exc),
                )
        if last_error is not None:
            raise last_error
        raise BrowserUnavailableError("LightPanda raw CDP command failed.")

    async def _safe_title(self, page: Any) -> str:
        try:
            title = await asyncio.wait_for(
                page.title(),
                timeout=min(self.timeout_ms / 1000, 3),
            )
            return str(title or "").strip()
        except TimeoutError as exc:
            logger.debug("lightpanda_title_timeout", error=str(exc))
            return ""
        except Exception:
            return ""

    async def _safe_title_for_url(self, url: str) -> str:
        value = await self._raw_runtime_evaluate_value(
            url,
            "document.title || ''",
            label="title",
            timeout=min(self.timeout_ms / 1000, 5),
        )
        return str(value or "").strip() if isinstance(value, str) else ""

    async def _raise_if_google_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "sorry/index" not in page_url and "google." not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_google_surface = "google." in page_url or "google" in title
        if "sorry/index" not in page_url and not is_google_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "our systems have detected",
            "before you continue",
            "consent.google",
            "enable javascript on your web browser",
        )
        if "sorry/index" in page_url or (
            is_google_surface and any(marker in sample or marker in title for marker in markers)
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Google blocked this browser session with consent, CAPTCHA, or unusual-traffic checks. "
                "This is a Google/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="google",
                reason="captcha_or_unusual_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_bing_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "bing.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_bing_surface = "bing.com" in page_url or "bing" in title
        if not is_bing_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
            "solve this puzzle",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Bing blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="bing",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_yahoo_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "search.yahoo.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_yahoo_surface = "search.yahoo.com" in page_url or "yahoo search" in title
        if not is_yahoo_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Yahoo blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="yahoo",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_search_blocked(self, page: Any) -> None:
        await self._raise_if_google_blocked(page)
        await self._raise_if_bing_blocked(page)
        await self._raise_if_yahoo_blocked(page)

    def _cache_search_results(
        self,
        *,
        conversation_id: str,
        query: str,
        search_url: str,
        results: list[BrowserSearchResult],
    ) -> BrowserSearchSnapshot:
        return self.search_result_cache.cache_search_results(
            conversation_id=conversation_id, query=query,
            search_url=search_url, results=results,
        )

    def _latest_cached_search_results(self, conversation_id: str) -> list[BrowserSearchResult]:
        return self.search_result_cache.latest_cached_search_results(conversation_id)

    def _copy_search_results(
        self,
        results: list[BrowserSearchResult],
    ) -> list[BrowserSearchResult]:
        return SearchResultCache.copy_search_results(results)

    def _remember_current_url(self, conversation_id: str, url: str | None) -> None:
        self.search_result_cache.remember_current_url(conversation_id, url)

    def _cache_opened_page(
        self,
        *,
        conversation_id: str,
        url: str,
        final_url: str,
        title: str,
        source_search_id: str | None,
        opener_tool_call_id: str | None,
    ) -> tuple[BrowserOpenedPage, bool]:
        return self.opened_pages.cache_opened_page(
            conversation_id=conversation_id, url=url, final_url=final_url,
            title=title, source_search_id=source_search_id,
            opener_tool_call_id=opener_tool_call_id,
        )

    def _browser_open_response(
        self,
        *,
        conversation_id: str,
        opened_page: BrowserOpenedPage,
        requested_url: str,
        title: str,
        search_id: str | None,
        reused_existing_page: bool,
    ) -> dict[str, Any]:
        return self.opened_pages.browser_open_response(
            conversation_id=conversation_id, opened_page=opened_page,
            requested_url=requested_url, title=title, search_id=search_id,
            reused_existing_page=reused_existing_page,
        )

    def _opened_page_read_status(self, opened_page: BrowserOpenedPage) -> str:
        return OpenedPageTracker.opened_page_read_status(opened_page)

    def _opened_page_tab(
        self,
        page: BrowserOpenedPage,
        *,
        index: int,
        current_url: str | None,
        last_open_page_id: str | None,
    ) -> dict[str, Any]:
        return self.opened_pages.opened_page_tab(
            page, index=index, current_url=current_url,
            last_open_page_id=last_open_page_id,
        )

    def _opened_page(
        self,
        conversation_id: str,
        page_id: str,
    ) -> BrowserOpenedPage | None:
        return self.opened_pages.opened_page(conversation_id, page_id)

    def _opened_page_by_url(
        self,
        conversation_id: str,
        url: str,
    ) -> BrowserOpenedPage | None:
        return self.opened_pages.opened_page_by_url(conversation_id, url)

    def _target_title(self, conversation_id: str, page_id: str | None) -> str:
        return self.opened_pages.target_title(conversation_id, page_id)

    def _resolve_content_target(
        self,
        conversation_id: str,
        session: _BrowserSession | None,
        *,
        url: str | None = None,
        page_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        if url and page_id:
            raise BrowserError("Use either url or page_id, not both.")
        if page_id:
            if session is not None and self._is_session_page_alias(conversation_id, session, page_id):
                page = self._preferred_session_page(session)
                target_url = _clean_browser_url(
                    str(
                        getattr(page, "url", "")
                        or session.current_url
                        or session.last_open_url
                        or self._current_url_cache.get(conversation_id)
                        or ""
                    )
                )
                if target_url:
                    session.pages.setdefault(page_id, page)
                    return target_url, page_id
            if session is not None:
                page = session.pages.get(page_id)
                if page is not None and self._page_is_open(page):
                    target_url = _clean_browser_url(
                        str(
                            getattr(page, "url", "")
                            or session.current_url
                            or session.last_open_url
                            or self._current_url_cache.get(conversation_id)
                            or ""
                        )
                    )
                    if target_url:
                        return target_url, page_id
            opened_page = self._opened_page(conversation_id, page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {page_id}. Run BrowserOpen first."
                )
            return opened_page.final_url, opened_page.page_id
        if url:
            return _clean_browser_url(url), None
        next_unextracted = self._next_unextracted_opened_page(conversation_id)
        if next_unextracted is not None:
            return next_unextracted.final_url, next_unextracted.page_id
        last_open = self._last_open_cache.get(conversation_id)
        if last_open is not None:
            return last_open.final_url, last_open.page_id
        if session is not None and session.last_open_url:
            return session.last_open_url, session.last_open_page_id
        current_url = _clean_browser_url(
            str(
                (session.current_url if session is not None else None)
                or self._current_url_cache.get(conversation_id)
                or ""
            )
        )
        if current_url.startswith(("http://", "https://")):
            return current_url, None
        if session is not None:
            page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                return page_url, None
        return None, None

    def _next_unextracted_opened_page(self, conversation_id: str) -> BrowserOpenedPage | None:
        return self.opened_pages.next_unextracted_opened_page(conversation_id)

    def _should_navigate_for_content(self, session: _BrowserSession, target_url: str) -> bool:
        target_url = _clean_browser_url(target_url)
        if not target_url.startswith(("http://", "https://")):
            return False
        page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return page_url != target_url

    def _result_url(
        self,
        conversation_id: str,
        session: _BrowserSession,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> tuple[str, str | None]:
        return self.search_result_cache.result_url(
            conversation_id, session, result_index, search_id=search_id,
        )

    def _result_title(
        self,
        conversation_id: str,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> str:
        return self.search_result_cache.result_title(
            conversation_id, result_index, search_id=search_id,
        )

    def _match_search_result_url(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str | None:
        return self.search_result_cache.match_search_result_url(
            conversation_id, url, search_id=search_id,
        )

    def _match_search_result_title(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str:
        return self.search_result_cache.match_search_result_title(
            conversation_id, url, search_id=search_id,
        )

    async def _cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._sessions.items()
            if now - session.updated_at > self.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self._close_session(conversation_id, self._sessions[conversation_id])
        self._cleanup_search_cache(now)

    def _cleanup_search_cache(self, now: float) -> None:
        self.search_result_cache.cleanup_search_cache(now)

    async def _enforce_session_limit(self) -> None:
        while len(self._sessions) > self.max_sessions:
            conversation_id, session = min(
                self._sessions.items(),
                key=lambda item: item[1].updated_at,
            )
            await self._close_session(conversation_id, session)

    async def _reset_browser(self) -> None:
        async with self._lock:
            await self._close_sessions()

    async def _close_sessions(self) -> None:
        for conversation_id, session in list(self._sessions.items()):
            await self._close_session(conversation_id, session)

    async def _close_session(self, conversation_id: str, session: _BrowserSession) -> None:
        self._sessions.pop(conversation_id, None)
        self._element_map_cache.pop(conversation_id, None)
        self._console_cache.pop(conversation_id, None)
        self._cooperation_event_cache.pop(conversation_id, None)
        get_browser_page_cache().clear_conversation(conversation_id)
        self._snapshot_cache.clear_conversation(conversation_id)
        for page in self._session_pages(session):
            await self._best_effort_resource_call("browser_page_close", page.close)
        await self._best_effort_resource_call("browser_context_close", session.context.close)
        await self._release_browser(session.browser)

    async def _release_browser(self, browser: Any) -> None:
        await self._best_effort_resource_call("browser_close", browser.close)

    async def _best_effort_resource_call(
        self,
        label: str,
        operation: Callable[[], Any],
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await asyncio.wait_for(
                    result,
                    timeout=min(max(self.timeout_ms / 1000, 0.5), 2),
                )
        except Exception as exc:
            logger.debug("lightpanda_resource_close_failed", label=label, error=str(exc))


from personagent.infrastructure.browser.cdp_client import CdpClient as _RawCdpClient  # noqa: E402
