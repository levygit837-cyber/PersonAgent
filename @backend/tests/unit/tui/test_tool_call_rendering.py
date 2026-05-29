"""Tests for TUI tool-call and memory-recall rendering fixes."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from personagent.adapters.tui.app import ChatApp
from personagent.adapters.tui.client.types import StreamChunk
from personagent.adapters.tui.widgets.tool_call_group import (
    MemoryRecallBlock,
    ToolCallGroup,
    ToolCallView,
    _status_style,
    _tool_label,
    is_tool_stream_event,
)


@pytest.fixture
def app() -> ChatApp:
    return ChatApp(base_url="http://localhost:8000")


# ---------------------------------------------------------------------------
# is_tool_stream_event
# ---------------------------------------------------------------------------


class TestIsToolStreamEvent:
    """Backend may send tool events with tool_name but no tool_call_id."""

    def test_true_when_tool_call_id_present(self) -> None:
        chunk = StreamChunk(event="tool_call_started", tool_call_id="t1", tool_name="Read")
        assert is_tool_stream_event(chunk) is True

    def test_true_when_only_tool_name_present(self) -> None:
        """Shell and generic tools often lack tool_call_id."""
        chunk = StreamChunk(event="tool_result", tool_name="shell")
        assert is_tool_stream_event(chunk) is True

    def test_false_when_neither_id_nor_name(self) -> None:
        chunk = StreamChunk(event="tool_result")
        assert is_tool_stream_event(chunk) is False

    def test_false_for_non_tool_event(self) -> None:
        chunk = StreamChunk(event="memory_recall_started", tool_name="x")
        assert is_tool_stream_event(chunk) is False


# ---------------------------------------------------------------------------
# _tool_label
# ---------------------------------------------------------------------------


class TestToolLabel:
    """Args/path move into parentheses for Read/Write/Shell; natural language for grep."""

    def test_read_shows_path_in_parens(self) -> None:
        call = ToolCallView(id="1", name="Read", args={"path": "src/main.py"})
        assert _tool_label(call) == "Read (src/main.py)"

    def test_write_shows_path_in_parens(self) -> None:
        call = ToolCallView(id="1", name="Write", args={"path": "README.md"})
        assert _tool_label(call) == "Write (README.md)"

    def test_shell_shows_command_in_parens(self) -> None:
        call = ToolCallView(id="1", name="shell", args={"command": "ls -la"})
        assert _tool_label(call) == "Shell (ls -la)"

    def test_shell_capitalised(self) -> None:
        call = ToolCallView(id="1", name="Shell", args={"command": "echo hi"})
        assert _tool_label(call) == "Shell (echo hi)"

    def test_grep_natural_language(self) -> None:
        call = ToolCallView(
            id="1", name="Grep", args={"pattern": "foo", "path": "src"}
        )
        assert _tool_label(call) == "Grep foo in src"

    def test_read_fallback_file(self) -> None:
        call = ToolCallView(id="1", name="Read", args={})
        assert _tool_label(call) == "Read (file)"


# ---------------------------------------------------------------------------
# ToolCallGroup styling & tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_shows_group_total_tokens_not_rows(app: ChatApp) -> None:
    """Only the group header shows tokens; individual rows do not."""
    async with app.run_test() as pilot:
        group = ToolCallGroup(model="deepseek-v4-flash")
        group._calls = [
            ToolCallView(id="t1", name="Read", token_count=15),
            ToolCallView(id="t2", name="Write", token_count=25),
        ]
        group._displayed_tokens = 40
        group._target_tokens = 40

        header = group._header()
        assert "40 tok" in header.plain

        # Individual rows must NOT show any token count
        rows = group._call_rows(group._calls[0])
        first_row = rows[0]
        assert isinstance(first_row, Text)
        assert "tok" not in first_row.plain

        rows2 = group._call_rows(group._calls[1])
        second_row = rows2[0]
        assert isinstance(second_row, Text)
        assert "tok" not in second_row.plain


@pytest.mark.asyncio
async def test_tool_name_is_white_dot_is_colored(app: ChatApp) -> None:
    """Only the dot and status word are coloured; the tool label is white."""
    async with app.run_test() as pilot:
        group = ToolCallGroup()
        group._calls = [ToolCallView(id="t1", name="Read", args={"path": "x.py"}, status="completed")]
        group._displayed_tokens = 0

        rows = group._call_rows(group._calls[0])
        row = rows[0]
        assert isinstance(row, Text)

        # Only the dot is colored; status word and label are white/default
        assert "Read (x.py)" in row.plain
        assert "Completed" in row.plain
        spans = list(row.spans)
        # Only one span: the dot → green
        assert len(spans) == 1
        assert spans[0].style == "green"
        assert "●" in row.plain[spans[0].start:spans[0].end]


@pytest.mark.asyncio
async def test_running_call_has_yellow_dot(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        group = ToolCallGroup()
        group._calls = [ToolCallView(id="t1", name="Read", status="running")]
        group._displayed_tokens = 0

        rows = group._call_rows(group._calls[0])
        row = rows[0]
        assert isinstance(row, Text)
        assert "Running" in row.plain
        spans = list(row.spans)
        assert len(spans) == 1
        assert spans[0].style == "yellow"
        assert "●" in row.plain[spans[0].start:spans[0].end]


@pytest.mark.asyncio
async def test_failed_call_has_red_dot(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        group = ToolCallGroup()
        group._calls = [ToolCallView(id="t1", name="Read", status="error")]
        group._displayed_tokens = 0

        rows = group._call_rows(group._calls[0])
        row = rows[0]
        assert isinstance(row, Text)
        assert "Failed" in row.plain
        spans = list(row.spans)
        assert len(spans) == 1
        assert spans[0].style == "red"
        assert "●" in row.plain[spans[0].start:spans[0].end]


# ---------------------------------------------------------------------------
# MemoryRecallBlock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_recall_hides_when_zero_completed(app: ChatApp) -> None:
    """A completed memory recall with 0 memories sets display=False."""
    async with app.run_test() as pilot:
        block = MemoryRecallBlock()
        block.update_from_chunk(
            StreamChunk(event="memory_recall_finished", memory_count=0)
        )
        assert block.display is False


@pytest.mark.asyncio
async def test_memory_recall_shows_when_non_zero(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        block = MemoryRecallBlock()
        block.update_from_chunk(
            StreamChunk(event="memory_recall_finished", memory_count=3)
        )
        assert block.display is not False
        renderable = block._build_renderable()
        assert isinstance(renderable, Text)
        assert "Recalled 3 memories" in renderable.plain


@pytest.mark.asyncio
async def test_memory_recall_shows_running_state(app: ChatApp) -> None:
    async with app.run_test() as pilot:
        block = MemoryRecallBlock()
        block.update_from_chunk(
            StreamChunk(event="memory_recall_started")
        )
        assert block.display is not False
        renderable = block._build_renderable()
        assert "Recalling" in renderable.plain
