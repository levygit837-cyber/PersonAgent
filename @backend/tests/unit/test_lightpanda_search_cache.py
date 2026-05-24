"""Unit tests for personagent.infrastructure.browser.search_cache (Slice 11)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserSearchResult,
    BrowserSearchSnapshot,
)
from personagent.infrastructure.browser.search_cache import SearchResultCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker._search_cache = {}
    worker._current_url_cache = {}
    worker._last_open_cache = {}
    worker._opened_pages_cache = {}
    worker._element_map_cache = {}
    worker._console_cache = {}
    worker._cooperation_event_cache = {}
    worker._sessions = {}
    worker.search_provider = "yahoo"
    worker.session_ttl_seconds = 600
    return worker


def _make_cache() -> tuple[SearchResultCache, MagicMock]:
    worker = _make_worker()
    return SearchResultCache(worker), worker


def _make_results(count: int = 3) -> list[BrowserSearchResult]:
    return [
        BrowserSearchResult(
            index=i, title=f"Result {i}", url=f"https://r{i}.com", snippet=f"Snippet {i}"
        )
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# cache_search_results
# ---------------------------------------------------------------------------

class TestCacheSearchResults:
    def test_creates_snapshot(self) -> None:
        cache, worker = _make_cache()
        snap = cache.cache_search_results(
            conversation_id="c1", query="test", search_url="https://search.yahoo.com/search?p=test",
            results=_make_results(),
        )
        assert snap.search_id.startswith("search_")
        assert snap.query == "test"
        assert snap.provider == "yahoo"
        assert len(snap.results) == 3
        assert len(worker._search_cache["c1"]) == 1

    def test_latest_first(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q1", search_url="u1", results=_make_results(1),
        )
        snap2 = cache.cache_search_results(
            conversation_id="c1", query="q2", search_url="u2", results=_make_results(2),
        )
        assert worker._search_cache["c1"][0].search_id == snap2.search_id

    def test_limits_to_8(self) -> None:
        cache, worker = _make_cache()
        for i in range(12):
            cache.cache_search_results(
                conversation_id="c1", query=f"q{i}", search_url=f"u{i}", results=_make_results(1),
            )
        assert len(worker._search_cache["c1"]) == 8

    def test_results_are_copies(self) -> None:
        cache, worker = _make_cache()
        original = _make_results(1)
        snap = cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=original,
        )
        assert snap.results[0] is not original[0]
        assert snap.results[0].title == original[0].title


# ---------------------------------------------------------------------------
# latest_cached_search_results
# ---------------------------------------------------------------------------

class TestLatestCachedSearchResults:
    def test_returns_latest(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q1", search_url="u1",
            results=[BrowserSearchResult(index=1, title="Old", url="https://old.com", snippet="old")],
        )
        cache.cache_search_results(
            conversation_id="c1", query="q2", search_url="u2",
            results=[BrowserSearchResult(index=1, title="New", url="https://new.com", snippet="new")],
        )
        latest = cache.latest_cached_search_results("c1")
        assert len(latest) == 1
        assert latest[0].title == "New"

    def test_returns_empty_when_no_cache(self) -> None:
        cache, _ = _make_cache()
        assert cache.latest_cached_search_results("c1") == []


# ---------------------------------------------------------------------------
# copy_search_results
# ---------------------------------------------------------------------------

class TestCopySearchResults:
    def test_deep_copies(self) -> None:
        original = _make_results(2)
        copied = SearchResultCache.copy_search_results(original)
        assert len(copied) == 2
        assert copied[0] is not original[0]
        assert copied[0].url == original[0].url


# ---------------------------------------------------------------------------
# remember_current_url
# ---------------------------------------------------------------------------

class TestRememberCurrentUrl:
    def test_stores_url(self) -> None:
        cache, worker = _make_cache()
        cache.remember_current_url("c1", "https://example.com")
        assert worker._current_url_cache["c1"] == "https://example.com"

    def test_ignores_blank(self) -> None:
        cache, worker = _make_cache()
        cache.remember_current_url("c1", "about:blank")
        assert "c1" not in worker._current_url_cache

    def test_ignores_empty(self) -> None:
        cache, worker = _make_cache()
        cache.remember_current_url("c1", "")
        assert "c1" not in worker._current_url_cache

    def test_ignores_none(self) -> None:
        cache, worker = _make_cache()
        cache.remember_current_url("c1", None)
        assert "c1" not in worker._current_url_cache


# ---------------------------------------------------------------------------
# result_url
# ---------------------------------------------------------------------------

class TestResultUrl:
    def test_finds_by_search_id(self) -> None:
        cache, worker = _make_cache()
        snap = cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        session = MagicMock()
        url, sid = cache.result_url("c1", session, 2, search_id=snap.search_id)
        assert "r2.com" in url
        assert sid == snap.search_id

    def test_finds_across_snapshots(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        session = MagicMock()
        url, sid = cache.result_url("c1", session, 1)
        assert "r1.com" in url

    def test_falls_back_to_session(self) -> None:
        cache, worker = _make_cache()
        session = MagicMock()
        session.search_results = [
            BrowserSearchResult(index=5, title="Session", url="https://session.com", snippet="s"),
        ]
        url, sid = cache.result_url("c1", session, 5)
        assert "session.com" in url
        assert sid is None

    def test_raises_when_not_found(self) -> None:
        cache, worker = _make_cache()
        session = MagicMock()
        session.search_results = []
        with pytest.raises(BrowserError, match="No browser search result"):
            cache.result_url("c1", session, 99)

    def test_raises_when_search_id_not_found(self) -> None:
        cache, worker = _make_cache()
        session = MagicMock()
        with pytest.raises(BrowserError, match="No cached browser search"):
            cache.result_url("c1", session, 1, search_id="nonexistent")

    def test_raises_when_index_not_in_search_id(self) -> None:
        cache, worker = _make_cache()
        snap = cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(2),
        )
        session = MagicMock()
        with pytest.raises(BrowserError, match="No browser search result with index 99"):
            cache.result_url("c1", session, 99, search_id=snap.search_id)


# ---------------------------------------------------------------------------
# result_title
# ---------------------------------------------------------------------------

class TestResultTitle:
    def test_finds_title(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        assert cache.result_title("c1", 2) == "Result 2"

    def test_returns_empty_when_not_found(self) -> None:
        cache, _ = _make_cache()
        assert cache.result_title("c1", 99) == ""


# ---------------------------------------------------------------------------
# match_search_result_url / match_search_result_title
# ---------------------------------------------------------------------------

class TestMatchSearchResult:
    def test_match_url_found(self) -> None:
        cache, worker = _make_cache()
        snap = cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        sid = cache.match_search_result_url("c1", "https://r2.com")
        assert sid == snap.search_id

    def test_match_url_not_found(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        assert cache.match_search_result_url("c1", "https://notfound.com") is None

    def test_match_title_found(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        assert cache.match_search_result_title("c1", "https://r1.com") == "Result 1"

    def test_match_title_not_found(self) -> None:
        cache, worker = _make_cache()
        cache.cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(3),
        )
        assert cache.match_search_result_title("c1", "https://nope.com") == ""


# ---------------------------------------------------------------------------
# cleanup_search_cache
# ---------------------------------------------------------------------------

class TestCleanupSearchCache:
    def test_removes_expired(self) -> None:
        cache, worker = _make_cache()
        worker.session_ttl_seconds = 100
        snap = BrowserSearchSnapshot(
            search_id="old", query="q", search_url="u", provider="yahoo",
            results=[], created_at=time.monotonic() - 200,
        )
        worker._search_cache = {"c1": [snap]}
        cache.cleanup_search_cache(time.monotonic())
        assert "c1" not in worker._search_cache

    def test_keeps_fresh(self) -> None:
        cache, worker = _make_cache()
        worker.session_ttl_seconds = 1000
        snap = BrowserSearchSnapshot(
            search_id="fresh", query="q", search_url="u", provider="yahoo",
            results=[], created_at=time.monotonic(),
        )
        worker._search_cache = {"c1": [snap]}
        cache.cleanup_search_cache(time.monotonic())
        assert "c1" in worker._search_cache

    def test_cleans_related_caches_when_no_session(self) -> None:
        cache, worker = _make_cache()
        worker.session_ttl_seconds = 100
        snap = BrowserSearchSnapshot(
            search_id="old", query="q", search_url="u", provider="yahoo",
            results=[], created_at=time.monotonic() - 200,
        )
        worker._search_cache = {"c1": [snap]}
        worker._current_url_cache = {"c1": "https://x.com"}
        worker._last_open_cache = {"c1": MagicMock()}
        worker._opened_pages_cache = {"c1": []}
        worker._element_map_cache = {"c1": []}
        worker._console_cache = {"c1": {}}
        worker._cooperation_event_cache = {"c1": {}}
        worker._sessions = {}
        cache.cleanup_search_cache(time.monotonic())
        assert "c1" not in worker._current_url_cache
        assert "c1" not in worker._last_open_cache
        assert "c1" not in worker._opened_pages_cache

    def test_preserves_caches_when_session_exists(self) -> None:
        cache, worker = _make_cache()
        worker.session_ttl_seconds = 100
        snap = BrowserSearchSnapshot(
            search_id="old", query="q", search_url="u", provider="yahoo",
            results=[], created_at=time.monotonic() - 200,
        )
        worker._search_cache = {"c1": [snap]}
        worker._current_url_cache = {"c1": "https://x.com"}
        worker._sessions = {"c1": MagicMock()}
        cache.cleanup_search_cache(time.monotonic())
        assert "c1" in worker._current_url_cache


# ---------------------------------------------------------------------------
# Backward-compat delegations
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_cache_search_results_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        snap = worker._cache_search_results(
            conversation_id="c1", query="q", search_url="u", results=_make_results(1),
        )
        assert snap.search_id.startswith("search_")

    def test_worker_remember_current_url_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        worker._remember_current_url("c1", "https://example.com")
        assert worker._current_url_cache["c1"] == "https://example.com"

    def test_worker_result_title_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker._result_title("c1", 99) == ""
