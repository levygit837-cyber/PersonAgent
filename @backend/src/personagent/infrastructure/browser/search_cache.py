"""Search-result caching and lookup for the browser worker.

Extracted from ``lightpanda.py`` (Slice 11).  The ``SearchResultCache``
helper owns:

* Caching search snapshots per conversation (ring-buffer)
* Lookup by search_id, result index, or URL equivalence
* Current-URL tracking per conversation
* TTL-based cache cleanup
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserSearchResult,
    BrowserSearchSnapshot,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
    from personagent.infrastructure.browser.models import BrowserSession

_MAX_CACHED_SEARCHES_PER_CONVERSATION = 8


class SearchResultCache:
    """Manages search-result snapshots, URL tracking, and cache cleanup."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def cache_search_results(
        self,
        *,
        conversation_id: str,
        query: str,
        search_url: str,
        results: list[BrowserSearchResult],
    ) -> BrowserSearchSnapshot:
        raw_id = (
            f"{conversation_id}\n{query}\n{search_url}\n{time.monotonic_ns()}"
        )
        search_id = (
            f"search_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        )
        snapshot = BrowserSearchSnapshot(
            search_id=search_id,
            query=query,
            search_url=search_url,
            provider=self._w.search_provider,
            results=self.copy_search_results(results),
        )
        snapshots = self._w._search_cache.setdefault(conversation_id, [])
        snapshots.insert(0, snapshot)
        del snapshots[_MAX_CACHED_SEARCHES_PER_CONVERSATION:]
        return snapshot

    def latest_cached_search_results(
        self, conversation_id: str
    ) -> list[BrowserSearchResult]:
        snapshots = self._w._search_cache.get(conversation_id) or []
        if not snapshots:
            return []
        return self.copy_search_results(snapshots[0].results)

    @staticmethod
    def copy_search_results(
        results: list[BrowserSearchResult],
    ) -> list[BrowserSearchResult]:
        return [
            BrowserSearchResult(
                index=result.index,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
            )
            for result in results
        ]

    # ------------------------------------------------------------------
    # URL tracking
    # ------------------------------------------------------------------

    def remember_current_url(
        self, conversation_id: str, url: str | None
    ) -> None:
        url = _clean_browser_url(str(url or ""))
        if not url or url == "about:blank":
            return
        self._w._current_url_cache[conversation_id] = url

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def result_url(
        self,
        conversation_id: str,
        session: BrowserSession,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> tuple[str, str | None]:
        if search_id:
            for snapshot in self._w._search_cache.get(
                conversation_id, []
            ):
                if snapshot.search_id != search_id:
                    continue
                for result in snapshot.results:
                    if result.index == result_index:
                        return (
                            _clean_browser_url(result.url),
                            snapshot.search_id,
                        )
                raise BrowserError(
                    f"No browser search result with index {result_index} "
                    f"in search_id {search_id}."
                )
            raise BrowserError(
                f"No cached browser search with search_id {search_id}. "
                f"Run BrowserSearch first."
            )

        for snapshot in self._w._search_cache.get(conversation_id, []):
            for result in snapshot.results:
                if result.index == result_index:
                    return (
                        _clean_browser_url(result.url),
                        snapshot.search_id,
                    )

        for result in session.search_results:
            if result.index == result_index:
                return _clean_browser_url(result.url), None
        raise BrowserError(
            f"No browser search result with index {result_index}. "
            f"Run BrowserSearch first."
        )

    def result_title(
        self,
        conversation_id: str,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> str:
        snapshots = self._w._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if result.index == result_index:
                    return result.title
        return ""

    def match_search_result_url(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str | None:
        snapshots = self._w._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if _urls_equivalent(url, result.url):
                    return snapshot.search_id
        return None

    def match_search_result_title(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str:
        snapshots = self._w._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if _urls_equivalent(url, result.url):
                    return result.title
        return ""

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_search_cache(self, now: float) -> None:
        for conversation_id, snapshots in list(
            self._w._search_cache.items()
        ):
            fresh = [
                snapshot
                for snapshot in snapshots
                if now - snapshot.created_at <= self._w.session_ttl_seconds
            ][:_MAX_CACHED_SEARCHES_PER_CONVERSATION]
            if fresh:
                self._w._search_cache[conversation_id] = fresh
            else:
                self._w._search_cache.pop(conversation_id, None)
                if conversation_id not in self._w._sessions:
                    self._w._current_url_cache.pop(conversation_id, None)
                    self._w._last_open_cache.pop(conversation_id, None)
                    self._w._opened_pages_cache.pop(
                        conversation_id, None
                    )
                    self._w._element_map_cache.pop(conversation_id, None)
                    self._w._console_cache.pop(conversation_id, None)
                    self._w._cooperation_event_cache.pop(
                        conversation_id, None
                    )
