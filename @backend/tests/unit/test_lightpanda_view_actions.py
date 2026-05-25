"""Unit tests for BrowserViewActions extracted from lightpanda.py (Slice 7)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.view_actions import BrowserViewActions

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

_VIEW_SNAPSHOT_RESULT: dict[str, Any] = {
    "type": "browser_view",
    "url": "https://example.com",
    "html": "<html></html>",
}


class _StubMouse:
    def __init__(self) -> None:
        self.click = AsyncMock()
        self.wheel = AsyncMock()


class _StubKeyboard:
    def __init__(self) -> None:
        self.type = AsyncMock()
        self.press = AsyncMock()


class _StubPage:
    def __init__(self, url: str = "https://example.com") -> None:
        self.url = url
        self.mouse = _StubMouse()
        self.keyboard = _StubKeyboard()
        self.reload = AsyncMock()
        self.go_back = AsyncMock()
        self.go_forward = AsyncMock()
        self.wait_for_timeout = AsyncMock()


class _StubSession:
    def __init__(self, page: _StubPage | None = None) -> None:
        self.page = page or _StubPage()
        self.current_url = "https://example.com"
        self.last_open_url = "https://example.com"
        self.current_page_id: str | None = None
        self._touched = False

    def touch(self) -> None:
        self._touched = True


class _StubSnapshot:
    def __init__(self) -> None:
        self.browser_view_snapshot = AsyncMock(return_value=dict(_VIEW_SNAPSHOT_RESULT))
        self.browser_element_map = AsyncMock(return_value=[])
        self.enrich_browser_element_map = MagicMock(return_value=[])


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for BrowserViewActions tests."""

    def __init__(self) -> None:
        self._session = _StubSession()
        self.snapshot = _StubSnapshot()
        self.timeout_ms = 5_000
        self._element_map_cache: dict[str, Any] = {}
        self._goto_urls: list[str] = []
        # Module stubs
        self.session_manager = _StubSessionManager(self._session)
        self.element_helpers = _StubElementHelpers()
        self.page_helpers = _StubPageHelpers()
        self.console = _StubConsole()
        self.opened_pages = _StubOpenedPages()
        self.search_result_cache = _StubSearchResultCache()

        self._get_session = AsyncMock(return_value=self._session)
        self._goto = AsyncMock()
        self._goto_page = AsyncMock()
        self._preferred_session_page = MagicMock(return_value=self._session.page)
        self._ensure_session_page_alias = MagicMock()
        self._remember_current_url = MagicMock()
        self._wait_for_page_visual_ready = AsyncMock()
        self._wait_for_page_load_complete = AsyncMock()
        self._set_page_viewport = AsyncMock()
        self._evaluate_page = AsyncMock(return_value={"ok": True})
        self._element_target = MagicMock(return_value={"selector": "[data-pa-node-id='n1']"})
        self._action_context_for_element = AsyncMock(return_value=self._session.page)
        self._upload_files = AsyncMock(return_value={"ok": True})
        self._browser_action_target_payload = MagicMock(return_value={"node_id": "n1"})


class _StubSessionManager:
    def __init__(self, session: _StubSession) -> None:
        self._session = session
        self.ensure_session_page_alias = MagicMock(return_value="p1")

    async def get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        return self._session, self._session.page, page_id or "p1"


class _StubElementHelpers:
    async def safe_user_agent(self, page: Any) -> str:
        return "Mozilla/5.0"

    async def set_page_viewport(self, page: Any, width: int, height: int) -> None:
        pass


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
    def __init__(self) -> None:
        self.remember_current_url = MagicMock()

    def latest_cached_search_results(self, conversation_id: str) -> list[Any]:
        return []

    def cleanup_search_cache(self, now: float) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make() -> tuple[BrowserViewActions, _StubWorker]:
    worker = _StubWorker()
    va = BrowserViewActions(worker)
    return va, worker


# ---------------------------------------------------------------------------
# Tests — view_navigate
# ---------------------------------------------------------------------------


class TestViewNavigate:
    @pytest.mark.asyncio
    async def test_navigates_and_returns_snapshot(self):
        va, worker = _make()
        result = await va.view_navigate(
            browser_id="b1",
            url="https://example.com/page",
            width=1280,
            height=720,
        )
        assert result["type"] == "browser_view"
        worker._goto.assert_awaited_once()
        worker.snapshot.browser_view_snapshot.assert_awaited_once()
        assert worker._session._touched

    @pytest.mark.asyncio
    async def test_updates_session_url(self):
        va, worker = _make()
        await va.view_navigate(
            browser_id="b1", url="https://new.example.com", width=800, height=600
        )
        worker.search_result_cache.remember_current_url.assert_called_once()
        worker.session_manager.ensure_session_page_alias.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — view_history
# ---------------------------------------------------------------------------


class TestViewHistory:
    @pytest.mark.asyncio
    async def test_goes_back(self):
        va, worker = _make()
        result = await va.view_history(
            browser_id="b1", direction=-1, width=1280, height=720
        )
        assert result["type"] == "browser_view"
        worker._session.page.go_back.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_goes_forward(self):
        va, worker = _make()
        result = await va.view_history(
            browser_id="b1", direction=1, width=1280, height=720
        )
        assert result["type"] == "browser_view"
        worker._session.page.go_forward.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_no_history_operation(self):
        va, worker = _make()
        worker._session.page.go_back = None
        worker._session.page.go_forward = None
        with pytest.raises(BrowserUnavailableError, match="history navigation"):
            await va.view_history(browser_id="b1", direction=-1, width=800, height=600)


# ---------------------------------------------------------------------------
# Tests — view_reload
# ---------------------------------------------------------------------------


class TestViewReload:
    @pytest.mark.asyncio
    async def test_reloads_page(self):
        va, worker = _make()
        result = await va.view_reload(browser_id="b1", width=1280, height=720)
        assert result["type"] == "browser_view"
        worker._session.page.reload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_goto_on_reload_failure(self):
        va, worker = _make()
        worker._session.page.reload = AsyncMock(side_effect=Exception("reload failed"))
        worker._session.page.url = "https://example.com/fallback"
        result = await va.view_reload(browser_id="b1", width=800, height=600)
        assert result["type"] == "browser_view"
        worker._goto_page.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_no_reload_and_no_url(self):
        va, worker = _make()
        worker._session.page.reload = None
        worker._session.page.url = ""
        worker._session.current_url = ""
        worker._session.last_open_url = ""
        with pytest.raises(BrowserUnavailableError, match="reload is unavailable"):
            await va.view_reload(browser_id="b1", width=800, height=600)


# ---------------------------------------------------------------------------
# Tests — view_click
# ---------------------------------------------------------------------------


class TestViewClick:
    @pytest.mark.asyncio
    async def test_clicks_and_returns_snapshot(self):
        va, worker = _make()
        result = await va.view_click(
            browser_id="b1", x=100.0, y=200.0, width=1280, height=720
        )
        assert result["type"] == "browser_view"
        worker._session.page.mouse.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_if_no_mouse(self):
        va, worker = _make()
        worker._session.page.mouse = None  # type: ignore[assignment]
        with pytest.raises(BrowserUnavailableError, match="pointer interaction"):
            await va.view_click(browser_id="b1", x=10, y=10, width=800, height=600)

    @pytest.mark.asyncio
    async def test_clamps_coords_to_viewport(self):
        va, worker = _make()
        await va.view_click(
            browser_id="b1", x=99999.0, y=-10.0, width=800, height=600
        )
        args = worker._session.page.mouse.click.call_args
        assert args[0][0] <= 1280
        assert args[0][1] >= 0.0


# ---------------------------------------------------------------------------
# Tests — view_key
# ---------------------------------------------------------------------------


class TestViewKey:
    @pytest.mark.asyncio
    async def test_types_text(self):
        va, worker = _make()
        result = await va.view_key(
            browser_id="b1", width=800, height=600, text="hello"
        )
        assert result["type"] == "browser_view"
        worker._session.page.keyboard.type.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_presses_key(self):
        va, worker = _make()
        result = await va.view_key(
            browser_id="b1", width=800, height=600, key="Enter"
        )
        assert result["type"] == "browser_view"
        worker._session.page.keyboard.press.assert_awaited_once_with("Enter")

    @pytest.mark.asyncio
    async def test_raises_if_no_keyboard(self):
        va, worker = _make()
        worker._session.page.keyboard = None
        with pytest.raises(BrowserUnavailableError, match="keyboard"):
            await va.view_key(browser_id="b1", width=800, height=600, text="x")


# ---------------------------------------------------------------------------
# Tests — view_scroll
# ---------------------------------------------------------------------------


class TestViewScroll:
    @pytest.mark.asyncio
    async def test_scrolls_with_wheel(self):
        va, worker = _make()
        result = await va.view_scroll(
            browser_id="b1", delta_x=0.0, delta_y=100.0, width=800, height=600
        )
        assert result["type"] == "browser_view"
        worker._session.page.mouse.wheel.assert_awaited_once_with(0.0, 100.0)

    @pytest.mark.asyncio
    async def test_falls_back_to_scrollby_script(self):
        va, worker = _make()
        worker._session.page.mouse.wheel = None
        result = await va.view_scroll(
            browser_id="b1", delta_x=10.0, delta_y=50.0, width=800, height=600
        )
        assert result["type"] == "browser_view"
        worker._evaluate_page.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests — view_act
# ---------------------------------------------------------------------------


class TestViewAct:
    @pytest.mark.asyncio
    async def test_click_action(self):
        va, worker = _make()
        result = await va.view_act(
            browser_id="b1",
            node_id="n1",
            action="click",
            width=1280,
            height=720,
        )
        assert result["type"] == "browser_view"
        assert "last_action" in result
        assert result["last_action"]["action"] == "click"

    @pytest.mark.asyncio
    async def test_raises_on_empty_node_id(self):
        va, _ = _make()
        with pytest.raises(BrowserError, match="requires node_id"):
            await va.view_act(
                browser_id="b1", node_id="", action="click", width=800, height=600
            )

    @pytest.mark.asyncio
    async def test_raises_on_unsupported_action(self):
        va, _ = _make()
        with pytest.raises(BrowserError, match="must be one of"):
            await va.view_act(
                browser_id="b1",
                node_id="n1",
                action="invalid_action",
                width=800,
                height=600,
            )

    @pytest.mark.asyncio
    async def test_raises_on_failed_action(self):
        va, worker = _make()
        worker._evaluate_page = AsyncMock(return_value={"ok": False, "reason": "element not found"})
        with pytest.raises(BrowserError, match="element not found"):
            await va.view_act(
                browser_id="b1",
                node_id="n1",
                action="click",
                width=800,
                height=600,
            )

    @pytest.mark.asyncio
    async def test_upload_action_calls_upload_files(self):
        va, worker = _make()
        await va.view_act(
            browser_id="b1",
            node_id="n1",
            action="upload",
            width=800,
            height=600,
            files=["/tmp/test.txt"],
        )
        worker._upload_files.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fill_action_includes_value_in_last_action(self):
        va, worker = _make()
        result = await va.view_act(
            browser_id="b1",
            node_id="n1",
            action="fill",
            width=800,
            height=600,
            value="hello",
        )
        assert result["last_action"]["value"] == "hello"


# ---------------------------------------------------------------------------
# Tests — backward-compat delegations
# ---------------------------------------------------------------------------


class TestBackwardCompatDelegations:
    @pytest.mark.asyncio
    async def test_worker_view_navigate_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
        assert hasattr(worker, "view_actions")
        assert hasattr(worker.view_actions, "view_navigate")
        assert hasattr(worker.view_actions, "view_history")
        assert hasattr(worker.view_actions, "view_reload")
        assert hasattr(worker.view_actions, "view_click")
        assert hasattr(worker.view_actions, "view_key")
        assert hasattr(worker.view_actions, "view_scroll")
        assert hasattr(worker.view_actions, "view_act")
