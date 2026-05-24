"""Unit tests for personagent.infrastructure.browser.block_detection (Slice 13)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.infrastructure.browser.block_detection import BlockDetector
from personagent.infrastructure.browser.models import BrowserBlockedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker._evaluate_page = AsyncMock(return_value="")
    worker._safe_title = AsyncMock(return_value="")
    return worker


def _make_detector() -> tuple[BlockDetector, MagicMock]:
    worker = _make_worker()
    return BlockDetector(worker), worker


def _make_page(url: str = "") -> MagicMock:
    page = MagicMock()
    page.url = url
    return page


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Google block detection
# ---------------------------------------------------------------------------

class TestGoogleBlocked:
    def test_not_google_url_passes(self) -> None:
        detector, _ = _make_detector()
        page = _make_page("https://example.com")
        _run(detector.raise_if_google_blocked(page))

    def test_sorry_index_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.google.com/sorry/index?continue=...")
        worker._safe_title = AsyncMock(return_value="Google Sorry")
        worker._evaluate_page = AsyncMock(return_value="unusual traffic from your computer")
        with pytest.raises(BrowserBlockedError, match="Google blocked"):
            _run(detector.raise_if_google_blocked(page))

    def test_google_captcha_markers_raise(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.google.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="Google")
        worker._evaluate_page = AsyncMock(return_value="Our systems have detected unusual traffic")
        with pytest.raises(BrowserBlockedError) as exc_info:
            _run(detector.raise_if_google_blocked(page))
        assert exc_info.value.details["provider"] == "google"
        assert exc_info.value.details["reason"] == "captcha_or_unusual_traffic"

    def test_google_clean_page_passes(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.google.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="test - Google Search")
        worker._evaluate_page = AsyncMock(return_value="Here are your search results")
        _run(detector.raise_if_google_blocked(page))

    def test_google_consent_marker_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://consent.google.com/ml?continue=...")
        worker._safe_title = AsyncMock(return_value="Before you continue to Google")
        worker._evaluate_page = AsyncMock(return_value="Before you continue")
        with pytest.raises(BrowserBlockedError):
            _run(detector.raise_if_google_blocked(page))


# ---------------------------------------------------------------------------
# Bing block detection
# ---------------------------------------------------------------------------

class TestBingBlocked:
    def test_not_bing_url_passes(self) -> None:
        detector, _ = _make_detector()
        page = _make_page("https://example.com")
        _run(detector.raise_if_bing_blocked(page))

    def test_bing_captcha_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.bing.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="Bing")
        worker._evaluate_page = AsyncMock(return_value="verify you are human")
        with pytest.raises(BrowserBlockedError) as exc_info:
            _run(detector.raise_if_bing_blocked(page))
        assert exc_info.value.details["provider"] == "bing"
        assert exc_info.value.details["reason"] == "captcha_or_automated_traffic"

    def test_bing_clean_page_passes(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.bing.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="test - Bing")
        worker._evaluate_page = AsyncMock(return_value="Web results for test")
        _run(detector.raise_if_bing_blocked(page))

    def test_bing_robot_check_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.bing.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="Bing")
        worker._evaluate_page = AsyncMock(return_value="are you a robot")
        with pytest.raises(BrowserBlockedError):
            _run(detector.raise_if_bing_blocked(page))


# ---------------------------------------------------------------------------
# Yahoo block detection
# ---------------------------------------------------------------------------

class TestYahooBlocked:
    def test_not_yahoo_url_passes(self) -> None:
        detector, _ = _make_detector()
        page = _make_page("https://example.com")
        _run(detector.raise_if_yahoo_blocked(page))

    def test_yahoo_captcha_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://search.yahoo.com/search?p=test")
        worker._safe_title = AsyncMock(return_value="Yahoo Search")
        worker._evaluate_page = AsyncMock(return_value="verify you are human")
        with pytest.raises(BrowserBlockedError) as exc_info:
            _run(detector.raise_if_yahoo_blocked(page))
        assert exc_info.value.details["provider"] == "yahoo"
        assert exc_info.value.details["reason"] == "captcha_or_automated_traffic"

    def test_yahoo_clean_page_passes(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://search.yahoo.com/search?p=test")
        worker._safe_title = AsyncMock(return_value="test - Yahoo Search Results")
        worker._evaluate_page = AsyncMock(return_value="Web results for test")
        _run(detector.raise_if_yahoo_blocked(page))

    def test_yahoo_automated_request_raises(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://search.yahoo.com/search?p=test")
        worker._safe_title = AsyncMock(return_value="Yahoo Search")
        worker._evaluate_page = AsyncMock(return_value="automated requests detected")
        with pytest.raises(BrowserBlockedError):
            _run(detector.raise_if_yahoo_blocked(page))


# ---------------------------------------------------------------------------
# Composite check
# ---------------------------------------------------------------------------

class TestSearchBlocked:
    def test_clean_page_passes(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://example.com")
        worker._safe_title = AsyncMock(return_value="Example")
        _run(detector.raise_if_search_blocked(page))

    def test_google_block_propagates(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.google.com/sorry/index")
        worker._safe_title = AsyncMock(return_value="Google Sorry")
        worker._evaluate_page = AsyncMock(return_value="unusual traffic")
        with pytest.raises(BrowserBlockedError, match="Google"):
            _run(detector.raise_if_search_blocked(page))


# ---------------------------------------------------------------------------
# Error attributes
# ---------------------------------------------------------------------------

class TestBlockedErrorAttributes:
    def test_error_has_provider_and_reason(self) -> None:
        detector, worker = _make_detector()
        page = _make_page("https://www.bing.com/search?q=test")
        worker._safe_title = AsyncMock(return_value="Bing")
        worker._evaluate_page = AsyncMock(return_value="please solve the challenge")
        with pytest.raises(BrowserBlockedError) as exc_info:
            _run(detector.raise_if_bing_blocked(page))
        err = exc_info.value
        assert err.details["provider"] == "bing"
        assert err.details["reason"] == "captcha_or_automated_traffic"
        assert err.details["url"] == "https://www.bing.com/search?q=test"
        assert err.details["title"] == "Bing"
        assert "solve the challenge" in (err.details.get("sample") or "")


# ---------------------------------------------------------------------------
# Backward-compat delegations
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_raise_if_search_blocked_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = _make_page("https://example.com")
        _run(worker._raise_if_search_blocked(page))

    def test_worker_raise_if_google_blocked_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = _make_page("https://example.com")
        _run(worker._raise_if_google_blocked(page))
