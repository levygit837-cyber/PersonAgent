"""Unit tests for browser tool backward-compat exports and architectural invariants.

These tests verify that the re-export structure (factories.py → sub-modules) is
intact and that factories.py stays thin. No browser connection needed.

For real behavioral tests of every tool, see:
    tests/integration/test_browser_tools_behavior.py
"""

from __future__ import annotations

import inspect

from personagent.infrastructure.tools.browser import (
    create_browser_act_tool,
    create_browser_click_tool,
    create_browser_close_tab_tool,
    create_browser_extract_content_tool,
    create_browser_get_element_map_tool,
    create_browser_get_html_tool,
    create_browser_history_tool,
    create_browser_list_tabs_tool,
    create_browser_open_tool,
    create_browser_read_console_tool,
    create_browser_read_content_chunk_tool,
    create_browser_reload_tool,
    create_browser_screenshot_tool,
    create_browser_script_tool,
    create_browser_scroll_tool,
    create_browser_search_tool,
    create_browser_switch_tab_tool,
    create_browser_type_tool,
    create_browser_wait_tool,
    create_browser_tools,
)
from unittest.mock import MagicMock


def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
    worker.search_provider_label = "Yahoo"
    return worker


# ---------------------------------------------------------------------------
# factories.py re-exports from sub-modules
# ---------------------------------------------------------------------------

class TestBackwardCompatExports:
    def test_navigation_reexports(self):
        from personagent.infrastructure.tools.browser.factories import (
            create_browser_search_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser.navigation import (
            create_browser_search_tool as from_sub,
        )
        assert from_factories is from_sub

    def test_interaction_reexports(self):
        from personagent.infrastructure.tools.browser.factories import (
            create_browser_click_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser.interaction import (
            create_browser_click_tool as from_sub,
        )
        assert from_factories is from_sub

    def test_tab_management_reexports(self):
        from personagent.infrastructure.tools.browser.factories import (
            create_browser_list_tabs_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser.tab_management import (
            create_browser_list_tabs_tool as from_sub,
        )
        assert from_factories is from_sub

    def test_all_19_tools_importable_from_top_level(self):
        tools = [
            create_browser_search_tool, create_browser_open_tool,
            create_browser_extract_content_tool, create_browser_read_content_chunk_tool,
            create_browser_get_html_tool, create_browser_get_element_map_tool,
            create_browser_click_tool, create_browser_type_tool,
            create_browser_screenshot_tool, create_browser_read_console_tool,
            create_browser_script_tool, create_browser_scroll_tool,
            create_browser_wait_tool, create_browser_act_tool,
            create_browser_list_tabs_tool, create_browser_close_tab_tool,
            create_browser_reload_tool, create_browser_history_tool,
            create_browser_switch_tab_tool,
        ]
        assert all(tools), "All 19 tool factories should be importable"


# ---------------------------------------------------------------------------
# Architectural invariant: factories.py stays thin
# ---------------------------------------------------------------------------

class TestFactoriesIsThin:
    def test_factories_py_under_80_nonblank_lines(self):
        from personagent.infrastructure.tools.browser import factories

        source = inspect.getsource(factories)
        lines = [line for line in source.splitlines() if line.strip()]
        assert len(lines) < 80, f"factories.py has {len(lines)} non-blank lines, expected < 80"


# ---------------------------------------------------------------------------
# create_browser_tools returns correct count
# ---------------------------------------------------------------------------

class TestCreateBrowserToolsIntegrity:
    def test_returns_19_tools(self):
        tools = create_browser_tools(_make_worker())
        assert len(tools) == 19

    def test_all_expected_names_present(self):
        tools = create_browser_tools(_make_worker())
        names = {t.definition.name for t in tools}
        expected = {
            "BrowserSearch", "BrowserOpen", "BrowserListTabs",
            "BrowserExtractContent", "BrowserReadContentChunk",
            "BrowserGetHtml", "BrowserGetElementMap",
            "BrowserClick", "BrowserType", "BrowserScreenshot",
            "BrowserCloseTab", "BrowserReadConsole", "BrowserScript",
            "BrowserScroll", "BrowserReload", "BrowserHistory",
            "BrowserSwitchTab", "BrowserWait", "BrowserAct",
        }
        assert names == expected
