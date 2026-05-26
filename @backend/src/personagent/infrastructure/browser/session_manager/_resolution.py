"""Page resolution — resolve a live page and content targets for a conversation."""

from __future__ import annotations

from typing import Any

from personagent.infrastructure.browser.models import (
    BrowserError,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.search.url_utils import (
    urls_equivalent as _urls_equivalent,
)


class _PageResolutionMixin:
    """Methods for resolving live pages and content targets."""

    async def resolve_live_page(
        self,
        conversation_id: str,
        *,
        page_id: str | None = None,
        activate: bool = True,
    ) -> tuple[_BrowserSession, Any, str]:
        session = await self.get_session(conversation_id)
        target_page_id = self._resolve_target_page_id(conversation_id, session, page_id)
        page = self._resolve_page_from_session(session, target_page_id)

        if page is None and target_page_id:
            page = self._resolve_page_from_alias_or_opened(conversation_id, session, target_page_id)

        if page is None:
            page = self._resolve_page_fallback(session, target_page_id)

        if activate:
            self._activate_page(conversation_id, session, page, target_page_id)

        self._w.console.attach_page_console_listeners(conversation_id, target_page_id, page)
        return session, page, target_page_id

    def _resolve_target_page_id(self, conversation_id: str, session: _BrowserSession, page_id: str | None) -> str:
        last_open = self._w._last_open_cache.get(conversation_id)
        last_open_page_id = last_open.page_id if last_open else ""
        return str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or last_open_page_id
            or ""
        ).strip()

    def _resolve_page_from_session(self, session: _BrowserSession, target_page_id: str) -> Any | None:
        if not target_page_id:
            return None
        page = session.pages.get(target_page_id)
        if page is not None and not self.page_is_open(page):
            session.pages.pop(target_page_id, None)
            return None
        return page

    async def _resolve_page_from_alias_or_opened(
        self, conversation_id: str, session: _BrowserSession, target_page_id: str
    ) -> Any:
        if self.is_session_page_alias(conversation_id, session, target_page_id):
            page = self.preferred_session_page(session)
            if not self.page_is_open(page):
                raise BrowserError(
                    f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                )
            session.pages[target_page_id] = page
            return page

        opened_page = self._w.opened_pages.opened_page(conversation_id, target_page_id)
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
        return page

    def _resolve_page_fallback(self, session: _BrowserSession, target_page_id: str) -> Any:
        page = self.preferred_session_page(session)
        if not self.page_is_open(page):
            raise BrowserError("No live browser page is available. Run BrowserOpen first.")

        fallback_page_id = target_page_id or session.current_page_id or session.last_open_page_id
        session.pages.setdefault(fallback_page_id, page)
        return page

    def _activate_page(
        self, conversation_id: str, session: _BrowserSession, page: Any, target_page_id: str
    ) -> None:
        session.page = page
        session.current_page_id = target_page_id
        session.last_open_page_id = target_page_id
        current_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if current_url:
            session.current_url = current_url
            self._w.search_result_cache.remember_current_url(conversation_id, current_url)
        session.touch()

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
            opened_page = self._w.opened_pages.opened_page(conversation_id, page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {page_id}. Run BrowserOpen first."
                )
            return opened_page.final_url, opened_page.page_id
        if url:
            return _clean_browser_url(url), None
        next_unextracted = self._w.opened_pages.next_unextracted_opened_page(conversation_id)
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
