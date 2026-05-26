"""Navigation-related browser tool factories.

Extracted from ``navigation.py`` (browser_tools Slice 3).
Contains: BrowserSearch, BrowserOpen, BrowserExtractContent,
BrowserReadContentChunk, BrowserGetHtml, BrowserGetElementMap.
"""

from __future__ import annotations

from personagent.infrastructure.tools.browser.navigation.element_map import (
    create_browser_get_element_map_tool,
)
from personagent.infrastructure.tools.browser.navigation.extract import (
    create_browser_extract_content_tool,
)
from personagent.infrastructure.tools.browser.navigation.html import (
    create_browser_get_html_tool,
)
from personagent.infrastructure.tools.browser.navigation.open import (
    create_browser_open_tool,
)
from personagent.infrastructure.tools.browser.navigation.read_chunk import (
    create_browser_read_content_chunk_tool,
)
from personagent.infrastructure.tools.browser.navigation.search import (
    create_browser_search_tool,
)

__all__ = [
    "create_browser_search_tool",
    "create_browser_open_tool",
    "create_browser_extract_content_tool",
    "create_browser_read_content_chunk_tool",
    "create_browser_get_html_tool",
    "create_browser_get_element_map_tool",
]
