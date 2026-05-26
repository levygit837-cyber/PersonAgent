"""LightPanda browser tools for the main chat agent.

This module is the thin orchestrator that assembles all 19 browser tools
from their respective sub-modules (navigation, interaction, tab_management).
"""

from __future__ import annotations

from personagent.domain.tools import Tool
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.browser.interaction import (
    create_browser_act_tool,
    create_browser_click_tool,
    create_browser_read_console_tool,
    create_browser_screenshot_tool,
    create_browser_script_tool,
    create_browser_scroll_tool,
    create_browser_type_tool,
    create_browser_wait_tool,
)
from personagent.infrastructure.tools.browser.navigation import (
    create_browser_extract_content_tool,
    create_browser_get_element_map_tool,
    create_browser_get_html_tool,
    create_browser_open_tool,
    create_browser_read_content_chunk_tool,
    create_browser_search_tool,
)
from personagent.infrastructure.tools.browser.tab_management import (
    create_browser_close_tab_tool,
    create_browser_history_tool,
    create_browser_list_tabs_tool,
    create_browser_reload_tool,
    create_browser_switch_tab_tool,
)


def create_browser_tools(worker: LightPandaBrowserWorker) -> list[Tool]:
    """Create all LightPanda browser tools."""

    return [
        create_browser_search_tool(worker),
        create_browser_open_tool(worker),
        create_browser_list_tabs_tool(worker),
        create_browser_extract_content_tool(worker),
        create_browser_read_content_chunk_tool(),
        create_browser_get_html_tool(worker),
        create_browser_get_element_map_tool(worker),
        create_browser_click_tool(worker),
        create_browser_type_tool(worker),
        create_browser_screenshot_tool(worker),
        create_browser_close_tab_tool(worker),
        create_browser_read_console_tool(worker),
        create_browser_script_tool(worker),
        create_browser_scroll_tool(worker),
        create_browser_reload_tool(worker),
        create_browser_history_tool(worker),
        create_browser_switch_tab_tool(worker),
        create_browser_wait_tool(worker),
        create_browser_act_tool(worker),
    ]
