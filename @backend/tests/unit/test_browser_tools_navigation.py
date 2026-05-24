"""Unit tests for personagent.infrastructure.tools.browser_tools.navigation (Slice 2)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from personagent.infrastructure.tools.browser_tools.navigation import (
    create_browser_extract_content_tool,
    create_browser_get_element_map_tool,
    create_browser_get_html_tool,
    create_browser_open_tool,
    create_browser_read_content_chunk_tool,
    create_browser_search_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker.search_url = MagicMock(return_value="https://search.yahoo.com/search?q=test")
    worker.search_provider_label = "Yahoo"
    worker.search = AsyncMock(return_value={"results": []})
    worker.open = AsyncMock(return_value={"final_url": "https://example.com", "page_id": "p1"})
    worker.extract_content = AsyncMock(return_value={"content": "hello"})
    worker.get_html = AsyncMock(return_value={"html": "<p>hello</p>"})
    worker.view_snapshot = AsyncMock(return_value={
        "element_map": {},
        "browser_id": "b1",
        "active_tab_id": "t1",
        "url": "https://example.com",
        "title": "Example",
    })
    worker.switch_tab = AsyncMock()
    worker.view_navigate = AsyncMock(return_value={})
    return worker


def _make_context() -> MagicMock:
    context = MagicMock()
    context.conversation_id = "conv-123"
    context.get = MagicMock(return_value=None)
    return context


def _make_call() -> MagicMock:
    call = MagicMock()
    call.id = "call-1"
    return call


# ---------------------------------------------------------------------------
# BrowserSearch
# ---------------------------------------------------------------------------

class TestBrowserSearchTool:
    def test_returns_tool_with_correct_name(self) -> None:
        worker = _make_worker()
        tool = create_browser_search_tool(worker)
        assert tool.definition.name == "BrowserSearch"

    def test_tool_is_read_only(self) -> None:
        worker = _make_worker()
        tool = create_browser_search_tool(worker)
        assert tool.definition.is_read_only is True

    def test_tool_group_is_web(self) -> None:
        worker = _make_worker()
        tool = create_browser_search_tool(worker)
        assert tool.definition.group == "web"


# ---------------------------------------------------------------------------
# BrowserOpen
# ---------------------------------------------------------------------------

class TestBrowserOpenTool:
    def test_returns_tool_with_correct_name(self) -> None:
        worker = _make_worker()
        tool = create_browser_open_tool(worker)
        assert tool.definition.name == "BrowserOpen"

    def test_tool_is_read_only(self) -> None:
        worker = _make_worker()
        tool = create_browser_open_tool(worker)
        assert tool.definition.is_read_only is True

    def test_schema_has_url_property(self) -> None:
        worker = _make_worker()
        tool = create_browser_open_tool(worker)
        assert "url" in tool.definition.input_schema["properties"]

    def test_schema_has_result_index_property(self) -> None:
        worker = _make_worker()
        tool = create_browser_open_tool(worker)
        assert "result_index" in tool.definition.input_schema["properties"]

    def test_schema_has_search_id_property(self) -> None:
        worker = _make_worker()
        tool = create_browser_open_tool(worker)
        assert "search_id" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserExtractContent
# ---------------------------------------------------------------------------

class TestBrowserExtractContentTool:
    def test_returns_tool_with_correct_name(self) -> None:
        worker = _make_worker()
        tool = create_browser_extract_content_tool(worker)
        assert tool.definition.name == "BrowserExtractContent"

    def test_tool_is_read_only(self) -> None:
        worker = _make_worker()
        tool = create_browser_extract_content_tool(worker)
        assert tool.definition.is_read_only is True

    def test_schema_has_url_property(self) -> None:
        worker = _make_worker()
        tool = create_browser_extract_content_tool(worker)
        assert "url" in tool.definition.input_schema["properties"]

    def test_schema_has_force_refresh(self) -> None:
        worker = _make_worker()
        tool = create_browser_extract_content_tool(worker)
        assert "force_refresh" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserReadContentChunk
# ---------------------------------------------------------------------------

class TestBrowserReadContentChunkTool:
    def test_returns_tool_with_correct_name(self) -> None:
        tool = create_browser_read_content_chunk_tool()
        assert tool.definition.name == "BrowserReadContentChunk"

    def test_tool_is_read_only(self) -> None:
        tool = create_browser_read_content_chunk_tool()
        assert tool.definition.is_read_only is True

    def test_schema_has_cache_key(self) -> None:
        tool = create_browser_read_content_chunk_tool()
        assert "cache_key" in tool.definition.input_schema["properties"]

    def test_schema_has_chunk_index(self) -> None:
        tool = create_browser_read_content_chunk_tool()
        assert "chunk_index" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserGetHtml
# ---------------------------------------------------------------------------

class TestBrowserGetHtmlTool:
    def test_returns_tool_with_correct_name(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_html_tool(worker)
        assert tool.definition.name == "BrowserGetHtml"

    def test_tool_is_read_only(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_html_tool(worker)
        assert tool.definition.is_read_only is True

    def test_schema_has_page_id(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_html_tool(worker)
        assert "page_id" in tool.definition.input_schema["properties"]


# ---------------------------------------------------------------------------
# BrowserGetElementMap
# ---------------------------------------------------------------------------

class TestBrowserGetElementMapTool:
    def test_returns_tool_with_correct_name(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_element_map_tool(worker)
        assert tool.definition.name == "BrowserGetElementMap"

    def test_tool_is_read_only(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_element_map_tool(worker)
        assert tool.definition.is_read_only is True

    def test_schema_has_width_height(self) -> None:
        worker = _make_worker()
        tool = create_browser_get_element_map_tool(worker)
        props = tool.definition.input_schema["properties"]
        assert "width" in props
        assert "height" in props


# ---------------------------------------------------------------------------
# Backward-compat: factories.py still exports all navigation tools
# ---------------------------------------------------------------------------

class TestBackwardCompatExports:
    def test_factories_reexports_search(self) -> None:
        from personagent.infrastructure.tools.browser_tools.factories import (
            create_browser_search_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser_tools.navigation import (
            create_browser_search_tool as from_navigation,
        )
        assert from_factories is from_navigation

    def test_factories_reexports_open(self) -> None:
        from personagent.infrastructure.tools.browser_tools.factories import (
            create_browser_open_tool as from_factories,
        )
        from personagent.infrastructure.tools.browser_tools.navigation import (
            create_browser_open_tool as from_navigation,
        )
        assert from_factories is from_navigation

    def test_init_reexports_all_six(self) -> None:
        from personagent.infrastructure.tools.browser_tools import (
            create_browser_extract_content_tool,
            create_browser_get_element_map_tool,
            create_browser_get_html_tool,
            create_browser_open_tool,
            create_browser_read_content_chunk_tool,
            create_browser_search_tool,
        )
        assert all([
            create_browser_search_tool,
            create_browser_open_tool,
            create_browser_extract_content_tool,
            create_browser_read_content_chunk_tool,
            create_browser_get_html_tool,
            create_browser_get_element_map_tool,
        ])


# ---------------------------------------------------------------------------
# create_browser_tools still returns 19 tools
# ---------------------------------------------------------------------------

class TestCreateBrowserToolsIntegrity:
    def test_returns_19_tools(self) -> None:
        from personagent.infrastructure.tools.browser_tools import create_browser_tools

        worker = _make_worker()
        tools = create_browser_tools(worker)
        assert len(tools) == 19

    def test_all_tool_names_present(self) -> None:
        from personagent.infrastructure.tools.browser_tools import create_browser_tools

        worker = _make_worker()
        tools = create_browser_tools(worker)
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
