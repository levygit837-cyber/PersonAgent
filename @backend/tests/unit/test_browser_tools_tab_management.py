"""Unit tests for personagent.infrastructure.tools.browser.tab_management (Slice 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from personagent.infrastructure.tools.browser.tab_management import (
    create_browser_close_tab_tool,
    create_browser_history_tool,
    create_browser_list_tabs_tool,
    create_browser_reload_tool,
    create_browser_switch_tab_tool,
)


def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker.list_tabs = AsyncMock(return_value={"tabs": []})
    worker.close_tab = AsyncMock(return_value={"closed_page_id": "p1"})
    worker.reload = AsyncMock(return_value={"status": "ok"})
    worker.history = AsyncMock(return_value={"status": "ok"})
    worker.switch_tab = AsyncMock(return_value={"active_tab_id": "p2"})
    return worker


# ---------------------------------------------------------------------------
# BrowserListTabs
# ---------------------------------------------------------------------------

class TestBrowserListTabsTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_list_tabs_tool(_make_worker())
        assert tool.definition.name == "BrowserListTabs"

    def test_tool_is_read_only(self) -> None:
        tool = create_browser_list_tabs_tool(_make_worker())
        assert tool.definition.is_read_only is True

    def test_schema_has_max_tabs(self) -> None:
        tool = create_browser_list_tabs_tool(_make_worker())
        assert "max_tabs" in tool.definition.input_schema["properties"]

    def test_max_tabs_bounds(self) -> None:
        tool = create_browser_list_tabs_tool(_make_worker())
        prop = tool.definition.input_schema["properties"]["max_tabs"]
        assert prop["minimum"] == 1
        assert prop["maximum"] == 50


# ---------------------------------------------------------------------------
# BrowserCloseTab
# ---------------------------------------------------------------------------

class TestBrowserCloseTabTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_close_tab_tool(_make_worker())
        assert tool.definition.name == "BrowserCloseTab"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_close_tab_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_has_page_id(self) -> None:
        tool = create_browser_close_tab_tool(_make_worker())
        assert "page_id" in tool.definition.input_schema["properties"]

    def test_schema_has_max_tabs(self) -> None:
        tool = create_browser_close_tab_tool(_make_worker())
        assert "max_tabs" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserReload
# ---------------------------------------------------------------------------

class TestBrowserReloadTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_reload_tool(_make_worker())
        assert tool.definition.name == "BrowserReload"

    def test_schema_has_page_target(self) -> None:
        tool = create_browser_reload_tool(_make_worker())
        props = tool.definition.input_schema["properties"]
        assert "page_id" in props
        assert "window_id" in props


# ---------------------------------------------------------------------------
# BrowserHistory
# ---------------------------------------------------------------------------

class TestBrowserHistoryTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_history_tool(_make_worker())
        assert tool.definition.name == "BrowserHistory"

    def test_schema_has_direction(self) -> None:
        tool = create_browser_history_tool(_make_worker())
        direction = tool.definition.input_schema["properties"]["direction"]
        assert set(direction["enum"]) == {"back", "forward"}

    def test_schema_has_page_target(self) -> None:
        tool = create_browser_history_tool(_make_worker())
        props = tool.definition.input_schema["properties"]
        assert "page_id" in props


# ---------------------------------------------------------------------------
# BrowserSwitchTab
# ---------------------------------------------------------------------------

class TestBrowserSwitchTabTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_switch_tab_tool(_make_worker())
        assert tool.definition.name == "BrowserSwitchTab"

    def test_tool_is_not_read_only(self) -> None:
        tool = create_browser_switch_tab_tool(_make_worker())
        assert tool.definition.is_read_only is False

    def test_schema_has_page_id(self) -> None:
        tool = create_browser_switch_tab_tool(_make_worker())
        assert "page_id" in tool.definition.input_schema["properties"]

    def test_schema_has_max_tabs(self) -> None:
        tool = create_browser_switch_tab_tool(_make_worker())
        assert "max_tabs" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# Backward-compat: factories.py re-exports all 5 tab management tools
# ---------------------------------------------------------------------------

class TestBackwardCompatExports:
    def test_factories_reexports_list_tabs(self) -> None:
        from personagent.infrastructure.tools.browser.factories import (
            create_browser_list_tabs_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser.tab_management import (
            create_browser_list_tabs_tool as from_tab_mgmt,
        )
        assert from_factories is from_tab_mgmt

    def test_factories_reexports_close_tab(self) -> None:
        from personagent.infrastructure.tools.browser.factories import (
            create_browser_close_tab_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser.tab_management import (
            create_browser_close_tab_tool as from_tab_mgmt,
        )
        assert from_factories is from_tab_mgmt

    def test_init_reexports_all_five(self) -> None:
        from personagent.infrastructure.tools.browser import (
            create_browser_close_tab_tool,
            create_browser_history_tool,
            create_browser_list_tabs_tool,
            create_browser_reload_tool,
            create_browser_switch_tab_tool,
        )
        assert all([
            create_browser_list_tabs_tool,
            create_browser_close_tab_tool,
            create_browser_reload_tool,
            create_browser_history_tool,
            create_browser_switch_tab_tool,
        ])


# ---------------------------------------------------------------------------
# create_browser_tools still returns 19 tools
# ---------------------------------------------------------------------------

class TestCreateBrowserToolsIntegrity:
    def test_returns_19_tools(self) -> None:
        from personagent.infrastructure.tools.browser import create_browser_tools

        worker = _make_worker()
        worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
        worker.search_provider_label = "Yahoo"
        tools = create_browser_tools(worker)
        assert len(tools) == 19

    def test_tab_management_tool_names_present(self) -> None:
        from personagent.infrastructure.tools.browser import create_browser_tools

        worker = _make_worker()
        worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
        worker.search_provider_label = "Yahoo"
        tools = create_browser_tools(worker)
        names = {t.definition.name for t in tools}
        tab_names = {
            "BrowserListTabs", "BrowserCloseTab", "BrowserReload",
            "BrowserHistory", "BrowserSwitchTab",
        }
        assert tab_names.issubset(names)

    def test_factories_py_is_thin_orchestrator(self) -> None:
        """factories.py should now only contain create_browser_tools + imports."""
        import inspect

        from personagent.infrastructure.tools.browser import factories

        source = inspect.getsource(factories)
        lines = [line for line in source.splitlines() if line.strip()]
        assert len(lines) < 80, f"factories.py has {len(lines)} non-blank lines, expected < 80"
