"""Unit tests for browser_tools/workspace_target.py — workspace and target resolution."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from personagent.domain.tools import ToolUseContext
from personagent.infrastructure.tools.browser_tools.workspace_target import (
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_targeted_arguments,
    _browser_view_is_about_blank,
    _browser_workspace,
    _browser_workspace_current_url,
    _merge_shared_browser_workspace_tabs,
    _normalize_browser_tab_for_tool,
    _resolve_browser_page_target,
    _workspace_browser_tabs,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_context(
    *,
    conversation_id: str = "conv-42",
    metadata: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ToolUseContext:
    ctx = MagicMock(spec=ToolUseContext)
    ctx.conversation_id = conversation_id
    ctx.metadata = dict(metadata or {})
    ctx.limits = dict(limits or {})
    return ctx


# ---------------------------------------------------------------------------
# _browser_workspace
# ---------------------------------------------------------------------------


class TestBrowserWorkspace:
    def test_returns_workspace_from_metadata(self) -> None:
        ctx = _fake_context(metadata={"browser_workspace": {"active_browser_id": "b1"}})
        assert _browser_workspace(ctx) == {"active_browser_id": "b1"}

    def test_returns_empty_when_missing(self) -> None:
        ctx = _fake_context()
        assert _browser_workspace(ctx) == {}

    def test_returns_empty_for_non_mapping(self) -> None:
        ctx = _fake_context(metadata={"browser_workspace": "invalid"})
        assert _browser_workspace(ctx) == {}


# ---------------------------------------------------------------------------
# _browser_target
# ---------------------------------------------------------------------------


class TestBrowserTarget:
    def test_returns_target_from_metadata(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"page_id": "p1"}})
        assert _browser_target(ctx) == {"page_id": "p1"}

    def test_returns_empty_when_missing(self) -> None:
        ctx = _fake_context()
        assert _browser_target(ctx) == {}

    def test_returns_empty_for_non_mapping(self) -> None:
        ctx = _fake_context(metadata={"browser_target": 42})
        assert _browser_target(ctx) == {}


# ---------------------------------------------------------------------------
# _browser_target_page_id
# ---------------------------------------------------------------------------


class TestBrowserTargetPageId:
    def test_returns_page_id(self) -> None:
        assert _browser_target_page_id({"page_id": "p1"}) == "p1"

    def test_returns_window_id_fallback(self) -> None:
        assert _browser_target_page_id({"window_id": "w1"}) == "w1"

    def test_returns_tab_id_fallback(self) -> None:
        assert _browser_target_page_id({"tab_id": "t1"}) == "t1"

    def test_returns_none_for_empty(self) -> None:
        assert _browser_target_page_id({}) is None


# ---------------------------------------------------------------------------
# _browser_session_id
# ---------------------------------------------------------------------------


class TestBrowserSessionId:
    def test_uses_override(self) -> None:
        ctx = _fake_context(metadata={"_browser_session_id_override": "override-id"})
        assert _browser_session_id(ctx) == "override-id"

    def test_falls_back_to_target_browser_id(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"browser_id": "target-b"}})
        assert _browser_session_id(ctx) == "target-b"

    def test_falls_back_to_workspace_active_browser(self) -> None:
        ctx = _fake_context(metadata={"browser_workspace": {"active_browser_id": "ws-b"}})
        assert _browser_session_id(ctx) == "ws-b"

    def test_falls_back_to_conversation_id(self) -> None:
        ctx = _fake_context(conversation_id="conv-42")
        assert _browser_session_id(ctx) == "conv-42"


# ---------------------------------------------------------------------------
# _browser_view_is_about_blank
# ---------------------------------------------------------------------------


class TestBrowserViewIsAboutBlank:
    def test_about_blank(self) -> None:
        assert _browser_view_is_about_blank({"url": "about:blank"}) is True

    def test_empty_url(self) -> None:
        assert _browser_view_is_about_blank({}) is True

    def test_normal_url(self) -> None:
        assert _browser_view_is_about_blank({"url": "https://example.com"}) is False


# ---------------------------------------------------------------------------
# _normalize_browser_tab_for_tool
# ---------------------------------------------------------------------------


class TestNormalizeBrowserTabForTool:
    def test_basic_normalization(self) -> None:
        tab = {"page_id": "p1", "url": "https://example.com", "title": "Example"}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["page_id"] == "p1"
        assert result["window_id"] == "p1"
        assert result["url"] == "https://example.com"
        assert result["title"] == "Example"
        assert result["domain"] == "example.com"

    def test_falls_back_to_browser_id_for_page_id(self) -> None:
        tab: dict[str, Any] = {"url": "https://test.com"}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["page_id"] == "b1"

    def test_active_flags(self) -> None:
        tab = {"page_id": "p1", "active": True}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["active"] is True
        assert result["is_active"] is True
        assert result["is_current_page"] is True

    def test_already_read_from_extraction_count(self) -> None:
        tab = {"page_id": "p1", "extraction_count": 2}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["already_read"] is True
        assert result["read_status"] == "read"

    def test_unread_tab(self) -> None:
        tab = {"page_id": "p1", "extraction_count": 0}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["already_read"] is False
        assert result["read_status"] == "unread"


# ---------------------------------------------------------------------------
# _workspace_browser_tabs
# ---------------------------------------------------------------------------


class TestWorkspaceBrowserTabs:
    def test_returns_normalized_tabs(self) -> None:
        workspace: dict[str, Any] = {
            "tabs": [{"page_id": "p1", "url": "https://example.com", "active": True}]
        }
        tabs = _workspace_browser_tabs(workspace, browser_id="b1")
        assert len(tabs) == 1
        assert tabs[0]["page_id"] == "p1"

    def test_empty_workspace(self) -> None:
        tabs = _workspace_browser_tabs({}, browser_id="b1")
        assert tabs == []

    def test_synthesizes_tab_from_current_url(self) -> None:
        workspace: dict[str, Any] = {"current_url": "https://example.com", "current_title": "Example"}
        tabs = _workspace_browser_tabs(workspace, browser_id="b1")
        assert len(tabs) == 1
        assert tabs[0]["url"] == "https://example.com"
        assert tabs[0]["active"] is True


# ---------------------------------------------------------------------------
# _browser_workspace_current_url
# ---------------------------------------------------------------------------


class TestBrowserWorkspaceCurrentUrl:
    def test_returns_current_url(self) -> None:
        ctx = _fake_context(metadata={"browser_workspace": {"current_url": "https://example.com"}})
        assert _browser_workspace_current_url(ctx) == "https://example.com"

    def test_returns_none_for_invalid_url(self) -> None:
        ctx = _fake_context(metadata={"browser_workspace": {"current_url": "not-a-url"}})
        assert _browser_workspace_current_url(ctx) is None

    def test_returns_none_when_empty(self) -> None:
        ctx = _fake_context()
        assert _browser_workspace_current_url(ctx) is None


# ---------------------------------------------------------------------------
# _resolve_browser_page_target
# ---------------------------------------------------------------------------


class TestResolveBrowserPageTarget:
    def test_no_target_no_requested(self) -> None:
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target({}, ctx, tool_name="BrowserClick")
        assert target_id is None
        assert error is None

    def test_returns_requested_page_id(self) -> None:
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target(
            {"page_id": "p1"}, ctx, tool_name="BrowserClick"
        )
        assert target_id == "p1"
        assert error is None

    def test_returns_target_from_context(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"page_id": "ctx-p1"}})
        target_id, error = _resolve_browser_page_target({}, ctx, tool_name="BrowserClick")
        assert target_id == "ctx-p1"
        assert error is None

    def test_error_when_browser_id_empty_string(self) -> None:
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target(
            {"browser_id": ""}, ctx, tool_name="BrowserClick"
        )
        assert error is not None
        assert "non-empty string" in error

    def test_conflict_with_different_target_page_id(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"page_id": "ctx-p1"}})
        target_id, error = _resolve_browser_page_target(
            {"page_id": "other-p1"}, ctx, tool_name="BrowserClick"
        )
        assert error is not None
        assert "cannot target" in error


# ---------------------------------------------------------------------------
# _browser_targeted_arguments
# ---------------------------------------------------------------------------


class TestBrowserTargetedArguments:
    def test_injects_target_id(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"page_id": "p1"}})
        args, error = _browser_targeted_arguments({}, ctx, tool_name="BrowserClick")
        assert error is None
        assert args.get("page_id") == "p1"
        assert args.get("window_id") == "p1"

    def test_preserves_existing_page_id(self) -> None:
        ctx = _fake_context(metadata={"browser_target": {"page_id": "p1"}})
        args, error = _browser_targeted_arguments(
            {"page_id": "p1"}, ctx, tool_name="BrowserClick"
        )
        assert error is None
        assert args["page_id"] == "p1"


# ---------------------------------------------------------------------------
# _merge_shared_browser_workspace_tabs
# ---------------------------------------------------------------------------


class TestMergeSharedBrowserWorkspaceTabs:
    def test_returns_data_when_no_workspace(self) -> None:
        ctx = _fake_context()
        result = _merge_shared_browser_workspace_tabs(
            {"some": "data"}, ctx, browser_id="b1", max_tabs=10
        )
        assert result["browser_id"] == "b1"
        assert result["some"] == "data"

    def test_merges_workspace_tabs(self) -> None:
        ctx = _fake_context(
            metadata={
                "browser_workspace": {
                    "current_url": "https://example.com",
                    "current_title": "Example",
                    "active_browser_id": "b1",
                }
            }
        )
        result = _merge_shared_browser_workspace_tabs(
            {}, ctx, browser_id="b1", max_tabs=10
        )
        assert result["type"] == "browser_tabs"
        assert result["browser_id"] == "b1"
        assert len(result["tabs"]) > 0
