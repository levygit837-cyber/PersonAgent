"""Browser tool factories for the main chat agent.

This package was extracted from the monolithic ``browser_tools.py``.
The public API is ``create_browser_tools(worker)``.
"""

from personagent.infrastructure.tools.browser.building import (
    _summarize_element_map,
)
from personagent.infrastructure.tools.browser.factories import (
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
    create_browser_tools,
    create_browser_type_tool,
    create_browser_wait_tool,
)

__all__ = [
    "_summarize_element_map",
    "create_browser_act_tool",
    "create_browser_click_tool",
    "create_browser_close_tab_tool",
    "create_browser_extract_content_tool",
    "create_browser_get_element_map_tool",
    "create_browser_get_html_tool",
    "create_browser_history_tool",
    "create_browser_list_tabs_tool",
    "create_browser_open_tool",
    "create_browser_read_console_tool",
    "create_browser_read_content_chunk_tool",
    "create_browser_reload_tool",
    "create_browser_screenshot_tool",
    "create_browser_script_tool",
    "create_browser_scroll_tool",
    "create_browser_search_tool",
    "create_browser_switch_tab_tool",
    "create_browser_tools",
    "create_browser_type_tool",
    "create_browser_wait_tool",
]
