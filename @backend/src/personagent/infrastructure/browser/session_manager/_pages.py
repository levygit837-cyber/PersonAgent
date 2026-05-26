"""Session page queries, live-page management, aliases, and new-page creation."""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.url_utils import (
    is_target_already_loaded_error as _is_target_already_loaded_error,
)

logger = structlog.get_logger(__name__)

_MAX_LIVE_PAGES_PER_SESSION = 4


class _SessionPagesMixin:
    """Page queries, live-page management, aliases, and new-page creation."""

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
                if (opened_page := self._w.opened_pages.opened_page(conversation_id, page_id)) is not None
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
