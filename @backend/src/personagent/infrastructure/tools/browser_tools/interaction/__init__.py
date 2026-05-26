"""Interaction-related browser tool factories.

Extracted from ``interaction.py`` (browser_tools interaction slice).
Contains: BrowserClick, BrowserType, BrowserScreenshot,
BrowserReadConsole, BrowserScript, BrowserScroll, BrowserWait, BrowserAct.
"""

from __future__ import annotations

from personagent.infrastructure.tools.browser_tools.interaction._act import (
    create_browser_act_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._click import (
    create_browser_click_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._console import (
    create_browser_read_console_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._screenshot import (
    create_browser_screenshot_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._script import (
    create_browser_script_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._scroll import (
    create_browser_scroll_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._type import (
    create_browser_type_tool,
)
from personagent.infrastructure.tools.browser_tools.interaction._wait import (
    create_browser_wait_tool,
)

__all__ = [
    "create_browser_act_tool",
    "create_browser_click_tool",
    "create_browser_read_console_tool",
    "create_browser_screenshot_tool",
    "create_browser_script_tool",
    "create_browser_scroll_tool",
    "create_browser_type_tool",
    "create_browser_wait_tool",
]
