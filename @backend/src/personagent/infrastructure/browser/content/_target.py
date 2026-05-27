"""Content-target resolution and page lookup helpers for BrowserContent."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.search.url_utils import (
    urls_equivalent as _urls_equivalent,
)


class _ContentTargetMixin:
    """Methods for resolving content targets and looking up pages."""

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
            if page is None and self._w.session_manager.is_session_page_alias(conversation_id, session, target_page_id):
                page = self._w.session_manager.preferred_session_page(session)
                if page is not None and self._w.session_manager.page_is_open(page):
                    session.pages[target_page_id] = page
            if page is not None and self._is_live_page_for_url(page, clean_target_url):
                return page
            return None

        preferred_page = self._w.session_manager.preferred_session_page(session)
        if self._is_live_page_for_url(preferred_page, clean_target_url):
            return preferred_page
        if not allow_navigation or not clean_target_url.startswith(("http://", "https://")):
            return None

        page = await self._w.session_manager.new_session_page(session)
        if page is None:
            page = preferred_page
        await self._w._navigation.goto_page(page, clean_target_url, allow_partial=True)
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
