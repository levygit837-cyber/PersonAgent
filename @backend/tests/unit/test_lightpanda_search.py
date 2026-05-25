"""Unit tests for BrowserSearch extracted from lightpanda.py (Slice 6)."""

from __future__ import annotations

from typing import Any

import pytest

from personagent.infrastructure.browser.search import (
    BrowserSearch,
    _search_results_script,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPage:
    def __init__(self, url: str = "https://search.example.com") -> None:
        self.url = url

    async def close(self) -> None:
        pass


class _StubSession:
    def __init__(self, page: _StubPage | None = None) -> None:
        self.page = page or _StubPage()
        self.current_url = getattr(self.page, "url", "about:blank")
        self.search_results: list[Any] = []
        self._touched = False

    def touch(self) -> None:
        self._touched = True


class _StubSearchSnapshot:
    def __init__(self, search_id: str, results: list[Any]) -> None:
        self.search_id = search_id
        self.results = results


class _StubSearchResult:
    def __init__(self, title: str, url: str, snippet: str = "") -> None:
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for BrowserSearch tests."""

    def __init__(
        self,
        *,
        search_provider: str = "google",
        search_base_url: str = "https://www.google.com/search",
    ) -> None:
        self.search_provider = search_provider
        self.search_base_url = search_base_url
        self.timeout_ms = 5_000
        self._session = _StubSession()
        self._search_cache: dict[str, list[Any]] = {}
        self._new_page_result: Any = None
        self._evaluate_result: Any = None
        self._goto_urls: list[str] = []
        # Module stubs
        self.session_manager = _StubSessionManager(session=self._session)
        self.element_helpers = _StubElementHelpers()
        self.page_helpers = _StubPageHelpers()
        self.console = _StubConsole()
        self.opened_pages = _StubOpenedPages()
        self.search_result_cache = _StubSearchResultCache()
        self.block_detector = _StubBlockDetector()

    async def _get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def _new_session_page(self, session: Any) -> Any:
        return self._new_page_result

    async def _goto_page(self, page: Any, url: str) -> None:
        self._goto_urls.append(url)
        if hasattr(page, "url"):
            page.url = url

    async def _raise_if_search_blocked(self, page: Any) -> None:
        pass

    async def _evaluate_page(self, page: Any, script: str, args: Any = None) -> Any:
        return self._evaluate_result

    async def _best_effort_resource_call(self, label: str, coro: Any) -> None:
        pass

    async def _raw_runtime_evaluate_value(
        self, url: str, expression: str, *, label: str, timeout: float
    ) -> Any:
        return self._evaluate_result

    def _cache_search_results(
        self, *, conversation_id: str, query: str, search_url: str, results: list[Any]
    ) -> _StubSearchSnapshot:
        return _StubSearchSnapshot("search-001", results)


class _StubSessionManager:
    def __init__(self, session: _StubSession | None = None, new_page_result: Any = None) -> None:
        self._session = session or _StubSession()
        self._new_page_result = new_page_result

    async def get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        return self._session, self._session.page or _StubPage(), page_id or "p1"

    async def new_session_page(self, session: Any) -> _StubPage | None:
        return self._new_page_result or _StubPage()

    async def best_effort_resource_call(self, label: str, operation: Any) -> None:
        pass


class _StubElementHelpers:
    async def safe_user_agent(self, page: Any) -> str:
        return "Mozilla/5.0"


class _StubPageHelpers:
    async def wait_for_page_visual_ready(self, page: Any) -> None:
        pass


class _StubConsole:
    async def install_console_capture(self, page: Any) -> None:
        pass

    def attach_page_console_listeners(self, conversation_id: str, page_id: str, page: Any) -> None:
        pass


class _StubOpenedPages:
    def opened_page(self, conversation_id: str, page_id: str) -> Any:
        return None

    def next_unextracted_opened_page(self, conversation_id: str) -> Any:
        return None


class _StubSearchResultCache:
    def latest_cached_search_results(self, conversation_id: str) -> list[Any]:
        return []

    def remember_current_url(self, conversation_id: str, url: str) -> None:
        pass

    def cleanup_search_cache(self, now: float) -> None:
        pass

    def cache_search_results(self, conversation_id: str, query: str, search_url: str, results: list[Any]) -> Any:
        return _StubSearchSnapshot("search-001", results)

    def copy_search_results(self, results: list[Any]) -> list[Any]:
        return list(results)

    def _copy_search_results(self, results: list[Any]) -> list[Any]:
        return list(results)

    def _remember_current_url(self, browser_id: str, url: str) -> None:
        pass


class _StubBlockDetector:
    async def raise_if_search_blocked(self, page: Any) -> None:
        pass

    async def raise_if_google_blocked(self, page: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_search(*, provider: str = "google", base_url: str = "https://www.google.com/search") -> tuple[BrowserSearch, _StubWorker]:
    worker = _StubWorker(search_provider=provider, search_base_url=base_url)
    search = BrowserSearch(worker)
    return search, worker


# ---------------------------------------------------------------------------
# Tests — search_provider_label
# ---------------------------------------------------------------------------


class TestSearchProviderLabel:
    def test_google(self):
        search, _ = _make_search(provider="google")
        assert search.search_provider_label == "Google"

    def test_bing(self):
        search, _ = _make_search(provider="bing")
        assert search.search_provider_label == "Bing"

    def test_yahoo(self):
        search, _ = _make_search(provider="yahoo")
        assert search.search_provider_label == "Yahoo"

    def test_generic(self):
        search, _ = _make_search(provider="generic")
        assert search.search_provider_label == "the configured search provider"

    def test_unknown_returns_raw(self):
        search, _ = _make_search(provider="duckduckgo")
        assert search.search_provider_label == "duckduckgo"


# ---------------------------------------------------------------------------
# Tests — search_url
# ---------------------------------------------------------------------------


class TestSearchUrl:
    def test_google_basic(self):
        search, _ = _make_search(provider="google")
        url = search.search_url("hello world")
        assert "q=hello+world" in url
        assert "hl=en" in url
        assert "gl=us" in url
        assert "pws=0" in url

    def test_google_max_results(self):
        search, _ = _make_search(provider="google")
        url = search.search_url("test", max_results=5)
        assert "num=5" in url

    def test_bing_basic(self):
        search, _ = _make_search(provider="bing", base_url="https://www.bing.com/search")
        url = search.search_url("hello")
        assert "q=hello" in url
        assert "setlang=en-US" in url
        assert "cc=US" in url

    def test_bing_max_results(self):
        search, _ = _make_search(provider="bing", base_url="https://www.bing.com/search")
        url = search.search_url("test", max_results=3)
        assert "count=3" in url

    def test_yahoo_basic(self):
        search, _ = _make_search(provider="yahoo", base_url="https://search.yahoo.com/search")
        url = search.search_url("hello")
        assert "p=hello" in url
        assert "q=" not in url

    def test_yahoo_max_results(self):
        search, _ = _make_search(provider="yahoo", base_url="https://search.yahoo.com/search")
        url = search.search_url("test", max_results=7)
        assert "pz=7" in url

    def test_max_results_clamped_to_10(self):
        search, _ = _make_search(provider="google")
        url = search.search_url("test", max_results=50)
        assert "num=10" in url

    def test_max_results_minimum_1(self):
        search, _ = _make_search(provider="google")
        url = search.search_url("test", max_results=0)
        assert "num=1" in url

    def test_preserves_existing_params(self):
        search, _ = _make_search(provider="google", base_url="https://www.google.com/search?safe=active")
        url = search.search_url("test")
        assert "safe=active" in url
        assert "q=test" in url


# ---------------------------------------------------------------------------
# Tests — _search_results_script
# ---------------------------------------------------------------------------


class TestSearchResultsScript:
    def test_google_script(self):
        script = _search_results_script("google")
        assert "google." in script

    def test_bing_script(self):
        script = _search_results_script("bing")
        assert "bing.com" in script

    def test_yahoo_script(self):
        script = _search_results_script("yahoo")
        assert "yahoo.com" in script

    def test_generic_script(self):
        script = _search_results_script("unknown")
        assert "searchHost" in script

    def test_all_scripts_are_js_functions(self):
        for provider in ["google", "bing", "yahoo", "unknown"]:
            script = _search_results_script(provider)
            assert script.strip().startswith("(")
            assert "maxResults" in script


# ---------------------------------------------------------------------------
# Tests — search (full flow)
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_with_new_page(self):
        search, worker = _make_search()
        page = _StubPage(url="https://www.google.com/search?q=hello")
        worker._new_page_result = page
        worker._evaluate_result = [
            {"title": "Example", "url": "https://example.com", "snippet": "A snippet"},
        ]

        result = await search.search(
            conversation_id="conv1",
            query="hello",
            max_results=5,
        )

        assert result["type"] == "browser_search"
        assert result["provider"] == "google"
        assert result["query"] == "hello"
        assert result["search_id"] == "search-001"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Example"
        assert worker._session._touched is True

    @pytest.mark.asyncio
    async def test_search_without_new_page_uses_runtime_evaluate(self):
        search, worker = _make_search()
        worker._new_page_result = None
        worker._evaluate_result = [
            {"title": "Fallback Result", "url": "https://fallback.com", "snippet": ""},
        ]

        result = await search.search(
            conversation_id="conv1",
            query="fallback",
            max_results=3,
        )

        assert result["type"] == "browser_search"
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Fallback Result"

    @pytest.mark.asyncio
    async def test_search_filters_invalid_results(self):
        search, worker = _make_search()
        worker._new_page_result = _StubPage()
        worker._evaluate_result = [
            {"title": "Valid", "url": "https://valid.com", "snippet": "ok"},
            {"title": "", "url": "https://notitle.com", "snippet": ""},
            {"url": "https://missing-title.com", "snippet": ""},
            42,
            None,
        ]

        result = await search.search(
            conversation_id="conv1",
            query="test",
            max_results=10,
        )

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Valid"

    @pytest.mark.asyncio
    async def test_search_respects_max_results_limit(self):
        search, worker = _make_search()
        worker._new_page_result = _StubPage()
        worker._evaluate_result = [
            {"title": f"Result {i}", "url": f"https://r{i}.com", "snippet": ""}
            for i in range(10)
        ]

        result = await search.search(
            conversation_id="conv1",
            query="many",
            max_results=3,
        )

        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_search_updates_session_state(self):
        page = _StubPage(url="https://www.google.com/search?q=state")
        worker = _StubWorker(search_provider="google", search_base_url="https://www.google.com/search")
        worker._session = _StubSession(page=page)
        worker._session.current_url = page.url
        worker.session_manager = _StubSessionManager(session=worker._session, new_page_result=page)
        worker._new_page_result = page
        worker._evaluate_result = [
            {"title": "R1", "url": "https://r1.com", "snippet": ""},
        ]
        search = BrowserSearch(worker)

        await search.search(conversation_id="conv1", query="state", max_results=5)

        # The search URL includes additional parameters
        assert "q=state" in worker._session.current_url
        assert worker._session._touched is True

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(self):
        search, worker = _make_search()
        worker._new_page_result = _StubPage()
        worker._evaluate_result = []

        result = await search.search(conversation_id="conv1", query="empty", max_results=5)

        assert result["results"] == []


# ---------------------------------------------------------------------------
# Tests — backward-compat delegations on worker
# ---------------------------------------------------------------------------


class TestBackwardCompatDelegations:
    def test_worker_search_url_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        from personagent.infrastructure.browser.search import BrowserSearch
        worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
        search = BrowserSearch(worker)
        url = search.search_url("hello world")
        assert "hello+world" in url

    def test_worker_search_provider_label_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
        assert isinstance(worker.search_provider_label, str)
        assert len(worker.search_provider_label) > 0
