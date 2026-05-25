"""Unit tests for personagent.infrastructure.browser.opened_pages (Slice 10)."""

from __future__ import annotations

from unittest.mock import MagicMock

from personagent.infrastructure.browser.models import BrowserOpenedPage
from personagent.infrastructure.browser.opened_pages import OpenedPageTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker._opened_pages_cache = {}
    worker._last_open_cache = {}
    return worker


def _make_tracker() -> tuple[OpenedPageTracker, MagicMock]:
    worker = _make_worker()
    return OpenedPageTracker(worker), worker


def _make_opened_page(
    page_id: str = "page_abc",
    url: str = "https://example.com",
    final_url: str = "https://example.com",
    title: str = "Example",
    extraction_count: int = 0,
    opened_at: float | None = None,
) -> BrowserOpenedPage:
    page = BrowserOpenedPage(
        page_id=page_id,
        url=url,
        final_url=final_url,
        title=title,
    )
    page.extraction_count = extraction_count
    if opened_at is not None:
        page.opened_at = opened_at
    return page


# ---------------------------------------------------------------------------
# cache_opened_page
# ---------------------------------------------------------------------------

class TestCacheOpenedPage:
    def test_creates_new_page(self) -> None:
        tracker, worker = _make_tracker()
        opened, reused = tracker.cache_opened_page(
            conversation_id="conv1",
            url="https://example.com",
            final_url="https://example.com/final",
            title="Example",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        assert not reused
        assert opened.page_id.startswith("page_")
        assert opened.url == "https://example.com"
        assert opened.final_url == "https://example.com/final"
        assert opened.title == "Example"
        assert len(worker._opened_pages_cache["conv1"]) == 1
        assert worker._last_open_cache["conv1"] is opened

    def test_reuses_existing_by_final_url(self) -> None:
        tracker, worker = _make_tracker()
        first, _ = tracker.cache_opened_page(
            conversation_id="conv1",
            url="https://example.com",
            final_url="https://example.com/final",
            title="First",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        second, reused = tracker.cache_opened_page(
            conversation_id="conv1",
            url="https://different.com",
            final_url="https://example.com/final",
            title="Updated",
            source_search_id="s1",
            opener_tool_call_id="t1",
        )
        assert reused
        assert second.page_id == first.page_id
        assert second.title == "Updated"
        assert second.source_search_id == "s1"
        assert len(worker._opened_pages_cache["conv1"]) == 1

    def test_limits_to_32_pages(self) -> None:
        tracker, worker = _make_tracker()
        for i in range(40):
            tracker.cache_opened_page(
                conversation_id="conv1",
                url=f"https://example.com/{i}",
                final_url=f"https://example.com/{i}",
                title=f"Page {i}",
                source_search_id=None,
                opener_tool_call_id=None,
            )
        assert len(worker._opened_pages_cache["conv1"]) == 32

    def test_latest_page_is_first(self) -> None:
        tracker, worker = _make_tracker()
        tracker.cache_opened_page(
            conversation_id="c",
            url="https://a.com",
            final_url="https://a.com",
            title="A",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        tracker.cache_opened_page(
            conversation_id="c",
            url="https://b.com",
            final_url="https://b.com",
            title="B",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        assert worker._opened_pages_cache["c"][0].title == "B"


# ---------------------------------------------------------------------------
# browser_open_response
# ---------------------------------------------------------------------------

class TestBrowserOpenResponse:
    def test_response_structure(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page()
        worker._opened_pages_cache = {"conv1": [page]}
        resp = tracker.browser_open_response(
            conversation_id="conv1",
            opened_page=page,
            requested_url="https://example.com",
            title="Example",
            search_id="s1",
            reused_existing_page=False,
        )
        assert resp["type"] == "browser_open"
        assert resp["url"] == "https://example.com"
        assert resp["page_id"] == "page_abc"
        assert resp["search_id"] == "s1"
        assert resp["opened_page_count"] == 1
        assert resp["reused_existing_page"] is False
        assert resp["already_open"] is False
        assert resp["read_status"] == "unread"
        assert resp["extraction_count"] == 0

    def test_read_status_when_extracted(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(extraction_count=3)
        worker._opened_pages_cache = {"conv1": [page]}
        resp = tracker.browser_open_response(
            conversation_id="conv1",
            opened_page=page,
            requested_url="https://example.com",
            title="",
            search_id=None,
            reused_existing_page=True,
        )
        assert resp["read_status"] == "read"
        assert resp["already_read"] is True
        assert resp["already_open"] is True


# ---------------------------------------------------------------------------
# opened_page_read_status
# ---------------------------------------------------------------------------

class TestOpenedPageReadStatus:
    def test_unread(self) -> None:
        page = _make_opened_page(extraction_count=0)
        assert OpenedPageTracker.opened_page_read_status(page) == "unread"

    def test_read(self) -> None:
        page = _make_opened_page(extraction_count=1)
        assert OpenedPageTracker.opened_page_read_status(page) == "read"


# ---------------------------------------------------------------------------
# opened_page_tab
# ---------------------------------------------------------------------------

class TestOpenedPageTab:
    def test_tab_structure(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(
            url="https://example.com/path",
            final_url="https://example.com/path",
            title="Example Page",
        )
        tab = tracker.opened_page_tab(
            page, index=0, current_url=None, last_open_page_id=None,
        )
        assert tab["index"] == 0
        assert tab["page_id"] == "page_abc"
        assert tab["domain"] == "example.com"
        assert tab["title"] == "Example Page"
        assert tab["summary"] == "Example Page"
        assert tab["is_last_open"] is False
        assert tab["is_current_page"] is False

    def test_is_last_open(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page()
        tab = tracker.opened_page_tab(
            page, index=0, current_url=None, last_open_page_id="page_abc",
        )
        assert tab["is_last_open"] is True

    def test_is_current_page(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(final_url="https://example.com")
        tab = tracker.opened_page_tab(
            page, index=0, current_url="https://example.com",
            last_open_page_id=None,
        )
        assert tab["is_current_page"] is True

    def test_summary_falls_back_to_domain(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(
            title="",
            url="https://example.com/path",
            final_url="https://example.com/path",
        )
        tab = tracker.opened_page_tab(
            page, index=0, current_url=None, last_open_page_id=None,
        )
        assert tab["summary"] == "example.com"


# ---------------------------------------------------------------------------
# opened_page / opened_page_by_url
# ---------------------------------------------------------------------------

class TestOpenedPageLookups:
    def test_opened_page_found(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(page_id="p1")
        worker._opened_pages_cache = {"conv1": [page]}
        assert tracker.opened_page("conv1", "p1") is page

    def test_opened_page_not_found(self) -> None:
        tracker, worker = _make_tracker()
        worker._opened_pages_cache = {"conv1": []}
        assert tracker.opened_page("conv1", "p1") is None

    def test_opened_page_by_url_found(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(
            final_url="https://example.com/page",
            url="https://example.com/page",
        )
        worker._opened_pages_cache = {"conv1": [page]}
        result = tracker.opened_page_by_url("conv1", "https://example.com/page")
        assert result is page

    def test_opened_page_by_url_empty(self) -> None:
        tracker, worker = _make_tracker()
        worker._opened_pages_cache = {"conv1": []}
        assert tracker.opened_page_by_url("conv1", "") is None

    def test_opened_page_by_url_no_match(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(url="https://other.com", final_url="https://other.com")
        worker._opened_pages_cache = {"conv1": [page]}
        assert tracker.opened_page_by_url("conv1", "https://example.com") is None


# ---------------------------------------------------------------------------
# target_title
# ---------------------------------------------------------------------------

class TestTargetTitle:
    def test_found(self) -> None:
        tracker, worker = _make_tracker()
        page = _make_opened_page(page_id="p1", title="Hello")
        worker._opened_pages_cache = {"conv1": [page]}
        assert tracker.target_title("conv1", "p1") == "Hello"

    def test_not_found(self) -> None:
        tracker, worker = _make_tracker()
        worker._opened_pages_cache = {"conv1": []}
        assert tracker.target_title("conv1", "p1") == ""

    def test_none_page_id(self) -> None:
        tracker, _ = _make_tracker()
        assert tracker.target_title("conv1", None) == ""


# ---------------------------------------------------------------------------
# next_unextracted_opened_page
# ---------------------------------------------------------------------------

class TestNextUnextractedOpenedPage:
    def test_returns_oldest_unextracted(self) -> None:
        tracker, worker = _make_tracker()
        p1 = _make_opened_page(page_id="p1", opened_at=10.0)
        p2 = _make_opened_page(page_id="p2", opened_at=5.0)
        p3 = _make_opened_page(page_id="p3", extraction_count=1, opened_at=1.0)
        worker._opened_pages_cache = {"conv1": [p1, p2, p3]}
        result = tracker.next_unextracted_opened_page("conv1")
        assert result is not None
        assert result.page_id == "p2"

    def test_returns_none_when_all_extracted(self) -> None:
        tracker, worker = _make_tracker()
        p1 = _make_opened_page(page_id="p1", extraction_count=1)
        worker._opened_pages_cache = {"conv1": [p1]}
        assert tracker.next_unextracted_opened_page("conv1") is None

    def test_returns_none_when_empty(self) -> None:
        tracker, worker = _make_tracker()
        worker._opened_pages_cache = {"conv1": []}
        assert tracker.next_unextracted_opened_page("conv1") is None


# ---------------------------------------------------------------------------
# Backward-compat delegations on worker
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_cache_opened_page_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page, reused = worker.opened_pages.cache_opened_page(
            conversation_id="conv1",
            url="https://example.com",
            final_url="https://example.com",
            title="Test",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        assert page.page_id.startswith("page_")
        assert not reused

    def test_worker_opened_page_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        worker.opened_pages.cache_opened_page(
            conversation_id="conv1",
            url="https://example.com",
            final_url="https://example.com",
            title="Test",
            source_search_id=None,
            opener_tool_call_id=None,
        )
        pages = worker._opened_pages_cache["conv1"]
        result = worker.opened_pages.opened_page("conv1", pages[0].page_id)
        assert result is not None

    def test_worker_target_title_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker.opened_pages.target_title("conv1", None) == ""

    def test_worker_next_unextracted_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker.opened_pages.next_unextracted_opened_page("conv1") is None
