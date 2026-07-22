"""Tests for pure helper functions in ``tool_result_budget_helpers.py``."""

from __future__ import annotations

from typing import Any

import pytest

from personagent.application.use_cases.chat.tooling.tool_result_budget_helpers import (
    _ToolResultCandidate,
    _build_preview_message,
    _collect_candidates_by_assistant_turn,
    _is_content_already_compacted,
    _replace_tool_result_contents,
    _select_fresh_to_replace,
)
from personagent.domain.tools.tool_result_budget import (
    PERSISTED_OUTPUT_TAG,
    generate_preview,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _assistant_msg(content: str = "calling tool", tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or []}


def _tool_msg(content: str, tool_call_id: str) -> dict[str, Any]:
    return {"role": "tool", "content": content, "tool_call_id": tool_call_id}


def _user_msg(content: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


# ---------------------------------------------------------------------------
# generate_preview (domain module)
# ---------------------------------------------------------------------------


def test_generate_preview_returns_full_when_under_limit() -> None:
    text = "line1\nline2\nline3"
    preview, has_more = generate_preview(text, 100)
    assert preview == text
    assert has_more is False


def test_generate_preview_truncates_at_newline_when_possible() -> None:
    lines = "\n".join(f"line {i}" for i in range(100))
    preview, has_more = generate_preview(lines, 200)
    assert has_more is True
    assert preview.endswith("line 25")


def test_generate_preview_falls_back_to_exact_limit_when_no_newline() -> None:
    text = "a" * 1_000
    preview, has_more = generate_preview(text, 100)
    assert len(preview) == 100
    assert has_more is True


# ---------------------------------------------------------------------------
# _is_content_already_compacted
# ---------------------------------------------------------------------------


def test_is_content_already_compacted_detects_tag() -> None:
    assert _is_content_already_compacted(f"{PERSISTED_OUTPUT_TAG}\nfoo") is True


def test_is_content_already_compacted_ignores_mid_content_tag() -> None:
    assert _is_content_already_compacted(f"foo\n{PERSISTED_OUTPUT_TAG}") is False


def test_is_content_already_compacted_rejects_normal_content() -> None:
    assert _is_content_already_compacted("normal tool result") is False


# ---------------------------------------------------------------------------
# _collect_candidates_by_assistant_turn
# ---------------------------------------------------------------------------


def test_collect_candidates_groups_by_assistant_boundary() -> None:
    rendered = [
        _assistant_msg(),
        _tool_msg("a" * 10_000, "t1"),
        _tool_msg("b" * 20_000, "t2"),
        _assistant_msg(),
        _tool_msg("c" * 5_000, "t3"),
    ]
    groups = _collect_candidates_by_assistant_turn(rendered)
    assert len(groups) == 2
    assert [c.tool_call_id for c in groups[0]] == ["t1", "t2"]
    assert [c.tool_call_id for c in groups[1]] == ["t3"]


def test_collect_candidates_skips_empty_and_compacted() -> None:
    rendered = [
        _assistant_msg(),
        _tool_msg("", "t1"),
        _tool_msg(f"{PERSISTED_OUTPUT_TAG}\nfoo", "t2"),
        _tool_msg("valid", "t3"),
    ]
    groups = _collect_candidates_by_assistant_turn(rendered)
    assert len(groups) == 1
    assert [c.tool_call_id for c in groups[0]] == ["t3"]


def test_collect_candidates_without_leading_assistant() -> None:
    rendered = [
        _tool_msg("a" * 1_000, "t1"),
        _assistant_msg(),
        _tool_msg("b" * 1_000, "t2"),
    ]
    groups = _collect_candidates_by_assistant_turn(rendered)
    assert len(groups) == 2
    assert [c.tool_call_id for c in groups[0]] == ["t1"]
    assert [c.tool_call_id for c in groups[1]] == ["t2"]


# ---------------------------------------------------------------------------
# _select_fresh_to_replace
# ---------------------------------------------------------------------------


def test_select_fresh_returns_empty_when_under_budget() -> None:
    fresh = [
        _ToolResultCandidate("t1", "x" * 10_000, 10_000),
        _ToolResultCandidate("t2", "y" * 20_000, 20_000),
    ]
    selected = _select_fresh_to_replace(fresh, frozen_size=0, limit=200_000)
    assert selected == []


def test_select_fresh_replaces_largest_first() -> None:
    fresh = [
        _ToolResultCandidate("t1", "x" * 30_000, 30_000),
        _ToolResultCandidate("t2", "y" * 80_000, 80_000),
        _ToolResultCandidate("t3", "z" * 50_000, 50_000),
    ]
    selected = _select_fresh_to_replace(fresh, frozen_size=0, limit=100_000)
    ids = [c.tool_call_id for c in selected]
    assert ids == ["t2"]
    assert "t1" not in ids


def test_select_fresh_respects_frozen_size() -> None:
    fresh = [
        _ToolResultCandidate("t1", "x" * 50_000, 50_000),
    ]
    selected = _select_fresh_to_replace(fresh, frozen_size=180_000, limit=200_000)
    assert [c.tool_call_id for c in selected] == ["t1"]


# ---------------------------------------------------------------------------
# _replace_tool_result_contents
# ---------------------------------------------------------------------------


def test_replace_tool_result_contents_replaces_target_ids() -> None:
    rendered = [
        _assistant_msg(),
        _tool_msg("old1", "t1"),
        _tool_msg("old2", "t2"),
        _user_msg("hi"),
    ]
    replacement_map = {"t1": "new1"}
    result = _replace_tool_result_contents(rendered, replacement_map)
    assert result[1]["content"] == "new1"
    assert result[2]["content"] == "old2"
    assert result[3]["content"] == "hi"


def test_replace_tool_result_contents_returns_same_list_when_empty_map() -> None:
    rendered = [_tool_msg("old", "t1")]
    result = _replace_tool_result_contents(rendered, {})
    assert result is rendered


# ---------------------------------------------------------------------------
# _build_preview_message
# ---------------------------------------------------------------------------


def test_build_preview_message_includes_storage_ref_and_preview() -> None:
    msg = _build_preview_message(
        storage_ref="/tmp/out.txt",
        original_size=12345,
        preview_text="first lines...",
        has_more=True,
    )
    assert PERSISTED_OUTPUT_TAG in msg
    assert "/tmp/out.txt" in msg
    assert "12,345" in msg
    assert "first lines..." in msg
    assert "..." in msg
