"""Browser session lifecycle — create, reuse, resolve, cleanup."""

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    is_target_already_loaded_error as _is_target_already_loaded_error,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)

_MAX_LIVE_PAGES_PER_SESSION = 4


class BrowserSessionManager:
    """Owns per-conversation browser sessions and page resolution."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Session acquisition
    # ------------------------------------------------------------------

    async def get_session(self, conversation_id: str) -> _BrowserSession:
        async with self._w._sessions_lock:
            await self.cleanup_sessions()
            session = self._w._sessions.get(conversation_id)
            if session is not None:
                try:
                    browser_connected = True
                    is_connected = getattr(session.browser, "is_connected", None)
                    if callable(is_connected):
                        browser_connected = bool(is_connected())
                    if browser_connected and self.session_has_open_page(session):
                        session.page = self.preferred_session_page(session)
                        cached_results = self._w._latest_cached_search_results(conversation_id)
                        if cached_results:
                            session.search_results = cached_results
                        else:
                            session.search_results = []
                        session.current_url = session.current_url or self._w._current_url_cache.get(
                            conversation_id
                        )
                        last_open = self._w._last_open_cache.get(conversation_id)
                        if last_open is not None:
                            session.last_open_url = session.last_open_url or last_open.final_url
                            session.last_open_page_id = (
                                session.last_open_page_id or last_open.page_id
                            )
                        session.touch()
                        return session
                except Exception:
                    await self.close_session(conversation_id, session)
                    session = None
                if session is not None:
                    await self.close_session(conversation_id, session)

            browser = await self._w._connect_browser()
            try:
                context = await browser.new_context()
                new_pages_supported = True
                try:
                    page = await context.new_page()
                except Exception as exc:
                    if not _is_target_already_loaded_error(exc):
                        raise
                    page = self._w._first_open_context_page(context)
                    if page is None:
                        raise
                    new_pages_supported = False
                page.set_default_timeout(self._w.timeout_ms)
                last_open = self._w._last_open_cache.get(conversation_id)
                session = _BrowserSession(
                    browser=browser,
                    context=context,
                    page=page,
                    search_results=self._w._latest_cached_search_results(conversation_id),
                    current_url=self._w._current_url_cache.get(conversation_id),
                    last_open_url=last_open.final_url if last_open is not None else None,
                    last_open_page_id=last_open.page_id if last_open is not None else None,
                    current_page_id=last_open.page_id if last_open is not None else None,
                    new_pages_supported=new_pages_supported,
                )
                self._w._sessions[conversation_id] = session
                await self.enforce_session_limit()
                return session
            except Exception as exc:
                await self.release_browser(browser)
                raise BrowserUnavailableError(
                    f"Could not create a LightPanda browser session: {exc}"
                ) from exc

    def cached_usable_session(self, conversation_id: str) -> _BrowserSession | None:
        session = self._w._sessions.get(conversation_id)
        if session is None:
            return None
        try:
            browser_connected = True
            is_connected = getattr(session.browser, "is_connected", None)
            if callable(is_connected):
                browser_connected = bool(is_connected())
            if browser_connected and self.session_has_open_page(session):
                session.page = self.preferred_session_page(session)
                return session
        except Exception:
            pass
        self._w._sessions.pop(conversation_id, None)
        return None

    # ------------------------------------------------------------------
    # Session page queries
    # ------------------------------------------------------------------

    def session_has_open_page(self, session: _BrowserSession) -> bool:
        for page in self.session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return True
        return False

    def preferred_session_page(self, session: _BrowserSession) -> Any:
        if session.current_page_id:
            page = session.pages.get(session.current_page_id)
            if page is not None:
                with suppress(Exception):
                    if not page.is_closed():
                        return page
        for page in self.session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return session.page

    def session_pages(self, session: _BrowserSession) -> list[Any]:
        pages: list[Any] = []
        seen: set[int] = set()
        for page in (session.page, *session.pages.values()):
            marker = id(page)
            if marker in seen:
                continue
            seen.add(marker)
            pages.append(page)
        return pages

    def page_is_open(self, page: Any) -> bool:
        with suppress(Exception):
            is_closed = getattr(page, "is_closed", None)
            if callable(is_closed):
                return not bool(is_closed())
        return True

    # ------------------------------------------------------------------
    # Live page management
    # ------------------------------------------------------------------

    async def cleanup_live_pages(
        self,
        conversation_id: str,
        session: _BrowserSession,
        *,
        keep_page_id: str | None = None,
        close_read_pages: bool = False,
    ) -> None:
        live_entries = self.live_page_entries(session)
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
                if (opened_page := self._w._opened_page(conversation_id, page_id)) is not None
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
            await self.best_effort_resource_call("browser_live_page_close", page.close)
            for page_id in list(page_ids):
                session.pages.pop(page_id, None)
            live_count -= 1
        if session.current_page_id and session.current_page_id not in session.pages:
            session.current_page_id = keep_page_id or session.last_open_page_id
        if session.current_page_id and session.current_page_id in session.pages:
            session.page = session.pages[session.current_page_id]
        elif self.session_has_open_page(session):
            session.page = self.preferred_session_page(session)

    def live_page_entries(self, session: _BrowserSession) -> list[tuple[set[str], Any]]:
        by_page_object: dict[int, tuple[set[str], Any]] = {}
        for page_id, page in session.pages.items():
            if not self.page_is_open(page):
                continue
            marker = id(page)
            if marker not in by_page_object:
                by_page_object[marker] = (set(), page)
            by_page_object[marker][0].add(page_id)
        return list(by_page_object.values())

    # ------------------------------------------------------------------
    # Page aliases
    # ------------------------------------------------------------------

    def ensure_session_page_alias(
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
        target_page = page or self.preferred_session_page(session)
        if target_page is not None and self.page_is_open(target_page):
            session.pages.setdefault(target_page_id, target_page)
        session.current_page_id = session.current_page_id or target_page_id
        session.last_open_page_id = session.last_open_page_id or target_page_id
        return target_page_id

    def is_session_page_alias(
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

    # ------------------------------------------------------------------
    # Page resolution
    # ------------------------------------------------------------------

    async def resolve_live_page(
        self,
        conversation_id: str,
        *,
        page_id: str | None = None,
        activate: bool = True,
    ) -> tuple[_BrowserSession, Any, str]:
        session = await self.get_session(conversation_id)
        target_page_id = str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or (self._w._last_open_cache.get(conversation_id).page_id if self._w._last_open_cache.get(conversation_id) else "")
            or ""
        ).strip()
        page = session.pages.get(target_page_id) if target_page_id else None
        if page is not None and not self.page_is_open(page):
            session.pages.pop(target_page_id, None)
            page = None
        if page is None and target_page_id:
            if self.is_session_page_alias(conversation_id, session, target_page_id):
                page = self.preferred_session_page(session)
                if not self.page_is_open(page):
                    raise BrowserError(
                        f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                    )
                session.pages[target_page_id] = page
            else:
                opened_page = self._w._opened_page(conversation_id, target_page_id)
                if opened_page is None:
                    raise BrowserError(
                        f"No opened browser page with page_id {target_page_id}. Run BrowserOpen first."
                    )
                page = self.preferred_session_page(session)
                if not self.page_is_open(page):
                    raise BrowserError(
                        f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                    )
                page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
                target_url = opened_page.final_url or opened_page.url
                if target_url.startswith(("http://", "https://")) and not _urls_equivalent(page_url, target_url):
                    await self._w._goto_page(page, target_url, allow_partial=True)
                session.pages[target_page_id] = page
        if page is None:
            page = self.preferred_session_page(session)
            if not self.page_is_open(page):
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
                self._w._remember_current_url(conversation_id, current_url)
            session.touch()
        self._w._attach_page_console_listeners(conversation_id, target_page_id, page)
        return session, page, target_page_id

    # ------------------------------------------------------------------
    # New page creation
    # ------------------------------------------------------------------

    async def new_session_page(self, session: _BrowserSession) -> Any | None:
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
            page.set_default_timeout(self._w.timeout_ms)
        return page

    # ------------------------------------------------------------------
    # Content target resolution
    # ------------------------------------------------------------------

    def resolve_content_target(
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
            if session is not None and self.is_session_page_alias(conversation_id, session, page_id):
                page = self.preferred_session_page(session)
                target_url = _clean_browser_url(
                    str(
                        getattr(page, "url", "")
                        or session.current_url
                        or session.last_open_url
                        or self._w._current_url_cache.get(conversation_id)
                        or ""
                    )
                )
                if target_url:
                    session.pages.setdefault(page_id, page)
                    return target_url, page_id
            if session is not None:
                page = session.pages.get(page_id)
                if page is not None and self.page_is_open(page):
                    target_url = _clean_browser_url(
                        str(
                            getattr(page, "url", "")
                            or session.current_url
                            or session.last_open_url
                            or self._w._current_url_cache.get(conversation_id)
                            or ""
                        )
                    )
                    if target_url:
                        return target_url, page_id
            opened_page = self._w._opened_page(conversation_id, page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {page_id}. Run BrowserOpen first."
                )
            return opened_page.final_url, opened_page.page_id
        if url:
            return _clean_browser_url(url), None
        next_unextracted = self._w._next_unextracted_opened_page(conversation_id)
        if next_unextracted is not None:
            return next_unextracted.final_url, next_unextracted.page_id
        last_open = self._w._last_open_cache.get(conversation_id)
        if last_open is not None:
            return last_open.final_url, last_open.page_id
        if session is not None and session.last_open_url:
            return session.last_open_url, session.last_open_page_id
        current_url = _clean_browser_url(
            str(
                (session.current_url if session is not None else None)
                or self._w._current_url_cache.get(conversation_id)
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

    def should_navigate_for_content(self, session: _BrowserSession, target_url: str) -> bool:
        target_url = _clean_browser_url(target_url)
        if not target_url.startswith(("http://", "https://")):
            return False
        page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return page_url != target_url

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------

    async def cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._w._sessions.items()
            if now - session.updated_at > self._w.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self.close_session(conversation_id, self._w._sessions[conversation_id])
        self._w._cleanup_search_cache(now)

    async def enforce_session_limit(self) -> None:
        while len(self._w._sessions) > self._w.max_sessions:
            conversation_id, session = min(
                self._w._sessions.items(),
                key=lambda item: item[1].updated_at,
            )
            await self.close_session(conversation_id, session)

    async def reset_browser(self) -> None:
        async with self._w._lock:
            await self.close_sessions()

    async def close_sessions(self) -> None:
        for conversation_id, session in list(self._w._sessions.items()):
            await self.close_session(conversation_id, session)

    async def close_session(self, conversation_id: str, session: _BrowserSession) -> None:
        self._w._sessions.pop(conversation_id, None)
        self._w._element_map_cache.pop(conversation_id, None)
        self._w._console_cache.pop(conversation_id, None)
        self._w._cooperation_event_cache.pop(conversation_id, None)
        get_browser_page_cache().clear_conversation(conversation_id)
        self._w._snapshot_cache.clear_conversation(conversation_id)
        for page in self.session_pages(session):
            await self.best_effort_resource_call("browser_page_close", page.close)
        await self.best_effort_resource_call("browser_context_close", session.context.close)
        await self.release_browser(session.browser)

    async def release_browser(self, browser: Any) -> None:
        await self.best_effort_resource_call("browser_close", browser.close)

    async def best_effort_resource_call(
        self,
        label: str,
        operation: Any,
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await asyncio.wait_for(
                    result,
                    timeout=min(max(self._w.timeout_ms / 1000, 0.5), 2),
                )
        except Exception as exc:
            logger.debug("lightpanda_resource_close_failed", label=label, error=str(exc))
