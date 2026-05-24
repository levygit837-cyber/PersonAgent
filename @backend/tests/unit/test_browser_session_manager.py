"""Tests for BrowserSessionManager (Slice 15 extraction)."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserOpenedPage,
    BrowserSession,
)
from personagent.infrastructure.browser.session_manager import BrowserSessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(*, closed: bool = False, url: str = "https://example.com") -> MagicMock:
    page = MagicMock()
    page.is_closed.return_value = closed
    page.url = url
    page.close = AsyncMock()
    page.set_default_timeout = MagicMock()
    return page


def _make_session(
    *,
    page: Any | None = None,
    pages: dict[str, Any] | None = None,
    current_page_id: str | None = None,
    last_open_page_id: str | None = None,
    current_url: str | None = None,
    last_open_url: str | None = None,
    new_pages_supported: bool = True,
) -> BrowserSession:
    p = page or _make_page()
    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.close = AsyncMock()
    context = MagicMock()
    context.close = AsyncMock()
    context.new_page = AsyncMock(return_value=_make_page())
    session = BrowserSession(
        browser=browser,
        context=context,
        page=p,
        search_results=[],
        current_url=current_url,
        last_open_url=last_open_url,
        last_open_page_id=last_open_page_id,
        current_page_id=current_page_id,
        new_pages_supported=new_pages_supported,
    )
    if pages:
        session.pages.update(pages)
    return session


def _make_worker(**overrides: Any) -> MagicMock:
    worker = MagicMock()
    worker.timeout_ms = 30_000
    worker.session_ttl_seconds = 600
    worker.max_sessions = 12
    worker._sessions = {}
    worker._sessions_lock = asyncio.Lock()
    worker._lock = asyncio.Lock()
    worker._search_cache = {}
    worker._current_url_cache = {}
    worker._last_open_cache = {}
    worker._opened_pages_cache = {}
    worker._element_map_cache = {}
    worker._console_cache = {}
    worker._cooperation_event_cache = {}
    worker._cooperation_listener_keys = set()
    worker._console_listener_keys = set()
    worker._console_sequence = 0
    worker._snapshot_cache = MagicMock()
    worker._latest_cached_search_results = MagicMock(return_value=[])
    worker._opened_page = MagicMock(return_value=None)
    worker._next_unextracted_opened_page = MagicMock(return_value=None)
    worker._remember_current_url = MagicMock()
    worker._attach_page_console_listeners = MagicMock()
    worker._goto_page = AsyncMock()
    worker._connect_browser = AsyncMock()
    worker._first_open_context_page = MagicMock(return_value=None)
    worker.search_result_cache = MagicMock()
    worker.search_result_cache.cleanup_search_cache = MagicMock()
    for key, val in overrides.items():
        setattr(worker, key, val)
    return worker


# ---------------------------------------------------------------------------
# session_has_open_page
# ---------------------------------------------------------------------------

class TestSessionHasOpenPage:
    def test_returns_true_when_page_open(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page(closed=False))
        assert mgr.session_has_open_page(session) is True

    def test_returns_false_when_all_pages_closed(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page(closed=True))
        assert mgr.session_has_open_page(session) is False


# ---------------------------------------------------------------------------
# preferred_session_page
# ---------------------------------------------------------------------------

class TestPreferredSessionPage:
    def test_returns_current_page_id_page_when_open(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        target = _make_page()
        session = _make_session(
            page=_make_page(),
            pages={"tab-1": target},
            current_page_id="tab-1",
        )
        assert mgr.preferred_session_page(session) is target

    def test_falls_back_to_any_open_page(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        fallback = _make_page()
        session = _make_session(
            page=fallback,
            current_page_id="missing",
        )
        assert mgr.preferred_session_page(session) is fallback

    def test_returns_session_page_when_no_open_pages(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        default_page = _make_page(closed=True)
        session = _make_session(page=default_page)
        result = mgr.preferred_session_page(session)
        assert result is default_page


# ---------------------------------------------------------------------------
# session_pages
# ---------------------------------------------------------------------------

class TestSessionPages:
    def test_deduplicates_pages(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        page = _make_page()
        session = _make_session(page=page, pages={"tab-1": page, "tab-2": page})
        assert len(mgr.session_pages(session)) == 1

    def test_includes_all_distinct_pages(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        p1, p2 = _make_page(), _make_page()
        session = _make_session(page=p1, pages={"tab-2": p2})
        assert len(mgr.session_pages(session)) == 2


# ---------------------------------------------------------------------------
# page_is_open
# ---------------------------------------------------------------------------

class TestPageIsOpen:
    def test_open_page(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        assert mgr.page_is_open(_make_page(closed=False)) is True

    def test_closed_page(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        assert mgr.page_is_open(_make_page(closed=True)) is False

    def test_page_without_is_closed(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        page = MagicMock(spec=[])
        assert mgr.page_is_open(page) is True


# ---------------------------------------------------------------------------
# ensure_session_page_alias
# ---------------------------------------------------------------------------

class TestEnsureSessionPageAlias:
    def test_uses_page_id_when_provided(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page())
        result = mgr.ensure_session_page_alias("conv-1", session, page_id="my-tab")
        assert result == "my-tab"
        assert "my-tab" in session.pages

    def test_falls_back_to_current_page_id(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page(), current_page_id="existing")
        result = mgr.ensure_session_page_alias("conv-1", session)
        assert result == "existing"

    def test_falls_back_to_conversation_id(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page())
        result = mgr.ensure_session_page_alias("conv-1", session)
        assert result == "conv-1"


# ---------------------------------------------------------------------------
# is_session_page_alias
# ---------------------------------------------------------------------------

class TestIsSessionPageAlias:
    def test_conversation_id_is_alias(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session()
        assert mgr.is_session_page_alias("conv-1", session, "conv-1") is True

    def test_current_page_id_is_alias(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(current_page_id="tab-1")
        assert mgr.is_session_page_alias("conv-1", session, "tab-1") is True

    def test_random_id_is_not_alias(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(current_page_id="tab-1")
        assert mgr.is_session_page_alias("conv-1", session, "other") is False

    def test_none_session_returns_false(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        assert mgr.is_session_page_alias("conv-1", None, "tab-1") is False

    def test_empty_page_id_returns_false(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session()
        assert mgr.is_session_page_alias("conv-1", session, "") is False


# ---------------------------------------------------------------------------
# live_page_entries
# ---------------------------------------------------------------------------

class TestLivePageEntries:
    def test_groups_same_page_object(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        page = _make_page()
        session = _make_session(page=_make_page(closed=True), pages={"a": page, "b": page})
        entries = mgr.live_page_entries(session)
        assert len(entries) == 1
        assert entries[0][0] == {"a", "b"}

    def test_excludes_closed_pages(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(
            page=_make_page(closed=True),
            pages={"a": _make_page(closed=True)},
        )
        assert mgr.live_page_entries(session) == []


# ---------------------------------------------------------------------------
# cached_usable_session
# ---------------------------------------------------------------------------

class TestCachedUsableSession:
    def test_returns_session_when_valid(self) -> None:
        worker = _make_worker()
        session = _make_session()
        worker._sessions["conv-1"] = session
        mgr = BrowserSessionManager(worker)
        assert mgr.cached_usable_session("conv-1") is session

    def test_returns_none_when_missing(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        assert mgr.cached_usable_session("conv-1") is None

    def test_evicts_session_when_browser_disconnected(self) -> None:
        worker = _make_worker()
        session = _make_session()
        session.browser.is_connected.return_value = False
        worker._sessions["conv-1"] = session
        mgr = BrowserSessionManager(worker)
        assert mgr.cached_usable_session("conv-1") is None
        assert "conv-1" not in worker._sessions


# ---------------------------------------------------------------------------
# new_session_page
# ---------------------------------------------------------------------------

class TestNewSessionPage:
    @pytest.mark.asyncio
    async def test_returns_new_page(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session()
        page = await mgr.new_session_page(session)
        assert page is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_supported(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(new_pages_supported=False)
        assert await mgr.new_session_page(session) is None


# ---------------------------------------------------------------------------
# resolve_content_target
# ---------------------------------------------------------------------------

class TestResolveContentTarget:
    def test_raises_when_both_url_and_page_id(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        with pytest.raises(BrowserError, match="Use either url or page_id"):
            mgr.resolve_content_target("conv-1", None, url="http://x.com", page_id="tab-1")

    def test_returns_url_when_only_url_provided(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        url, pid = mgr.resolve_content_target("conv-1", None, url="http://example.com")
        assert url == "http://example.com"
        assert pid is None

    def test_returns_page_url_when_page_id_is_alias(self) -> None:
        worker = _make_worker()
        mgr = BrowserSessionManager(worker)
        session = _make_session(
            page=_make_page(url="https://found.com"),
            current_page_id="tab-1",
            current_url="https://found.com",
        )
        url, pid = mgr.resolve_content_target("conv-1", session, page_id="tab-1")
        assert url == "https://found.com"
        assert pid == "tab-1"

    def test_raises_when_page_id_not_found(self) -> None:
        worker = _make_worker()
        worker._opened_page.return_value = None
        mgr = BrowserSessionManager(worker)
        with pytest.raises(BrowserError, match="No opened browser page"):
            mgr.resolve_content_target("conv-1", None, page_id="nonexistent")

    def test_falls_back_to_next_unextracted(self) -> None:
        worker = _make_worker()
        opened = BrowserOpenedPage(
            url="https://target.com",
            final_url="https://target.com",
            page_id="pg-1",
        )
        worker._next_unextracted_opened_page.return_value = opened
        mgr = BrowserSessionManager(worker)
        url, pid = mgr.resolve_content_target("conv-1", None)
        assert url == "https://target.com"
        assert pid == "pg-1"

    def test_falls_back_to_last_open_cache(self) -> None:
        worker = _make_worker()
        opened = BrowserOpenedPage(
            url="https://cached.com",
            final_url="https://cached.com",
            page_id="pg-2",
        )
        worker._last_open_cache["conv-1"] = opened
        mgr = BrowserSessionManager(worker)
        url, pid = mgr.resolve_content_target("conv-1", None)
        assert url == "https://cached.com"

    def test_returns_none_when_no_target(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        url, pid = mgr.resolve_content_target("conv-1", None)
        assert url is None
        assert pid is None


# ---------------------------------------------------------------------------
# should_navigate_for_content
# ---------------------------------------------------------------------------

class TestShouldNavigateForContent:
    def test_true_when_urls_differ(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page(url="https://current.com"))
        assert mgr.should_navigate_for_content(session, "https://other.com") is True

    def test_false_when_urls_match(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session(page=_make_page(url="https://same.com"))
        assert mgr.should_navigate_for_content(session, "https://same.com") is False

    def test_false_for_non_http(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        session = _make_session()
        assert mgr.should_navigate_for_content(session, "about:blank") is False


# ---------------------------------------------------------------------------
# cleanup_sessions
# ---------------------------------------------------------------------------

class TestCleanupSessions:
    @pytest.mark.asyncio
    async def test_removes_expired_sessions(self) -> None:
        worker = _make_worker()
        session = _make_session()
        session.updated_at = time.monotonic() - 9999
        worker._sessions["conv-1"] = session
        mgr = BrowserSessionManager(worker)
        await mgr.cleanup_sessions()
        assert "conv-1" not in worker._sessions

    @pytest.mark.asyncio
    async def test_keeps_fresh_sessions(self) -> None:
        worker = _make_worker()
        session = _make_session()
        session.updated_at = time.monotonic()
        worker._sessions["conv-1"] = session
        mgr = BrowserSessionManager(worker)
        await mgr.cleanup_sessions()
        assert "conv-1" in worker._sessions


# ---------------------------------------------------------------------------
# enforce_session_limit
# ---------------------------------------------------------------------------

class TestEnforceSessionLimit:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_over_limit(self) -> None:
        worker = _make_worker()
        worker.max_sessions = 1
        old_session = _make_session()
        old_session.updated_at = time.monotonic() - 100
        new_session = _make_session()
        new_session.updated_at = time.monotonic()
        worker._sessions["old"] = old_session
        worker._sessions["new"] = new_session
        mgr = BrowserSessionManager(worker)
        await mgr.enforce_session_limit()
        assert "old" not in worker._sessions
        assert "new" in worker._sessions


# ---------------------------------------------------------------------------
# close_session
# ---------------------------------------------------------------------------

class TestCloseSession:
    @pytest.mark.asyncio
    async def test_cleans_up_caches_and_closes_resources(self) -> None:
        worker = _make_worker()
        page = _make_page()
        session = _make_session(page=page)
        worker._sessions["conv-1"] = session
        worker._element_map_cache["conv-1"] = []
        worker._console_cache["conv-1"] = {}
        worker._cooperation_event_cache["conv-1"] = {}
        mgr = BrowserSessionManager(worker)
        await mgr.close_session("conv-1", session)
        assert "conv-1" not in worker._sessions
        assert "conv-1" not in worker._element_map_cache
        assert "conv-1" not in worker._console_cache
        assert "conv-1" not in worker._cooperation_event_cache
        page.close.assert_awaited()
        session.context.close.assert_awaited()
        session.browser.close.assert_awaited()


# ---------------------------------------------------------------------------
# best_effort_resource_call
# ---------------------------------------------------------------------------

class TestBestEffortResourceCall:
    @pytest.mark.asyncio
    async def test_calls_sync_operation(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        called = False
        def op() -> None:
            nonlocal called
            called = True
        await mgr.best_effort_resource_call("test", op)
        assert called is True

    @pytest.mark.asyncio
    async def test_calls_async_operation(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        called = False
        async def op() -> None:
            nonlocal called
            called = True
        await mgr.best_effort_resource_call("test", op)
        assert called is True

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self) -> None:
        mgr = BrowserSessionManager(_make_worker())
        def op() -> None:
            raise RuntimeError("boom")
        await mgr.best_effort_resource_call("test", op)


# ---------------------------------------------------------------------------
# close_sessions / reset_browser
# ---------------------------------------------------------------------------

class TestCloseAndReset:
    @pytest.mark.asyncio
    async def test_close_sessions_clears_all(self) -> None:
        worker = _make_worker()
        worker._sessions["a"] = _make_session()
        worker._sessions["b"] = _make_session()
        mgr = BrowserSessionManager(worker)
        await mgr.close_sessions()
        assert len(worker._sessions) == 0

    @pytest.mark.asyncio
    async def test_reset_browser_closes_all(self) -> None:
        worker = _make_worker()
        worker._sessions["a"] = _make_session()
        mgr = BrowserSessionManager(worker)
        await mgr.reset_browser()
        assert len(worker._sessions) == 0
