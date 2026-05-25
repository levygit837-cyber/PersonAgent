"""Unit tests for BrowserContent extracted from lightpanda.py (Slice 8)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.infrastructure.browser.content import BrowserContent
from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserOpenedPage,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPage:
    def __init__(self, url: str = "https://example.com") -> None:
        self.url = url

    def is_closed(self) -> bool:
        return False

    async def content(self) -> str:
        return "<html><body>hello</body></html>"

    async def wait_for_load_state(self, state: str, timeout: int = 8_000) -> None:
        pass

    async def wait_for_timeout(self, ms: int) -> None:
        pass


class _StubSession:
    def __init__(self, page: _StubPage | None = None) -> None:
        self.page = page or _StubPage()
        self.pages: dict[str, Any] = {}
        self.current_url = "https://example.com"
        self.last_open_url = "https://example.com"
        self.last_open_page_id: str | None = None
        self.current_page_id: str | None = None
        self._touched = False

    def touch(self) -> None:
        self._touched = True


class _StubSnapshot:
    def __init__(self) -> None:
        self.browser_view_snapshot = AsyncMock(return_value={})


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for BrowserContent tests."""

    def __init__(self) -> None:
        self._session = _StubSession()
        self.snapshot = _StubSnapshot()
        self.timeout_ms = 5_000
        self._current_url_cache: dict[str, str] = {}
        self._opened_pages_cache: dict[str, list[Any]] = {}
        self._last_open_cache: dict[str, Any] = {}
        self._search_cache: dict[str, list[Any]] = {}
        # Module stubs
        self.session_manager = _StubSessionManager(self._session)
        self.element_helpers = _StubElementHelpers()
        self.page_helpers = _StubPageHelpers()
        self.console = _StubConsole()
        self.opened_pages = _StubOpenedPages()
        self.search_result_cache = _StubSearchResultCache()

        self._get_session = AsyncMock(return_value=self._session)
        self._cached_usable_session = MagicMock(return_value=self._session)
        self._preferred_session_page = MagicMock(return_value=self._session.page)
        self._page_is_open = MagicMock(return_value=True)
        self._is_session_page_alias = MagicMock(return_value=False)
        self._remember_current_url = MagicMock()
        self._goto_page = AsyncMock()
        self._new_session_page = AsyncMock(return_value=None)
        self._evaluate_page = AsyncMock(return_value={"content": "test content", "selected_tag": "body", "score": 1.0})
        self._safe_title = AsyncMock(return_value="Test Page")
        self._raw_runtime_evaluate_value = AsyncMock(return_value=None)
        self._lightpanda_raw_cdp_command = AsyncMock(return_value=None)
        self._lightpanda_markdown_url = AsyncMock(return_value="")
        self._cleanup_live_pages = AsyncMock()
        self._opened_page = MagicMock(return_value=None)
        self._resolve_content_target = MagicMock(return_value=("https://example.com", None))
        self._target_title = MagicMock(return_value="Test Page")


class _StubSessionManager:
    def __init__(self, session: _StubSession) -> None:
        self._session = session

    async def get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    def cached_usable_session(self, conversation_id: str) -> _StubSession | None:
        return self._session

    async def resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        return self._session, self._session.page, page_id or "p1"

    async def cleanup_live_pages(
        self, conversation_id: str, session: Any, keep_page_id: str | None = None, close_read_pages: bool = False
    ) -> None:
        pass


class _StubElementHelpers:
    async def safe_user_agent(self, page: Any) -> str:
        return "Mozilla/5.0"


class _StubPageHelpers:
    async def wait_for_page_visual_ready(self, page: Any) -> None:
        pass

    async def safe_title(self, page: Any) -> str:
        return "Test Page"


class _StubConsole:
    async def install_console_capture(self, page: Any) -> None:
        pass

    def attach_page_console_listeners(self, conversation_id: str, page_id: str, page: Any) -> None:
        pass


class _StubOpenedPages:
    def __init__(self) -> None:
        self._opened_page: Any = None

    def opened_page(self, conversation_id: str, page_id: str) -> Any:
        return self._opened_page

    def next_unextracted_opened_page(self, conversation_id: str) -> Any:
        return None

    def target_title(self, conversation_id: str, page_id: str) -> str:
        return "Test Page"


class _StubSearchResultCache:
    def latest_cached_search_results(self, conversation_id: str) -> list[Any]:
        return []

    def remember_current_url(self, conversation_id: str, url: str) -> None:
        pass

    def cleanup_search_cache(self, now: float) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make() -> tuple[BrowserContent, _StubWorker]:
    worker = _StubWorker()
    bc = BrowserContent(worker)
    return bc, worker


# ---------------------------------------------------------------------------
# Tests — extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    @pytest.mark.asyncio
    async def test_returns_content_dict(self):
        bc, worker = _make()
        result = await bc.extract_content(
            conversation_id="c1",
            max_chars=10_000,
            include_links=False,
        )
        assert result["type"] == "browser_extract_content"
        assert result["url"] == "https://example.com"
        assert "content" in result

    @pytest.mark.asyncio
    async def test_truncates_at_max_chars(self):
        bc, worker = _make()
        worker._evaluate_page = AsyncMock(return_value="x" * 500)
        result = await bc.extract_content(
            conversation_id="c1",
            max_chars=100,
            include_links=False,
        )
        assert result["truncated"] is True
        assert len(result["content"]) <= 100

    @pytest.mark.asyncio
    async def test_raises_when_no_page_selected(self):
        bc, worker = _make()
        worker._cached_usable_session = MagicMock(return_value=None)
        worker._get_session = AsyncMock(return_value=None)
        worker._resolve_content_target = MagicMock(return_value=(None, None))
        with pytest.raises(BrowserError, match="No browser page selected"):
            await bc.extract_content(
                conversation_id="c1",
                max_chars=10_000,
                include_links=False,
            )

    @pytest.mark.asyncio
    async def test_includes_links_when_requested(self):
        bc, worker = _make()
        worker._evaluate_page = AsyncMock(return_value="Check [link](https://example.com/page)")
        result = await bc.extract_content(
            conversation_id="c1",
            max_chars=10_000,
            include_links=True,
        )
        assert isinstance(result["links"], list)

    @pytest.mark.asyncio
    async def test_tracks_opened_page_extraction(self):
        bc, worker = _make()
        opened = BrowserOpenedPage(
            page_id="p1",
            url="https://example.com",
            final_url="https://example.com",
            title="Test",
            opened_at=time.monotonic(),
            extraction_count=0,
        )
        worker.opened_pages._opened_page = opened
        worker._resolve_content_target = MagicMock(return_value=("https://example.com", "p1"))
        await bc.extract_content(
            conversation_id="c1",
            max_chars=10_000,
            include_links=False,
        )
        assert opened.extraction_count == 1


# ---------------------------------------------------------------------------
# Tests — get_html
# ---------------------------------------------------------------------------


class TestGetHtml:
    @pytest.mark.asyncio
    async def test_returns_html_dict(self):
        bc, worker = _make()
        result = await bc.get_html(
            conversation_id="c1",
            max_chars=50_000,
        )
        assert result["type"] == "browser_get_html"
        assert "html" in result

    @pytest.mark.asyncio
    async def test_truncates_html(self):
        bc, worker = _make()
        result = await bc.get_html(
            conversation_id="c1",
            max_chars=5,
        )
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_raises_when_no_page_selected(self):
        bc, worker = _make()
        worker._cached_usable_session = MagicMock(return_value=None)
        worker._get_session = AsyncMock(return_value=None)
        worker._resolve_content_target = MagicMock(return_value=(None, None))
        with pytest.raises(BrowserError, match="No browser page selected"):
            await bc.get_html(
                conversation_id="c1",
                max_chars=50_000,
            )


# ---------------------------------------------------------------------------
# Tests — _content_page_for_target
# ---------------------------------------------------------------------------


class TestContentPageForTarget:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_session(self):
        bc, _ = _make()
        result = await bc._content_page_for_target(
            conversation_id="c1",
            session=None,
            target_url="https://example.com",
            target_page_id=None,
            allow_navigation=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_preferred_page_when_url_matches(self):
        bc, worker = _make()
        session = _StubSession()
        result = await bc._content_page_for_target(
            conversation_id="c1",
            session=session,
            target_url="https://example.com",
            target_page_id=None,
            allow_navigation=False,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Tests — _is_live_page_for_url
# ---------------------------------------------------------------------------


class TestIsLivePageForUrl:
    def test_returns_true_for_matching_url(self):
        bc, _ = _make()
        page = _StubPage(url="https://example.com/page")
        assert bc._is_live_page_for_url(page, "https://example.com/page") is True

    def test_returns_false_for_different_url(self):
        bc, _ = _make()
        page = _StubPage(url="https://example.com/page1")
        assert bc._is_live_page_for_url(page, "https://example.com/page2") is False


# ---------------------------------------------------------------------------
# Tests — _extract_links_from_content
# ---------------------------------------------------------------------------


class TestExtractLinksFromContent:
    def test_extracts_markdown_links(self):
        bc, _ = _make()
        content = "Check [Google](https://google.com) and [GitHub](https://github.com)"
        links = bc._extract_links_from_content(content)
        assert len(links) == 2
        assert links[0]["url"] == "https://google.com"

    def test_deduplicates_links(self):
        bc, _ = _make()
        content = "[a](https://x.com) [b](https://x.com)"
        links = bc._extract_links_from_content(content)
        assert len(links) == 1


# ---------------------------------------------------------------------------
# Tests — _merge_popup_dismissal
# ---------------------------------------------------------------------------


class TestMergePopupDismissal:
    def test_merges_counts(self):
        bc, _ = _make()
        metadata: dict[str, Any] = {"popup_dismissed_count": 1, "popup_dismissed_labels": ["ok"]}
        bc._merge_popup_dismissal(metadata, {"clicked_count": 2, "clicked_labels": ["x", "y"]})
        assert metadata["popup_dismissed_count"] == 3
        assert len(metadata["popup_dismissed_labels"]) == 3


# ---------------------------------------------------------------------------
# Tests — _extract_markdown_payload
# ---------------------------------------------------------------------------


class TestExtractMarkdownPayload:
    def test_extracts_from_dict_markdown_key(self):
        bc, _ = _make()
        assert bc._extract_markdown_payload({"markdown": "# Hello"}) == "# Hello"

    def test_extracts_from_string(self):
        bc, _ = _make()
        assert bc._extract_markdown_payload("raw markdown") == "raw markdown"

    def test_returns_empty_on_none(self):
        bc, _ = _make()
        assert bc._extract_markdown_payload(None) == ""


# ---------------------------------------------------------------------------
# Tests — _mark_opened_page_extracted
# ---------------------------------------------------------------------------


class TestMarkOpenedPageExtracted:
    def test_increments_extraction_count(self):
        bc, _ = _make()
        opened = BrowserOpenedPage(
            page_id="p1",
            url="https://example.com",
            final_url="https://example.com",
            title="Test",
            opened_at=time.monotonic(),
            extraction_count=0,
        )
        bc._mark_opened_page_extracted(opened)
        assert opened.extraction_count == 1
        bc._mark_opened_page_extracted(opened)
        assert opened.extraction_count == 2


# ---------------------------------------------------------------------------
# Tests — backward-compat delegations
# ---------------------------------------------------------------------------


class TestBackwardCompatDelegations:
    def test_worker_has_content_module(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
        assert hasattr(worker, "content_module")
        assert hasattr(worker.content_module, "extract_content")
        assert hasattr(worker.content_module, "get_html")
