"""Unit tests for personagent.infrastructure.browser.page_helpers (Slice 14)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from personagent.infrastructure.browser.page_helpers import PageHelpers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker.timeout_ms = 30_000
    worker._evaluate_page = AsyncMock(return_value=None)
    worker._raw_runtime_evaluate_value = AsyncMock(return_value=None)
    return worker


def _make_helpers() -> tuple[PageHelpers, MagicMock]:
    worker = _make_worker()
    return PageHelpers(worker), worker


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# wait_for_page_load_complete
# ---------------------------------------------------------------------------

class TestWaitForPageLoadComplete:
    def test_calls_wait_for_load_state(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()
        _run(helpers.wait_for_page_load_complete(page))
        page.wait_for_load_state.assert_awaited_once_with("load", timeout=5_000)

    def test_custom_timeout(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()
        _run(helpers.wait_for_page_load_complete(page, timeout_ms=2_000))
        page.wait_for_load_state.assert_awaited_once_with("load", timeout=2_000)

    def test_no_wait_for_load_state(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        _run(helpers.wait_for_page_load_complete(page))

    def test_exception_suppressed(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))
        _run(helpers.wait_for_page_load_complete(page))


# ---------------------------------------------------------------------------
# wait_for_page_visual_ready
# ---------------------------------------------------------------------------

class TestWaitForPageVisualReady:
    def test_returns_default_metrics_on_no_script_result(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(return_value=None)
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        result = _run(helpers.wait_for_page_visual_ready(page))
        assert result["style_ready"] is True
        assert result["stylesheet_count"] == 0
        assert result["fonts_ready"] is True

    def test_returns_script_metrics(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(return_value={
            "style_ready": False,
            "stylesheet_count": 3,
            "stylesheet_loaded_count": 2,
            "fonts_ready": False,
        })
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        result = _run(helpers.wait_for_page_visual_ready(page))
        assert result["style_ready"] is False
        assert result["stylesheet_count"] == 3
        assert result["stylesheet_loaded_count"] == 2
        assert result["fonts_ready"] is False

    def test_exception_returns_defaults(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(side_effect=Exception("fail"))
        page = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        result = _run(helpers.wait_for_page_visual_ready(page))
        assert result["style_ready"] is True


# ---------------------------------------------------------------------------
# safe_title
# ---------------------------------------------------------------------------

class TestSafeTitle:
    def test_returns_title(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.title = AsyncMock(return_value="  My Page  ")
        result = _run(helpers.safe_title(page))
        assert result == "My Page"

    def test_returns_empty_on_timeout(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.title = AsyncMock(side_effect=TimeoutError("timed out"))
        result = _run(helpers.safe_title(page))
        assert result == ""

    def test_returns_empty_on_exception(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.title = AsyncMock(side_effect=RuntimeError("broken"))
        result = _run(helpers.safe_title(page))
        assert result == ""

    def test_returns_empty_for_none_title(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.title = AsyncMock(return_value=None)
        result = _run(helpers.safe_title(page))
        assert result == ""


# ---------------------------------------------------------------------------
# safe_title_for_url
# ---------------------------------------------------------------------------

class TestSafeTitleForUrl:
    def test_returns_title(self) -> None:
        helpers, worker = _make_helpers()
        worker._raw_runtime_evaluate_value = AsyncMock(return_value="  Page Title  ")
        result = _run(helpers.safe_title_for_url("https://example.com"))
        assert result == "Page Title"
        worker._raw_runtime_evaluate_value.assert_awaited_once()

    def test_returns_empty_for_non_string(self) -> None:
        helpers, worker = _make_helpers()
        worker._raw_runtime_evaluate_value = AsyncMock(return_value=42)
        result = _run(helpers.safe_title_for_url("https://example.com"))
        assert result == ""

    def test_returns_empty_for_none(self) -> None:
        helpers, worker = _make_helpers()
        worker._raw_runtime_evaluate_value = AsyncMock(return_value=None)
        result = _run(helpers.safe_title_for_url("https://example.com"))
        assert result == ""


# ---------------------------------------------------------------------------
# Backward-compat delegations
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_wait_for_page_load_complete_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = MagicMock(spec=[])
        _run(worker.page_helpers.wait_for_page_load_complete(page))

    def test_worker_safe_title_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = MagicMock()
        page.title = AsyncMock(return_value="Test")
        result = _run(worker.page_helpers.safe_title(page))
        assert result == "Test"
