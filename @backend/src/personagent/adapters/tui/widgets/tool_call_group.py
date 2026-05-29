"""Grouped tool-call rendering for the chat stream."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.text import Text
from textual.app import RenderableType
from textual.widgets import Static

from personagent.adapters.tui.client.types import StreamChunk
from personagent.domain.token_counting import (
    count_text_tokens,
    count_tool_tokens,
    format_compact_tokens,
    token_animation_step,
)

_TOOL_EVENT_NAMES = {
    "tool_call_started",
    "tool_progress",
    "tool_result",
    "tool_error",
    "permission_required",
}
_RUNNING_STATUSES = {"queued", "running"}
_FAILED_STATUSES = {"error", "permission_required"}


@dataclass(slots=True)
class ToolCallView:
    """UI state for one tool call inside a contiguous group."""

    id: str
    name: str
    status: str = "running"
    args: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    error: str = ""
    message: str = ""
    token_count: int = 0


def is_tool_stream_event(chunk: StreamChunk) -> bool:
    """Return True for stream chunks that should update tool-call UI."""
    return bool(chunk.event in _TOOL_EVENT_NAMES and (chunk.tool_call_id or chunk.tool_name))


class ToolCallGroup(Static):
    """A Claude-Code-style group for sequential tool calls."""

    def __init__(self, *, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model = model
        self._calls: list[ToolCallView] = []
        self._displayed_tokens = 0
        self._target_tokens = 0
        self._token_timer = None
        self.update(self._build_renderable())

    @property
    def calls(self) -> list[ToolCallView]:
        return list(self._calls)

    def on_mount(self) -> None:
        self._token_timer = self.set_interval(0.04, self._tick_token_display)

    def on_unmount(self) -> None:
        if self._token_timer:
            self._token_timer.stop()

    def upsert_chunk(self, chunk: StreamChunk) -> None:
        """Create or update one tool row from a backend stream event."""
        call_id = chunk.tool_call_id or f"tool-{len(self._calls) + 1}"
        existing = next((item for item in self._calls if item.id == call_id), None)
        if existing is None:
            existing = ToolCallView(id=call_id, name=chunk.tool_name or "tool")
            self._calls.append(existing)

        existing.name = chunk.tool_name or existing.name
        existing.status = _parse_status(chunk)
        existing.args = _merged(existing.args, chunk.tool_input)
        existing.data = _merged(existing.data, chunk.tool_data)
        existing.result = chunk.tool_result or existing.result
        existing.error = chunk.tool_error or existing.error
        existing.message = chunk.tool_message or existing.message
        existing.token_count = count_tool_tokens(
            name=existing.name,
            arguments=existing.args,
            result=existing.error or existing.result,
            data=existing.data,
            model=self.model,
        )
        self._set_target_tokens(sum(item.token_count for item in self._calls))
        self.update(self._build_renderable())
        self.refresh()

    def _set_target_tokens(self, value: int) -> None:
        self._target_tokens = max(0, int(value or 0))
        if self._target_tokens < self._displayed_tokens:
            self._displayed_tokens = self._target_tokens

    def _tick_token_display(self) -> None:
        if self._displayed_tokens >= self._target_tokens:
            return
        self._displayed_tokens += token_animation_step(
            self._displayed_tokens,
            self._target_tokens,
        )
        self.update(self._build_renderable())

    def _build_renderable(self) -> RenderableType:
        if not self._calls:
            return Text("")
        parts: list[RenderableType] = [self._header()]
        for call in self._calls:
            parts.extend(self._call_rows(call))
        return Group(*parts)

    def _header(self) -> Text:
        status = _group_status(self._calls)
        text = Text()
        text.append("● ", style=_status_style(status))
        text.append(_group_label(status, len(self._calls)))
        text.append(f"  {format_compact_tokens(self._displayed_tokens)} tok", style="dim")
        return text

    def _call_rows(self, call: ToolCallView) -> list[RenderableType]:
        label = _tool_label(call)

        row = Text()
        row.append("  ● ", style=_status_style(call.status))
        row.append(_status_word_for_call(call))
        row.append(f" {label}")
        return [row]


@dataclass(slots=True)
class MemoryRecallState:
    status: str = "running"
    count: int = 0
    trace: dict[str, Any] | None = None
    token_count: int = 0


class MemoryRecallBlock(Static):
    """Inline memory recall state."""

    def __init__(self, *, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.state = MemoryRecallState()
        self._displayed_tokens = 0
        self._target_tokens = 0
        self._token_timer = None
        self.update(self._build_renderable())

    def on_mount(self) -> None:
        self._token_timer = self.set_interval(0.04, self._tick_token_display)

    def on_unmount(self) -> None:
        if self._token_timer:
            self._token_timer.stop()

    def update_from_chunk(self, chunk: StreamChunk) -> None:
        self.state.status = "completed" if chunk.event == "memory_recall_finished" else "running"
        if chunk.memory_count is not None:
            self.state.count = max(0, chunk.memory_count)
        if chunk.memory_trace:
            self.state.trace = chunk.memory_trace
            self.state.count = _memory_trace_count(chunk.memory_trace)
        if self.state.status == "completed" and self.state.count == 0:
            self.display = False
            return
        self.state.token_count = (
            count_text_tokens(
                json.dumps(self.state.trace, ensure_ascii=False, sort_keys=True),
                model=self.model,
            )
            if self.state.trace
            else 0
        )
        self._target_tokens = self.state.token_count
        if self._target_tokens < self._displayed_tokens:
            self._displayed_tokens = self._target_tokens
        self.update(self._build_renderable())
        self.refresh()

    def _tick_token_display(self) -> None:
        if self._displayed_tokens >= self._target_tokens:
            return
        self._displayed_tokens += token_animation_step(
            self._displayed_tokens,
            self._target_tokens,
        )
        self.update(self._build_renderable())

    def _build_renderable(self) -> RenderableType:
        if self.state.status == "completed" and self.state.count == 0:
            return Text("")
        text = Text()
        running = self.state.status == "running"
        style = "yellow" if running else "green"
        text.append("● ", style=style)
        if running:
            count = self.state.count
            label = f"Recalling {count} {_memory_word(count)}..." if count else "Recalling memories..."
        else:
            count = self.state.count
            label = f"Recalled {count} {_memory_word(count)}"
        text.append(label, style=style)
        text.append(f"  {format_compact_tokens(self._displayed_tokens)} tok", style="dim")
        return text


def is_memory_recall_event(chunk: StreamChunk) -> bool:
    return chunk.event in {"memory_recall_started", "memory_recall_finished"}


def _merged(existing: dict[str, Any], incoming: dict[str, Any] | None) -> dict[str, Any]:
    if not incoming:
        return dict(existing)
    return {**existing, **incoming}


def _parse_status(chunk: StreamChunk) -> str:
    if chunk.event == "permission_required":
        return "permission_required"
    if chunk.event == "tool_error":
        return "error"
    if chunk.event == "tool_result":
        return "completed" if chunk.tool_status != "error" else "error"
    if chunk.tool_status in {"queued", "running", "completed", "error", "permission_required"}:
        return chunk.tool_status
    return "running"


def _group_status(calls: list[ToolCallView]) -> str:
    if any(call.status in _FAILED_STATUSES for call in calls):
        return "error"
    if any(call.status in _RUNNING_STATUSES for call in calls):
        return "running"
    return "completed"


def _group_label(status: str, count: int) -> str:
    plural = "call" if count == 1 else "calls"
    if status in _RUNNING_STATUSES:
        return f"Running {count} tool {plural}..."
    if status == "error":
        return f"Failed {count} tool {plural}"
    return f"Completed {count} tool {plural}"


def _status_word(status: str) -> str:
    if status in _RUNNING_STATUSES:
        return "Running"
    if status in _FAILED_STATUSES:
        return "Failed"
    return "Completed"


def _status_word_for_call(call: ToolCallView) -> str:
    if _is_skill_invocation(call):
        if call.status in _RUNNING_STATUSES:
            return "Invoking"
        if call.status in _FAILED_STATUSES:
            return "Failed"
        return "Invoked"
    return _status_word(call.status)


def _status_style(status: str) -> str:
    if status in _RUNNING_STATUSES:
        return "yellow"
    if status in _FAILED_STATUSES:
        return "red"
    return "green"


def _tool_label(call: ToolCallView) -> str:
    name = call.name
    args = call.args
    data = call.data
    if name == "Skill":
        return _string(args.get("name")) or _string(data.get("name")) or "skill"
    if name in {"Read", "read_file"} and _is_skill_path(_path_from(call)):
        return Path(_path_from(call)).parent.name
    if name in {"Read", "read_file"}:
        path = _path_from(call) or "file"
        return f"Read ({path})"
    if name in {"Write", "Edit"}:
        return f"{name} ({_path_from(call) or 'file'})"
    if name.lower() == "shell":
        cmd = _string(args.get("command")) or _string(data.get("command")) or "shell command"
        return f"Shell ({cmd})"
    if name in {"Grep", "search_files"}:
        pattern = _string(args.get("pattern")) or _string(data.get("pattern")) or "pattern"
        path = _string(args.get("path")) or _string(data.get("path"))
        return f"Grep {pattern}{f' in {path}' if path else ''}"
    if name == "Glob":
        return f"Glob {_string(args.get('pattern')) or _string(data.get('pattern')) or 'pattern'}"
    if name in {"WebFetch", "WebSearch"}:
        target = _string(args.get("url")) or _string(args.get("query")) or _string(data.get("url"))
        return f"{name}{f' {target}' if target else ''}"
    if name.startswith("Browser"):
        target = (
            _string(args.get("url"))
            or _string(args.get("query"))
            or _string(args.get("node_id"))
            or _string(args.get("page_id"))
            or _string(args.get("window_id"))
        )
        return f"{name}{f' {target}' if target else ''}"
    if name in {"ListMcpResourcesTool", "ReadMcpResourceTool", "McpAuth"} or name.startswith("mcp__"):
        return _mcp_label(name, args, data)
    if name == "TodoWrite":
        todos = args.get("todos") or data.get("todos")
        count = len(todos) if isinstance(todos, list) else 0
        return f"TodoWrite {count} items" if count else "TodoWrite"
    if name == "ToolSearch":
        return f"ToolSearch {_string(args.get('query')) or ''}".strip()
    if name.startswith("Task") or name in {"Agent", "SendMessage", "AskUserQuestion", "SendUserMessage"}:
        subject = _string(args.get("title")) or _string(args.get("task_id")) or _string(args.get("message"))
        return f"{name}{f' {subject}' if subject else ''}"
    return f"{name}{f' {_compact_json(args)}' if args else ''}"


def _mcp_label(name: str, args: dict[str, Any], data: dict[str, Any]) -> str:
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        server = parts[1] if len(parts) > 1 else _string(data.get("server"))
        tool = parts[2] if len(parts) > 2 else _string(data.get("tool"))
        return f"MCP {server or 'server'}{f'/{tool}' if tool else ''}"
    server = _string(args.get("server")) or _string(data.get("server"))
    uri = _string(args.get("uri")) or _string(data.get("uri"))
    return f"{name}{f' {server}' if server else ''}{f' {uri}' if uri else ''}"


def _path_from(call: ToolCallView) -> str:
    return (
        _string(call.args.get("display_path"))
        or _string(call.data.get("display_path"))
        or _string(call.args.get("path"))
        or _string(call.data.get("path"))
        or ""
    )


def _is_skill_path(path: str) -> bool:
    return bool(path and Path(path).name == "SKILL.md")


def _is_skill_invocation(call: ToolCallView) -> bool:
    return call.name == "Skill" or (
        call.name in {"Read", "read_file"} and _is_skill_path(_path_from(call))
    )


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _compact_json(value: Any, *, max_chars: int = 120) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _memory_trace_count(trace: dict[str, Any]) -> int:
    summary = trace.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("total_used"), int):
        return max(0, int(summary["total_used"]))
    classic = trace.get("classic")
    operational = trace.get("operational")
    return (len(classic) if isinstance(classic, list) else 0) + (
        len(operational) if isinstance(operational, list) else 0
    )


def _memory_word(count: int) -> str:
    return "memory" if count == 1 else "memories"
