"""Unit tests for browser_tools/helpers.py — extracted helper functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolUseContext,
)
from personagent.infrastructure.tools.browser.building import (
    _browser_action_permission,
    _browser_height,
    _browser_result_max_chars,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_view_is_about_blank,
    _browser_width,
    _browser_workspace,
    _coerce_links,
    _coerce_page_or_window_id,
    _curate_links,
    _deny,
    _error,
    _error_type,
    _extract_markdown_links,
    _is_int,
    _is_low_quality_link,
    _json_result,
    _normalize_browser_open_arguments,
    _normalize_browser_tab_for_tool,
    _page_target_schema,
    _prepare_browser_control_response,
    _prepare_extracted_content_response,
    _resolve_browser_page_target,
    _split_content_chunks,
    _summarize_element_map,
    _trim_content,
    _validate_browser_dimensions,
    _validate_page_or_window_id,
    _viewport_schema,
    _workspace_browser_tabs,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fake_context(
    *,
    conversation_id: str = "conv-1",
    metadata: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ToolUseContext:
    ctx = MagicMock(spec=ToolUseContext)
    ctx.conversation_id = conversation_id
    ctx.metadata = dict(metadata or {})
    ctx.limits = dict(limits or {})
    return ctx


def _fake_call(*, call_id: str = "call-1", name: str = "BrowserClick") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


# ---------------------------------------------------------------------------
# _is_int
# ---------------------------------------------------------------------------


class TestIsInt:
    def test_true_for_int(self):
        assert _is_int(42) is True

    def test_true_for_string_int(self):
        assert _is_int("7") is True

    def test_false_for_bool(self):
        assert _is_int(True) is False

    def test_false_for_float_with_fraction(self):
        assert _is_int(3.5) is False

    def test_true_for_float_integer(self):
        assert _is_int(3.0) is True

    def test_false_for_non_numeric_string(self):
        assert _is_int("abc") is False

    def test_false_for_none(self):
        assert _is_int(None) is False


# ---------------------------------------------------------------------------
# _browser_width / _browser_height
# ---------------------------------------------------------------------------


class TestBrowserDimensions:
    def test_width_default(self):
        assert _browser_width({}) == 1024

    def test_width_clamps_low(self):
        assert _browser_width({"width": 100}) == 320

    def test_width_clamps_high(self):
        assert _browser_width({"width": 5000}) == 2400

    def test_height_default(self):
        assert _browser_height({}) == 720

    def test_height_clamps_low(self):
        assert _browser_height({"height": 10}) == 240

    def test_height_clamps_high(self):
        assert _browser_height({"height": 9000}) == 1800


# ---------------------------------------------------------------------------
# _validate_browser_dimensions
# ---------------------------------------------------------------------------


class TestValidateBrowserDimensions:
    def test_valid_dimensions_returns_none(self):
        assert _validate_browser_dimensions({"width": 800, "height": 600}, "BrowserOpen") is None

    def test_invalid_width_returns_deny(self):
        result = _validate_browser_dimensions({"width": 100, "height": 600}, "BrowserOpen")
        assert result is not None
        assert result.behavior == ToolPermissionBehavior.DENY

    def test_invalid_height_returns_deny(self):
        result = _validate_browser_dimensions({"width": 800, "height": 50}, "BrowserOpen")
        assert result is not None
        assert result.behavior == ToolPermissionBehavior.DENY


# ---------------------------------------------------------------------------
# _page_target_schema / _viewport_schema
# ---------------------------------------------------------------------------


class TestSchemaHelpers:
    def test_page_target_schema_has_keys(self):
        schema = _page_target_schema()
        assert "browser_id" in schema
        assert "page_id" in schema
        assert "window_id" in schema

    def test_viewport_schema_has_keys(self):
        schema = _viewport_schema()
        assert "width" in schema
        assert "height" in schema


# ---------------------------------------------------------------------------
# _summarize_element_map
# ---------------------------------------------------------------------------


class TestSummarizeElementMap:
    def test_empty_returns_empty(self):
        assert _summarize_element_map([]) == []

    def test_non_list_returns_empty(self):
        assert _summarize_element_map("not a list") == []

    def test_extracts_fields(self):
        raw = [{"node_id": "n1", "tag": "button", "text": "Click me", "interactable": True}]
        result = _summarize_element_map(raw)
        assert len(result) == 1
        assert result[0]["node_id"] == "n1"
        assert result[0]["tag"] == "button"
        assert result[0]["interactable"] is True

    def test_skips_missing_node_id(self):
        raw = [{"tag": "div"}]
        assert _summarize_element_map(raw) == []

    def test_caps_at_120(self):
        raw = [{"node_id": f"n{i}"} for i in range(200)]
        assert len(_summarize_element_map(raw)) == 120


# ---------------------------------------------------------------------------
# _split_content_chunks
# ---------------------------------------------------------------------------


class TestSplitContentChunks:
    def test_single_chunk(self):
        chunks, ranges = _split_content_chunks("Hello world", 100)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_multiple_chunks(self):
        content = "A" * 100 + "\n\n" + "B" * 100
        chunks, ranges = _split_content_chunks(content, 50)
        assert len(chunks) >= 2

    def test_empty_content(self):
        chunks, ranges = _split_content_chunks("", 100)
        assert chunks == []


# ---------------------------------------------------------------------------
# _trim_content
# ---------------------------------------------------------------------------


class TestTrimContent:
    def test_no_trim_when_short(self):
        assert _trim_content("short", 100) == "short"

    def test_trims_at_boundary(self):
        content = "Hello world. This is a test."
        trimmed = _trim_content(content, 15)
        assert len(trimmed) <= 15


# ---------------------------------------------------------------------------
# _extract_markdown_links
# ---------------------------------------------------------------------------


class TestExtractMarkdownLinks:
    def test_extracts_links(self):
        content = "[Google](https://google.com) and [GitHub](https://github.com)"
        links = _extract_markdown_links(content)
        assert len(links) == 2
        assert links[0]["text"] == "Google"
        assert links[0]["url"] == "https://google.com"

    def test_no_links(self):
        assert _extract_markdown_links("no links here") == []


# ---------------------------------------------------------------------------
# _coerce_links
# ---------------------------------------------------------------------------


class TestCoerceLinks:
    def test_deduplicates(self):
        raw = [
            {"url": "https://a.com", "text": "A"},
            {"url": "https://a.com", "text": "A again"},
        ]
        result = _coerce_links(raw)
        assert len(result) == 1

    def test_filters_non_http(self):
        raw = [{"url": "ftp://a.com", "text": "A"}]
        assert _coerce_links(raw) == []

    def test_non_list_returns_empty(self):
        assert _coerce_links("not a list") == []


# ---------------------------------------------------------------------------
# _curate_links
# ---------------------------------------------------------------------------


class TestCurateLinks:
    def test_returns_links_and_summary(self):
        raw = [{"url": "https://example.com/article", "text": "Good Article"}]
        links, summary = _curate_links(raw, content="text", source_url="https://other.com")
        assert len(links) <= 20
        assert "total" in summary
        assert "returned" in summary


# ---------------------------------------------------------------------------
# _is_low_quality_link
# ---------------------------------------------------------------------------


class TestIsLowQualityLink:
    def test_login_is_low_quality(self):
        assert _is_low_quality_link({"url": "https://example.com/login", "text": "login"}, "https://example.com") is True

    def test_good_link_is_not_low_quality(self):
        assert _is_low_quality_link({"url": "https://other.com/article", "text": "Great Article"}, "https://example.com") is False


# ---------------------------------------------------------------------------
# _coerce_page_or_window_id
# ---------------------------------------------------------------------------


class TestCoercePageOrWindowId:
    def test_prefers_page_id(self):
        assert _coerce_page_or_window_id("p1", "w1") == "p1"

    def test_falls_back_to_window_id(self):
        assert _coerce_page_or_window_id(None, "w1") == "w1"

    def test_returns_none_when_both_empty(self):
        assert _coerce_page_or_window_id(None, None) is None
        assert _coerce_page_or_window_id("", "") is None


# ---------------------------------------------------------------------------
# _validate_page_or_window_id
# ---------------------------------------------------------------------------


class TestValidatePageOrWindowId:
    def test_valid_returns_none(self):
        assert _validate_page_or_window_id("p1", None, tool_name="BrowserClick") is None

    def test_empty_page_id_returns_deny(self):
        result = _validate_page_or_window_id("", None, tool_name="BrowserClick")
        assert result is not None
        assert result.behavior == ToolPermissionBehavior.DENY

    def test_mismatched_ids_returns_deny(self):
        result = _validate_page_or_window_id("p1", "p2", tool_name="BrowserClick")
        assert result is not None
        assert result.behavior == ToolPermissionBehavior.DENY


# ---------------------------------------------------------------------------
# _normalize_browser_open_arguments
# ---------------------------------------------------------------------------


class TestNormalizeBrowserOpenArguments:
    def test_canonical_url(self):
        result = _normalize_browser_open_arguments({"url": "https://example.com"})
        assert result["url"] == "https://example.com"
        assert result["recovered_from"] == []

    def test_recovers_from_result_url(self):
        result = _normalize_browser_open_arguments({"result_url": "https://example.com"})
        assert result["url"] == "https://example.com"
        assert "result_url" in result["recovered_from"]

    def test_result_index(self):
        result = _normalize_browser_open_arguments({"result_index": 3})
        assert result["result_index"] == 3


# ---------------------------------------------------------------------------
# _normalize_browser_tab_for_tool
# ---------------------------------------------------------------------------


class TestNormalizeBrowserTabForTool:
    def test_normalizes_tab(self):
        tab = {"page_id": "p1", "url": "https://example.com", "title": "Test", "active": True}
        result = _normalize_browser_tab_for_tool(tab, browser_id="b1")
        assert result["page_id"] == "p1"
        assert result["window_id"] == "p1"
        assert result["browser_id"] == "b1"
        assert result["active"] is True
        assert result["is_active"] is True
        assert result["domain"] == "example.com"


# ---------------------------------------------------------------------------
# _workspace_browser_tabs
# ---------------------------------------------------------------------------


class TestWorkspaceBrowserTabs:
    def test_creates_tab_from_current_url(self):
        workspace = {"current_url": "https://example.com", "current_title": "Test"}
        tabs = _workspace_browser_tabs(workspace, browser_id="b1")
        assert len(tabs) == 1
        assert tabs[0]["url"] == "https://example.com"

    def test_empty_workspace(self):
        tabs = _workspace_browser_tabs({}, browser_id="b1")
        assert tabs == []


# ---------------------------------------------------------------------------
# _browser_view_is_about_blank
# ---------------------------------------------------------------------------


class TestBrowserViewIsAboutBlank:
    def test_blank_url(self):
        assert _browser_view_is_about_blank({"url": "about:blank"}) is True

    def test_empty_url(self):
        assert _browser_view_is_about_blank({}) is True

    def test_real_url(self):
        assert _browser_view_is_about_blank({"url": "https://example.com"}) is False


# ---------------------------------------------------------------------------
# _browser_session_id
# ---------------------------------------------------------------------------


class TestBrowserSessionId:
    def test_uses_override(self):
        ctx = _fake_context(metadata={"_browser_session_id_override": "override-id"})
        assert _browser_session_id(ctx) == "override-id"

    def test_uses_conversation_id(self):
        ctx = _fake_context(conversation_id="conv-42")
        assert _browser_session_id(ctx) == "conv-42"


# ---------------------------------------------------------------------------
# _browser_workspace / _browser_target
# ---------------------------------------------------------------------------


class TestBrowserWorkspaceAndTarget:
    def test_workspace_returns_dict(self):
        ctx = _fake_context(metadata={"browser_workspace": {"active_browser_id": "b1"}})
        assert _browser_workspace(ctx) == {"active_browser_id": "b1"}

    def test_workspace_returns_empty_for_non_mapping(self):
        ctx = _fake_context(metadata={"browser_workspace": "not a dict"})
        assert _browser_workspace(ctx) == {}

    def test_target_returns_dict(self):
        ctx = _fake_context(metadata={"browser_target": {"page_id": "p1"}})
        assert _browser_target(ctx) == {"page_id": "p1"}

    def test_target_returns_empty_for_none(self):
        ctx = _fake_context()
        assert _browser_target(ctx) == {}


# ---------------------------------------------------------------------------
# _browser_target_page_id
# ---------------------------------------------------------------------------


class TestBrowserTargetPageId:
    def test_returns_page_id(self):
        assert _browser_target_page_id({"page_id": "p1"}) == "p1"

    def test_returns_window_id(self):
        assert _browser_target_page_id({"window_id": "w1"}) == "w1"

    def test_returns_none(self):
        assert _browser_target_page_id({}) is None


# ---------------------------------------------------------------------------
# _error_type
# ---------------------------------------------------------------------------


class TestErrorType:
    def test_known_tool(self):
        assert _error_type("BrowserSearch") == "browser_search"
        assert _error_type("BrowserOpen") == "browser_open"

    def test_unknown_tool(self):
        assert _error_type("UnknownTool") == "browser"


# ---------------------------------------------------------------------------
# _json_result
# ---------------------------------------------------------------------------


class TestJsonResult:
    def test_returns_completed_result(self):
        call = _fake_call()
        result = _json_result(call, "BrowserClick", {"status": "ok"})
        assert result.status == ToolExecutionStatus.COMPLETED
        assert result.data == {"status": "ok"}


# ---------------------------------------------------------------------------
# _error
# ---------------------------------------------------------------------------


class TestError:
    def test_returns_error_result(self):
        call = _fake_call()
        result = _error(call, "BrowserClick", "something failed")
        assert result.status == ToolExecutionStatus.ERROR
        assert result.is_error is True
        assert "something failed" in result.content


# ---------------------------------------------------------------------------
# _deny
# ---------------------------------------------------------------------------


class TestDeny:
    def test_returns_deny_permission(self):
        result = _deny("not allowed")
        assert result.behavior == ToolPermissionBehavior.DENY
        assert result.message == "not allowed"


# ---------------------------------------------------------------------------
# _prepare_browser_control_response
# ---------------------------------------------------------------------------


class TestPrepareBrowserControlResponse:
    def test_strips_heavy_keys(self):
        data = {
            "url": "https://example.com",
            "element_map": [{"node_id": "n1", "tag": "a"}],
            "browser_snapshot": "heavy",
            "frame_tree": "heavy",
            "image_data": "base64...",
            "html": "<html>",
        }
        result = _prepare_browser_control_response(data)
        assert "browser_snapshot" not in result
        assert "frame_tree" not in result
        assert "image_data" not in result
        assert "html" not in result
        assert result["element_count"] == 1

    def test_keep_image(self):
        data = {
            "url": "https://example.com",
            "element_map": [],
            "image_data": "base64...",
            "image_mime_type": "image/png",
        }
        result = _prepare_browser_control_response(data, keep_image=True)
        assert result.get("image_data") == "base64..."


# ---------------------------------------------------------------------------
# _prepare_extracted_content_response
# ---------------------------------------------------------------------------


class TestPrepareExtractedContentResponse:
    def test_empty_content_sets_unavailable(self):
        data: dict[str, Any] = {"content": "", "url": "https://example.com"}
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=True
        )
        assert result["content_unavailable"] is True
        assert result["chunk_count"] == 0

    def test_short_content_not_truncated(self):
        data: dict[str, Any] = {
            "content": "Short content",
            "url": "https://example.com",
            "title": "Test",
        }
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=False
        )
        assert result["inline_content_truncated"] is False
        assert result["content"] == "Short content"


# ---------------------------------------------------------------------------
# _browser_result_max_chars
# ---------------------------------------------------------------------------


class TestBrowserResultMaxChars:
    def test_default(self):
        ctx = _fake_context()
        assert _browser_result_max_chars(ctx) == 60_000

    def test_custom_limit(self):
        ctx = _fake_context(limits={"result_max_chars": 10_000})
        assert _browser_result_max_chars(ctx) == 10_000

    def test_invalid_limit(self):
        ctx = _fake_context(limits={"result_max_chars": "not_a_number"})
        assert _browser_result_max_chars(ctx) == 60_000


# ---------------------------------------------------------------------------
# _resolve_browser_page_target
# ---------------------------------------------------------------------------


class TestResolveBrowserPageTarget:
    def test_no_target_no_page_id(self):
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target({}, ctx, tool_name="BrowserClick")
        assert target_id is None
        assert error is None

    def test_explicit_page_id(self):
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target(
            {"page_id": "p1"}, ctx, tool_name="BrowserClick"
        )
        assert target_id == "p1"
        assert error is None

    def test_empty_browser_id_returns_error(self):
        ctx = _fake_context()
        target_id, error = _resolve_browser_page_target(
            {"browser_id": ""}, ctx, tool_name="BrowserClick"
        )
        assert error is not None
        assert "browser_id" in error


# ---------------------------------------------------------------------------
# _browser_action_permission
# ---------------------------------------------------------------------------


class TestBrowserActionPermission:
    @pytest.mark.asyncio
    async def test_returns_permission_result(self):
        ctx = _fake_context()
        result = await _browser_action_permission("BrowserClick", {}, ctx)
        assert result.behavior is not None
