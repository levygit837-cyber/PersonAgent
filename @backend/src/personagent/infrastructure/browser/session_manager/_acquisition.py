"""Session acquisition — get or reuse a browser session."""

from __future__ import annotations

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.models import (
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.search.url_utils import (
    is_target_already_loaded_error as _is_target_already_loaded_error,
)


class _SessionAcquisitionMixin:
    """Methods for acquiring and caching browser sessions."""

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
                        cached_results = self._w.d
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
                    search_results=self._w.search_result_cache.latest_cached_search_results(conversation_id),
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
