"""Unit tests for personagent.infrastructure.tools.browser_tools.interaction (Slice 3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from personagent.infrastructure.tools.browser_tools.interaction import (
    create_browser_act_tool,
    create_browser_click_tool,
    create_browser_read_console_tool,
    create_browser_screenshot_tool,
    create_browser_script_tool,
    create_browser_scroll_tool,
    create_browser_type_tool,
    create_browser_wait_tool,
)


def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker.click = AsyncMock(return_value={"status": "ok"})
    worker.type_input = AsyncMock(return_value={"status": "ok"})
    worker.screenshot = AsyncMock(return_value={"image": "base64..."})
    worker.read_console = AsyncMock(return_value={"entries": []})
    worker.script = AsyncMock(return_value={"result": 42})
    worker.scroll = AsyncMock(return_value={"status": "ok"})
    worker.wait = AsyncMock(return_value={"status": "ok"})
    worker.view_act = AsyncMock(return_value={"element_map": {}, "url": "https://example.com"})
    worker.switch_tab = AsyncMock()
    return worker


# ---------------------------------------------------------------------------
# BrowserClick
# ---------------------------------------------------------------------------

class TestBrowserClickTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_click_tool(_make_worker())
        assert tool.definition.name == "BrowserClick"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_click_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_has_node_id(self) -> None:
        tool = create_browser_click_tool(_make_worker())
        assert "node_id" in tool.definition.input_schema["properties"]

    def test_schema_has_coordinates(self) -> None:
        tool = create_browser_click_tool(_make_worker())
        props = tool.definition.input_schema["properties"]
        assert "x" in props
        assert "y" in props

    def test_schema_has_button(self) -> None:
        tool = create_browser_click_tool(_make_worker())
        assert "button" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserType
# ---------------------------------------------------------------------------

class TestBrowserTypeTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_type_tool(_make_worker())
        assert tool.definition.name == "BrowserType"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_type_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_has_mode(self) -> None:
        tool = create_browser_type_tool(_make_worker())
        assert "mode" in tool.definition.input_schema["properties"]

    def test_schema_mode_enum(self) -> None:
        tool = create_browser_type_tool(_make_worker())
        mode_prop = tool.definition.input_schema["properties"]["mode"]
        assert set(mode_prop["enum"]) == {"type", "fill", "press"}


# ---------------------------------------------------------------------------
# BrowserScreenshot
# ---------------------------------------------------------------------------

class TestBrowserScreenshotTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_screenshot_tool(_make_worker())
        assert tool.definition.name == "BrowserScreenshot"

    def test_tool_is_read_only(self) -> None:
        tool = create_browser_screenshot_tool(_make_worker())
        assert tool.definition.is_read_only is True

    def test_schema_has_full_page(self) -> None:
        tool = create_browser_screenshot_tool(_make_worker())
        assert "full_page" in tool.definition.input_schema["properties"]

    def test_schema_has_format(self) -> None:
        tool = create_browser_screenshot_tool(_make_worker())
        fmt_prop = tool.definition.input_schema["properties"]["format"]
        assert set(fmt_prop["enum"]) == {"png", "jpeg"}


# ---------------------------------------------------------------------------
# BrowserReadConsole
# ---------------------------------------------------------------------------

class TestBrowserReadConsoleTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_read_console_tool(_make_worker())
        assert tool.definition.name == "BrowserReadConsole"

    def test_tool_is_read_only(self) -> None:
        tool = create_browser_read_console_tool(_make_worker())
        assert tool.definition.is_read_only is True

    def test_schema_has_levels(self) -> None:
        tool = create_browser_read_console_tool(_make_worker())
        assert "levels" in tool.definition.input_schema["properties"]

    def test_schema_has_since_id(self) -> None:
        tool = create_browser_read_console_tool(_make_worker())
        assert "since_id" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserScript
# ---------------------------------------------------------------------------

class TestBrowserScriptTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_script_tool(_make_worker())
        assert tool.definition.name == "BrowserScript"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_script_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_has_script(self) -> None:
        tool = create_browser_script_tool(_make_worker())
        assert "script" in tool.definition.input_schema["properties"]

    def test_schema_has_cdp_method(self) -> None:
        tool = create_browser_script_tool(_make_worker())
        assert "cdp_method" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserScroll
# ---------------------------------------------------------------------------

class TestBrowserScrollTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_scroll_tool(_make_worker())
        assert tool.definition.name == "BrowserScroll"

    def test_schema_has_delta_x_y(self) -> None:
        tool = create_browser_scroll_tool(_make_worker())
        props = tool.definition.input_schema["properties"]
        assert "delta_x" in props
        assert "delta_y" in props


# ---------------------------------------------------------------------------
# BrowserWait
# ---------------------------------------------------------------------------

class TestBrowserWaitTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_wait_tool(_make_worker())
        assert tool.definition.name == "BrowserWait"

    def test_schema_has_timeout_ms(self) -> None:
        tool = create_browser_wait_tool(_make_worker())
        assert "timeout_ms" in tool.definition.input_schema["properties"]

    def test_schema_has_state(self) -> None:
        tool = create_browser_wait_tool(_make_worker())
        state_prop = tool.definition.input_schema["properties"]["state"]
        assert set(state_prop["enum"]) == {"load", "domcontentloaded", "networkidle"}


# ---------------------------------------------------------------------------
# BrowserAct
# ---------------------------------------------------------------------------

class TestBrowserActTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_act_tool(_make_worker())
        assert tool.definition.name == "BrowserAct"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_act_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_requires_node_id_and_action(self) -> None:
        tool = create_browser_act_tool(_make_worker())
        assert "node_id" in tool.definition.input_schema["properties"]
        assert "action" in tool.definition.input_schema["properties"]
        assert set(tool.definition.input_schema["required"]) == {"node_id", "action"}

    def test_schema_has_optional_fields(self) -> None:
        tool = create_browser_act_tool(_make_worker())
        props = tool.definition.input_schema["properties"]
        for field in ("value", "key", "target_node_id", "timeout_ms", "files", "text", "x", "y"):
            assert field in props, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Backward-compat: factories.py re-exports all 8 interaction tools
# ---------------------------------------------------------------------------

class TestBackwardCompatExports:
    def test_factories_reexports_click(self) -> None:
        from personagent.infrastructure.tools.browser_tools.factories import (
            create_browser_click_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser_tools.interaction import (
            create_browser_click_tool as from_interaction,
        )
        assert from_factories is from_interaction

    def test_factories_reexports_act(self) -> None:
        from personagent.infrastructure.tools.browser_tools.factories import (
            create_browser_act_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser_tools.interaction import (
            create_browser_act_tool as from_interaction,
        )
        assert from_factories is from_interaction

    def test_init_reexports_all_eight(self) -> None:
        from personagent.infrastructure.tools.browser_tools import (
            create_browser_act_tool,
            create_browser_click_tool,
            create_browser_read_console_tool,
            create_browser_screenshot_tool,
            create_browser_script_tool,
            create_browser_scroll_tool,
            create_browser_type_tool,
            create_browser_wait_tool,
        )
        assert all([
            create_browser_click_tool,
            create_browser_type_tool,
            create_browser_screenshot_tool,
            create_browser_read_console_tool,
            create_browser_script_tool,
            create_browser_scroll_tool,
            create_browser_wait_tool,
            create_browser_act_tool,
        ])


# ---------------------------------------------------------------------------
# create_browser_tools still returns 19 tools
# ---------------------------------------------------------------------------

class TestCreateBrowserToolsIntegrity:
    def test_returns_19_tools(self) -> None:
        from personagent.infrastructure.tools.browser_tools import create_browser_tools

        worker = _make_worker()
        worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
        worker.search_provider_label = "Yahoo"
        tools = create_browser_tools(worker)
        assert len(tools) == 19

    def test_interaction_tool_names_present(self) -> None:
        from personagent.infrastructure.tools.browser_tools import create_browser_tools

        worker = _make_worker()
        worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
        worker.search_provider_label = "Yahoo"
        tools = create_browser_tools(worker)
        names = {t.definition.name for t in tools}
        interaction_names = {
            "BrowserClick", "BrowserType", "BrowserScreenshot",
            "BrowserReadConsole", "BrowserScript", "BrowserScroll",
            "BrowserWait", "BrowserAct",
        }
        assert interaction_names.issubset(names)
