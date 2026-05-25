"""Unit tests for BrowserPageLifecycle extracted from lightpanda.py."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from personagent.infrastructure.browser.models import BrowserError
from personagent.infrastructure.browser.page_lifecycle import BrowserPageLifecycle

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPage:
    """Minimal page object."""

    def __init__(self, url: str = "https://example.com", *, title: str = "Example") -> None:
        self.url = url
        self._title = title
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    async def wait_for_load_state(self, state: str, *, timeout: int = 30_000) -> None:
        pass


class _StubOpenedPage:
    """Minimal opened page record."""

    def __init__(
        self,
        page_id: str = "p1",
        url: str = "https://example.com",
        final_url: str = "https://example.com",
        title: str = "Example",
        source_search_id: str | None = None,
        window_id: str | None = None,
        extraction_count: int = 0,
    ) -> None:
        self.page_id = page_id
        self.url = url
        self.final_url = final_url
        self.title = title
        self.source_search_id = source_search_id
        self.window_id = window_id
        self.extraction_count = extraction_count


class _StubSearchSnapshot:
    def __init__(self, search_id: str, results: list[Any]) -> None:
        self.search_id = search_id
        self.results = results


class _StubSession:
    """Minimal session stub."""

    def __init__(
        self,
        page: _StubPage | None = None,
        page_id: str = "p1",
    ) -> None:
        self.current_page_id: str | None = page_id
        self.last_open_page_id: str | None = page_id
        self.current_url = "https://example.com"
        self.last_open_url = "https://example.com"
        self.page = page or _StubPage()
        self.pages: dict[str, _StubPage] = {page_id: self.page}
        self._touched = False

    def touch(self) -> None:
        self._touched = True


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for lifecycle tests."""

    def __init__(
        self,
        session: _StubSession | None = None,
        page: _StubPage | None = None,
    ) -> None:
        self._session = session or _StubSession(page=page)
        self._page = page or self._session.page
        self.timeout_ms = 5_000
        self._sessions: dict[str, _StubSession] = {"c1": self._session}
        self._current_url_cache: dict[str, str] = {}
        self._last_open_cache: dict[str, _StubOpenedPage] = {}
        self._opened_pages_cache: dict[str, list[_StubOpenedPage]] = {}
        self._console_cache: dict[str, dict[str, Any]] = {}
        self._element_map_cache: dict[str, list[Any]] = {}
        self._search_cache: dict[str, Any] = {}
        # Module stubs
        self.session_manager = _StubSessionManager(self._session, self._page)
        self.element_helpers = _StubElementHelpers()
        self.page_helpers = _StubPageHelpers()
        self.console = _StubConsole()
        self.opened_pages = _StubOpenedPages()
        self.opened_pages.set_cache(self._opened_pages_cache)
        self.search_result_cache = _StubSearchResultCache()
        self.snapshot = _StubSnapshot()
        self.view_reload = AsyncMock(return_value={"url": "https://example.com"})
        self.view_history = AsyncMock(return_value={"url": "https://example.com"})
        self._goto_page = AsyncMock()
        self.block_detector = _StubBlockDetector()

    async def _get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def _resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        resolved_id = page_id or self._session.current_page_id or "p1"
        return self._session, self._page, resolved_id

    async def _cleanup_sessions(self) -> None:
        pass


class _StubSessionManager:
    def __init__(self, session: _StubSession, page: _StubPage) -> None:
        self._session = session
        self._page = page

    async def get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        resolved_id = page_id or self._session.current_page_id or "p1"
        return self._session, self._page, resolved_id

    async def cleanup_sessions(self) -> None:
        pass

    async def new_session_page(self, session: Any) -> _StubPage | None:
        return _StubPage()

    def preferred_session_page(self, session: Any) -> _StubPage:
        return self._page

    def page_is_open(self, page: Any) -> bool:
        return not getattr(page, "_closed", False)

    async def best_effort_resource_call(self, label: str, operation: Any) -> None:
        if asyncio.iscoroutinefunction(operation):
            await operation()
        elif callable(operation):
            operation()

    async def cleanup_live_pages(self, conversation_id: str, session: Any, *, keep_page_id: str) -> None:
        pass

    def ensure_session_page_alias(
        self, conversation_id: str, session: Any, *, page: Any = None, page_id: str | None = None
    ) -> str:
        return page_id or session.current_page_id or conversation_id


class _StubElementHelpers:
    async def safe_user_agent(self, page: Any) -> str:
        return "Mozilla/5.0"


class _StubPageHelpers:
    async def wait_for_page_visual_ready(self, page: Any) -> None:
        pass

    async def safe_title(self, page: Any) -> str:
        return getattr(page, "_title", "")


class _StubConsole:
    async def install_console_capture(self, page: Any) -> None:
        pass

    def attach_page_console_listeners(self, conversation_id: str, page_id: str, page: Any) -> None:
        pass


class _StubOpenedPages:
    def __init__(self) -> None:
        self._cache: dict[str, list[Any]] = {}

    def opened_page(self, conversation_id: str, page_id: str) -> Any:
        return None

    def next_unextracted_opened_page(self, conversation_id: str) -> Any:
        return None

    def opened_page_by_url(self, conversation_id: str, url: str) -> Any:
        for p in self._cache.get(conversation_id, []):
            if p.final_url == url:
                return p
        return None

    def set_cache(self, cache: dict[str, list[Any]]) -> None:
        self._cache = cache

    def opened_page_tab(self, page: Any, index: int, current_url: str | None, last_open_page_id: str | None) -> dict[str, Any]:
        return {
            "index": index,
            "page_id": page.page_id,
            "url": page.final_url,
            "title": page.title,
        }

    def browser_open_response(self, **kwargs: Any) -> dict[str, Any]:
        opened_page = kwargs.get("opened_page")
        page_id = getattr(opened_page, "page_id", "") if opened_page else ""
        return {
            "type": "browser_open",
            "page_id": page_id,
            "url": kwargs.get("requested_url", ""),
            "title": kwargs.get("title", ""),
            "reused_existing_page": kwargs.get("reused_existing_page", False),
        }

    def cache_opened_page(self, **kwargs: Any) -> tuple[Any, bool]:
        opened = _StubOpenedPage(
            page_id="p_new",
            url=kwargs.get("url", ""),
            final_url=kwargs.get("final_url", ""),
            title=kwargs.get("title", ""),
        )
        return opened, False


class _StubSearchResultCache:
    def latest_cached_search_results(self, conversation_id: str) -> list[Any]:
        return []

    def remember_current_url(self, conversation_id: str, url: str) -> None:
        pass

    def cleanup_search_cache(self, now: float) -> None:
        pass

    def result_url(self, conversation_id: str, session: Any, result_index: int, *, search_id: str | None = None) -> tuple[str, str | None]:
        return f"https://result-{result_index}.com", search_id

    def result_title(self, conversation_id: str, result_index: int, *, search_id: str | None = None) -> str:
        return f"Result {result_index}"

    def match_search_result_url(self, conversation_id: str, url: str, *, search_id: str) -> str | None:
        return None

    def match_search_result_title(self, conversation_id: str, url: str, *, search_id: str) -> str:
        return ""

    def cache_search_results(self, **kwargs: Any) -> Any:
        return _StubSearchSnapshot("search-001", [])


class _StubSnapshot:
    async def view_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        return {"snapshot": "test"}

    view_reload = AsyncMock(return_value={"url": "https://example.com"})
    view_history = AsyncMock(return_value={"url": "https://example.com"})

    async def panel_session_tabs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def _new_session_page(self, session: Any) -> _StubPage | None:
        return _StubPage()


class _StubBlockDetector:
    async def raise_if_search_blocked(self, page: Any) -> None:
        pass


def _make_lifecycle(
    *,
    session: _StubSession | None = None,
    page: _StubPage | None = None,
) -> tuple[BrowserPageLifecycle, _StubWorker]:
    worker = _StubWorker(session=session, page=page)
    lc = BrowserPageLifecycle(worker)  # type: ignore[arg-type]
    return lc, worker


# ---------------------------------------------------------------------------
# Tests: open
# ---------------------------------------------------------------------------


class TestOpen:
    @pytest.mark.asyncio
    async def test_open_url_creates_page(self) -> None:
        lc, worker = _make_lifecycle()
        result = await lc.open(conversation_id="c1", url="https://new.com")
        assert result["type"] == "browser_open"
        assert result["url"] == "https://new.com"

    @pytest.mark.asyncio
    async def test_open_reuses_existing_page(self) -> None:
        session = _StubSession()
        page = _StubPage(url="https://existing.com")
        opened = _StubOpenedPage(page_id="p1", final_url="https://existing.com", title="Existing")
        lc, worker = _make_lifecycle(session=session)
        worker._opened_pages_cache["c1"] = [opened]
        session.pages["p1"] = page
        result = await lc.open(conversation_id="c1", url="https://existing.com")
        assert result["reused_existing_page"] is True

    @pytest.mark.asyncio
    async def test_open_by_result_index(self) -> None:
        lc, worker = _make_lifecycle()
        result = await lc.open(conversation_id="c1", result_index=0)
        assert result["type"] == "browser_open"

    @pytest.mark.asyncio
    async def test_open_no_url_no_index_raises(self) -> None:
        lc, _ = _make_lifecycle()
        with pytest.raises(BrowserError, match="url or result_index"):
            await lc.open(conversation_id="c1")


# ---------------------------------------------------------------------------
# Tests: list_tabs
# ---------------------------------------------------------------------------


class TestListTabs:
    @pytest.mark.asyncio
    async def test_list_tabs_empty_session(self) -> None:
        lc, worker = _make_lifecycle()
        worker._sessions.clear()
        result = await lc.list_tabs(conversation_id="c1", max_tabs=10)
        assert result["type"] == "browser_tabs"
        assert result["tab_count"] == 0

    @pytest.mark.asyncio
    async def test_list_tabs_with_opened_pages(self) -> None:
        lc, worker = _make_lifecycle()
        worker._opened_pages_cache["c1"] = [
            _StubOpenedPage(page_id="p1", title="Page 1"),
            _StubOpenedPage(page_id="p2", title="Page 2"),
        ]
        result = await lc.list_tabs(conversation_id="c1", max_tabs=10)
        assert result["tab_count"] == 2

    @pytest.mark.asyncio
    async def test_list_tabs_respects_max(self) -> None:
        lc, worker = _make_lifecycle()
        worker._opened_pages_cache["c1"] = [
            _StubOpenedPage(page_id=f"p{i}") for i in range(10)
        ]
        result = await lc.list_tabs(conversation_id="c1", max_tabs=3)
        assert len(result["tabs"]) <= 3

    @pytest.mark.asyncio
    async def test_list_tabs_max_clamped_to_50(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.list_tabs(conversation_id="c1", max_tabs=999)
        assert result["max_tabs"] == 50

    @pytest.mark.asyncio
    async def test_list_tabs_with_current_url_fallback(self) -> None:
        lc, worker = _make_lifecycle()
        worker._current_url_cache["c1"] = "https://fallback.com"
        worker._sessions.clear()
        result = await lc.list_tabs(conversation_id="c1", max_tabs=10)
        assert result["current_url"] == "https://fallback.com"


# ---------------------------------------------------------------------------
# Tests: close_tab
# ---------------------------------------------------------------------------


class TestCloseTab:
    @pytest.mark.asyncio
    async def test_close_tab_removes_page(self) -> None:
        session = _StubSession()
        page = _StubPage()
        session.pages["p1"] = page
        lc, worker = _make_lifecycle(session=session)
        worker._opened_pages_cache["c1"] = [_StubOpenedPage(page_id="p1")]
        result = await lc.close_tab(conversation_id="c1", page_id="p1")
        assert result["type"] == "browser_close_tab"
        assert result["closed_page_id"] == "p1"
        assert result["closed"] is True
        assert page._closed is True

    @pytest.mark.asyncio
    async def test_close_tab_no_page_raises(self) -> None:
        session = _StubSession()
        session.current_page_id = None
        session.last_open_page_id = None
        lc, worker = _make_lifecycle(session=session)
        worker._last_open_cache.clear()
        with pytest.raises(BrowserError, match="No browser page selected"):
            await lc.close_tab(conversation_id="c1")

    @pytest.mark.asyncio
    async def test_close_tab_clears_console_cache(self) -> None:
        session = _StubSession()
        lc, worker = _make_lifecycle(session=session)
        worker._console_cache["c1"] = {"p1": ["entry"]}
        worker._opened_pages_cache["c1"] = [_StubOpenedPage(page_id="p1")]
        await lc.close_tab(conversation_id="c1", page_id="p1")
        assert "p1" not in worker._console_cache.get("c1", {})


# ---------------------------------------------------------------------------
# Tests: reload
# ---------------------------------------------------------------------------


class TestReload:
    @pytest.mark.asyncio
    async def test_reload_returns_type(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.reload(conversation_id="c1")
        assert result["type"] == "browser_reload"
        assert result["navigated"] is True

    @pytest.mark.asyncio
    async def test_reload_sets_page_id(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.reload(conversation_id="c1")
        assert result["page_id"] == "p1"


# ---------------------------------------------------------------------------
# Tests: history
# ---------------------------------------------------------------------------


class TestHistory:
    @pytest.mark.asyncio
    async def test_history_back(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.history(conversation_id="c1", direction=-1)
        assert result["type"] == "browser_history"
        assert result["direction"] == -1
        assert result["navigated"] is True

    @pytest.mark.asyncio
    async def test_history_forward(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.history(conversation_id="c1", direction=1)
        assert result["direction"] == 1

    @pytest.mark.asyncio
    async def test_history_negative_clamped(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.history(conversation_id="c1", direction=-99)
        assert result["direction"] == -1


# ---------------------------------------------------------------------------
# Tests: switch_tab
# ---------------------------------------------------------------------------


class TestSwitchTab:
    @pytest.mark.asyncio
    async def test_switch_tab_returns_type(self) -> None:
        lc, _ = _make_lifecycle()
        result = await lc.switch_tab(conversation_id="c1", page_id="p1")
        assert result["type"] == "browser_switch_tab"
        assert result["active_tab_id"] == "p1"
        assert result["navigated"] is False

    @pytest.mark.asyncio
    async def test_switch_tab_updates_current_url(self) -> None:
        page = _StubPage(url="https://switched.com")
        session = _StubSession(page=page)
        lc, _ = _make_lifecycle(session=session, page=page)
        await lc.switch_tab(conversation_id="c1", page_id="p1")
        assert session.current_url == "https://switched.com"
