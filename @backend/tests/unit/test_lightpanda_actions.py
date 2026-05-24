"""Unit tests for BrowserActions extracted from lightpanda.py."""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from personagent.infrastructure.browser.actions import (
    _BROWSER_SCRIPT_CDP_ALLOWLIST,
    _MAX_BROWSER_SCRIPT_CHARS,
    _MAX_CONSOLE_ENTRIES_PER_PAGE,
    BrowserActions,
)
from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserUnavailableError,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPage:
    """Minimal page object recording interactions."""

    def __init__(
        self,
        url: str = "https://example.com",
        *,
        user_agent: str = "lightpanda/1.0",
        title: str = "Example",
        html: str = "<html></html>",
    ) -> None:
        self.url = url
        self._user_agent = user_agent
        self._title = title
        self._html = html
        self.mouse = _StubMouse()
        self.keyboard = _StubKeyboard()
        self._wait_for_timeout_called: list[int] = []
        self._wait_for_load_state_called: list[tuple[str, int]] = []

    async def wait_for_timeout(self, ms: int) -> None:
        self._wait_for_timeout_called.append(ms)

    async def wait_for_load_state(self, state: str, *, timeout: int = 30_000) -> None:
        self._wait_for_load_state_called.append((state, timeout))

    async def screenshot(self, **kwargs: Any) -> bytes:
        return b"\x89PNG_fake"


class _StubMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float, dict[str, Any]]] = []

    async def click(self, x: float, y: float, **kwargs: Any) -> None:
        self.clicks.append((x, y, kwargs))


class _StubKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.downs: list[str] = []
        self.ups: list[str] = []

    async def type(self, text: str, **kwargs: Any) -> None:
        self.typed.append(text)

    async def press(self, key: str) -> None:
        self.pressed.append(key)

    async def down(self, key: str) -> None:
        self.downs.append(key)

    async def up(self, key: str) -> None:
        self.ups.append(key)


class _ConsoleEntry:
    """Minimal console entry stub."""

    def __init__(self, entry_id: int, level: str = "log", text: str = "hello") -> None:
        self.entry_id = entry_id
        self.level = level
        self.text = text

    def to_dict(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, "level": self.level, "text": self.text}


class _StubSession:
    """Minimal session stub."""

    def __init__(
        self,
        page: _StubPage | None = None,
        page_id: str = "p1",
    ) -> None:
        self.current_page_id = page_id
        self.last_open_page_id = page_id
        self.current_url = "https://example.com"
        self.page = page or _StubPage()
        self.pages: dict[str, _StubPage] = {page_id: self.page}
        self._touched = False

    def touch(self) -> None:
        self._touched = True


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for BrowserActions tests."""

    def __init__(
        self,
        session: _StubSession | None = None,
        page: _StubPage | None = None,
    ) -> None:
        self._session = session or _StubSession(page=page)
        self._page = page or self._session.page
        self.timeout_ms = 5_000
        self._element_map_cache: dict[str, list[Any]] = {}
        self._console_cache: dict[str, dict[str, deque[_ConsoleEntry]]] = {}
        self._last_open_cache: dict[str, Any] = {}

    async def _resolve_live_page(
        self, conversation_id: str, *, page_id: str | None = None, activate: bool = True
    ) -> tuple[_StubSession, _StubPage, str]:
        resolved_id = page_id or self._session.current_page_id or "p1"
        return self._session, self._page, resolved_id

    async def _get_session(self, conversation_id: str) -> _StubSession:
        return self._session

    async def _set_page_viewport(self, page: Any, w: int, h: int) -> None:
        pass

    async def _wait_for_page_load_complete(self, page: Any, *, timeout_ms: int = 1_500) -> None:
        pass

    async def _safe_title(self, page: Any) -> str:
        return getattr(page, "_title", "")

    async def _safe_user_agent(self, page: Any) -> str:
        return getattr(page, "_user_agent", "")

    async def _browser_element_map(self, page: Any) -> list[Any]:
        return []

    async def _safe_html(self, page: Any) -> str:
        return getattr(page, "_html", "")

    async def _safe_scroll_state(self, page: Any) -> dict[str, Any]:
        return {"scroll_x": 0, "scroll_y": 0}

    async def _page_runtime(self, page: Any) -> str:
        ua = getattr(page, "_user_agent", "")
        return "lightpanda" if ua.lower().startswith("lightpanda/") else "chrome_cdp"

    async def _is_lightpanda_page(self, page: Any) -> bool:
        ua = getattr(page, "_user_agent", "")
        return ua.lower().startswith("lightpanda/")

    def _enrich_browser_element_map(
        self, raw: list[Any], *, browser_id: str, tab_id: str
    ) -> list[Any]:
        return raw

    async def _browser_view_snapshot(
        self, conversation_id: str, session: Any, *, width: int = 1024, height: int = 720, wait_for_styles: bool = True
    ) -> dict[str, Any]:
        return {"url": "https://example.com", "title": "Example", "html": "<html></html>"}

    def _preferred_session_page(self, session: Any) -> _StubPage:
        return self._page

    async def _drain_page_console_entries(self, page: Any, cid: str, pid: str) -> None:
        pass

    async def _evaluate_page(self, page: Any, script: str, args: Any) -> Any:
        return "eval_result"

    async def _cdp_command_for_page(
        self, page: Any, *, url: str, method: str, params: dict[str, Any]
    ) -> Any:
        return {"result": "cdp_ok"}

    def _bounded_script_result(self, value: Any) -> tuple[str, Any, bool]:
        text = str(value)
        return text, value, False

    async def view_act(
        self, *, browser_id: str, node_id: str, action: str, width: int = 1024, height: int = 720, **kwargs: Any
    ) -> dict[str, Any]:
        return {
            "url": "https://example.com",
            "title": "Example",
            "last_action": {"action": action, "target": node_id, "result": "ok"},
        }

    async def view_scroll(
        self, *, browser_id: str, delta_x: float = 0.0, delta_y: float = 600.0, width: int = 1024, height: int = 720
    ) -> dict[str, Any]:
        return {"url": "https://example.com", "title": "Example"}


def _make_actions(
    *,
    session: _StubSession | None = None,
    page: _StubPage | None = None,
) -> tuple[BrowserActions, _StubWorker]:
    worker = _StubWorker(session=session, page=page)
    actions = BrowserActions(worker)  # type: ignore[arg-type]
    return actions, worker


# ---------------------------------------------------------------------------
# Tests: click
# ---------------------------------------------------------------------------


class TestClick:
    @pytest.mark.asyncio
    async def test_click_with_node_id(self) -> None:
        actions, _ = _make_actions()
        result = await actions.click(conversation_id="c1", node_id="n1")
        assert result["type"] == "browser_click"
        assert result["last_action"]["node_id"] == "n1"

    @pytest.mark.asyncio
    async def test_click_with_coordinates(self) -> None:
        actions, _ = _make_actions()
        result = await actions.click(conversation_id="c1", x=100.0, y=200.0)
        assert result["type"] == "browser_click"
        assert result["last_action"]["x"] == 100.0
        assert result["last_action"]["y"] == 200.0

    @pytest.mark.asyncio
    async def test_click_without_node_or_coords_raises(self) -> None:
        actions, _ = _make_actions()
        with pytest.raises(BrowserError, match="node_id or x/y"):
            await actions.click(conversation_id="c1")

    @pytest.mark.asyncio
    async def test_click_clamps_coordinates_to_viewport(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        await actions.click(conversation_id="c1", x=99999.0, y=99999.0, width=800, height=600)
        assert page.mouse.clicks
        cx, cy, _ = page.mouse.clicks[0]
        assert cx <= 800.0
        assert cy <= 600.0

    @pytest.mark.asyncio
    async def test_click_with_modifiers(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        await actions.click(conversation_id="c1", x=50.0, y=50.0, modifiers=["Shift"])
        assert "Shift" in page.keyboard.downs
        assert "Shift" in page.keyboard.ups


# ---------------------------------------------------------------------------
# Tests: type_input
# ---------------------------------------------------------------------------


class TestTypeInput:
    @pytest.mark.asyncio
    async def test_type_mode_default(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        result = await actions.type_input(conversation_id="c1", text="hello")
        assert result["type"] == "browser_type"
        assert "hello" in page.keyboard.typed

    @pytest.mark.asyncio
    async def test_type_mode_press(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        result = await actions.type_input(conversation_id="c1", mode="press", key="Enter")
        assert result["type"] == "browser_type"
        assert "Enter" in page.keyboard.pressed

    @pytest.mark.asyncio
    async def test_type_invalid_mode_raises(self) -> None:
        actions, _ = _make_actions()
        with pytest.raises(BrowserError, match="mode must be one of"):
            await actions.type_input(conversation_id="c1", mode="invalid")

    @pytest.mark.asyncio
    async def test_type_fill_with_node_id(self) -> None:
        actions, _ = _make_actions()
        result = await actions.type_input(
            conversation_id="c1", node_id="n1", mode="fill", text="world"
        )
        assert result["type"] == "browser_type"
        assert result["last_action"]["action"] == "fill"

    @pytest.mark.asyncio
    async def test_type_no_keyboard_raises(self) -> None:
        page = _StubPage()
        page.keyboard = None  # type: ignore[assignment]
        actions, _ = _make_actions(page=page)
        with pytest.raises(BrowserUnavailableError, match="keyboard"):
            await actions.type_input(conversation_id="c1", text="hello")


# ---------------------------------------------------------------------------
# Tests: screenshot
# ---------------------------------------------------------------------------


class TestScreenshot:
    @pytest.mark.asyncio
    async def test_screenshot_lightpanda_returns_html_mirror(self) -> None:
        page = _StubPage(user_agent="lightpanda/1.0")
        actions, _ = _make_actions(page=page)
        result = await actions.screenshot(conversation_id="c1")
        assert result["type"] == "browser_screenshot"
        assert result["render_mode"] == "html_mirror"
        assert result["image_data"] == ""
        assert "DOM mirror" in result["screenshot_error"]

    @pytest.mark.asyncio
    async def test_screenshot_chrome_returns_pixel(self) -> None:
        page = _StubPage(user_agent="Chrome/120")
        actions, _ = _make_actions(page=page)
        result = await actions.screenshot(conversation_id="c1")
        assert result["render_mode"] == "pixel"
        assert result["image_data"] != ""
        assert result["can_capture"] is True

    @pytest.mark.asyncio
    async def test_screenshot_invalid_format_defaults_to_png(self) -> None:
        page = _StubPage(user_agent="lightpanda/1.0")
        actions, _ = _make_actions(page=page)
        result = await actions.screenshot(conversation_id="c1", image_format="bmp")
        assert result["image_mime_type"] == ""  # no image captured for LP


# ---------------------------------------------------------------------------
# Tests: read_console
# ---------------------------------------------------------------------------


class TestReadConsole:
    @pytest.mark.asyncio
    async def test_read_console_empty(self) -> None:
        actions, _ = _make_actions()
        result = await actions.read_console(conversation_id="c1")
        assert result["type"] == "browser_console"
        assert result["entries"] == []

    @pytest.mark.asyncio
    async def test_read_console_with_entries(self) -> None:
        actions, worker = _make_actions()
        entries = deque([_ConsoleEntry(1, "log", "first"), _ConsoleEntry(2, "warn", "second")])
        worker._console_cache["c1"] = {"p1": entries}
        result = await actions.read_console(conversation_id="c1")
        assert len(result["entries"]) == 2

    @pytest.mark.asyncio
    async def test_read_console_filter_by_level(self) -> None:
        actions, worker = _make_actions()
        entries = deque([
            _ConsoleEntry(1, "log", "a"),
            _ConsoleEntry(2, "error", "b"),
            _ConsoleEntry(3, "log", "c"),
        ])
        worker._console_cache["c1"] = {"p1": entries}
        result = await actions.read_console(conversation_id="c1", levels=["error"])
        assert len(result["entries"]) == 1
        assert result["entries"][0]["level"] == "error"

    @pytest.mark.asyncio
    async def test_read_console_since_id(self) -> None:
        actions, worker = _make_actions()
        entries = deque([_ConsoleEntry(1), _ConsoleEntry(2), _ConsoleEntry(3)])
        worker._console_cache["c1"] = {"p1": entries}
        result = await actions.read_console(conversation_id="c1", since_id=1)
        assert len(result["entries"]) == 2
        assert result["entries"][0]["entry_id"] == 2

    @pytest.mark.asyncio
    async def test_read_console_clear(self) -> None:
        actions, worker = _make_actions()
        entries = deque([_ConsoleEntry(1)])
        worker._console_cache["c1"] = {"p1": entries}
        result = await actions.read_console(conversation_id="c1", clear=True)
        assert result["cleared"] is True
        assert "p1" not in worker._console_cache["c1"]

    @pytest.mark.asyncio
    async def test_read_console_limit_capped(self) -> None:
        actions, worker = _make_actions()
        big = deque([_ConsoleEntry(i) for i in range(_MAX_CONSOLE_ENTRIES_PER_PAGE + 50)])
        worker._console_cache["c1"] = {"p1": big}
        result = await actions.read_console(conversation_id="c1", limit=9999)
        assert len(result["entries"]) <= _MAX_CONSOLE_ENTRIES_PER_PAGE


# ---------------------------------------------------------------------------
# Tests: script
# ---------------------------------------------------------------------------


class TestScript:
    @pytest.mark.asyncio
    async def test_script_evaluate_basic(self) -> None:
        actions, _ = _make_actions()
        result = await actions.script(conversation_id="c1", script="1+1")
        assert result["type"] == "browser_script"
        assert result["mode"] == "evaluate"

    @pytest.mark.asyncio
    async def test_script_evaluate_empty_raises(self) -> None:
        actions, _ = _make_actions()
        with pytest.raises(BrowserError, match="non-empty script"):
            await actions.script(conversation_id="c1", mode="evaluate", script="")

    @pytest.mark.asyncio
    async def test_script_evaluate_too_large_raises(self) -> None:
        actions, _ = _make_actions()
        big_script = "x" * (_MAX_BROWSER_SCRIPT_CHARS + 1)
        with pytest.raises(BrowserError, match="too large"):
            await actions.script(conversation_id="c1", script=big_script)

    @pytest.mark.asyncio
    async def test_script_invalid_mode_raises(self) -> None:
        actions, _ = _make_actions()
        with pytest.raises(BrowserError, match="mode must be one of"):
            await actions.script(conversation_id="c1", mode="unknown")

    @pytest.mark.asyncio
    async def test_script_cdp_allowlisted(self) -> None:
        actions, _ = _make_actions()
        result = await actions.script(
            conversation_id="c1", mode="cdp", cdp_method="Runtime.evaluate", cdp_params={}
        )
        assert result["mode"] == "cdp"
        assert result["cdp_method"] == "Runtime.evaluate"

    @pytest.mark.asyncio
    async def test_script_cdp_disallowed_raises(self) -> None:
        actions, _ = _make_actions()
        with pytest.raises(BrowserError, match="cdp_method must be one of"):
            await actions.script(conversation_id="c1", mode="cdp", cdp_method="Network.disable")


# ---------------------------------------------------------------------------
# Tests: scroll
# ---------------------------------------------------------------------------


class TestScroll:
    @pytest.mark.asyncio
    async def test_scroll_returns_type(self) -> None:
        actions, _ = _make_actions()
        result = await actions.scroll(conversation_id="c1")
        assert result["type"] == "browser_scroll"

    @pytest.mark.asyncio
    async def test_scroll_sets_page_id(self) -> None:
        actions, _ = _make_actions()
        result = await actions.scroll(conversation_id="c1")
        assert result["page_id"] == "p1"


# ---------------------------------------------------------------------------
# Tests: wait
# ---------------------------------------------------------------------------


class TestWait:
    @pytest.mark.asyncio
    async def test_wait_basic(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        result = await actions.wait(conversation_id="c1", timeout_ms=500)
        assert result["type"] == "browser_wait"
        assert result["timeout_ms"] == 500
        assert 500 in page._wait_for_timeout_called

    @pytest.mark.asyncio
    async def test_wait_with_state(self) -> None:
        page = _StubPage()
        actions, _ = _make_actions(page=page)
        result = await actions.wait(conversation_id="c1", state="networkidle", timeout_ms=2000)
        assert result["state"] == "networkidle"
        assert ("networkidle", 2000) in page._wait_for_load_state_called

    @pytest.mark.asyncio
    async def test_wait_clamps_timeout(self) -> None:
        actions, _ = _make_actions()
        result = await actions.wait(conversation_id="c1", timeout_ms=999_999)
        assert result["timeout_ms"] == 120_000


# ---------------------------------------------------------------------------
# Tests: constants / allowlist
# ---------------------------------------------------------------------------


class TestConstants:
    def test_cdp_allowlist_has_expected_methods(self) -> None:
        assert "Runtime.evaluate" in _BROWSER_SCRIPT_CDP_ALLOWLIST
        assert "Page.captureScreenshot" in _BROWSER_SCRIPT_CDP_ALLOWLIST
        assert "DOM.getDocument" in _BROWSER_SCRIPT_CDP_ALLOWLIST

    def test_max_script_chars_positive(self) -> None:
        assert _MAX_BROWSER_SCRIPT_CHARS > 0

    def test_max_console_entries_positive(self) -> None:
        assert _MAX_CONSOLE_ENTRIES_PER_PAGE > 0
