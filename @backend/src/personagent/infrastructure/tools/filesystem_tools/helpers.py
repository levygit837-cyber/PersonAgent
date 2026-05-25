"""Shared helpers for filesystem tools."""

from __future__ import annotations

import difflib
import fnmatch
import json
from pathlib import Path
from typing import Any

from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
)

_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}

def _grep_with_python(
    *,
    search_path: Path,
    pattern: str,
    glob: Any,
    max_results: int,
    context: ToolUseContext,
    call: ToolCall,
) -> ToolResult:
    roots = (
        [search_path]
        if search_path.is_file()
        else [p for p in search_path.rglob("*") if p.is_file()]
    )
    lines: list[str] = []
    for path in roots:
        if _is_ignored(path):
            continue
        if isinstance(glob, str) and glob.strip() and not fnmatch.fnmatch(path.name, glob.strip()):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                lines.append(f"{path}:{number}:{line}")
                if len(lines) >= max_results + 1:
                    return _grep_result(lines, search_path, pattern, max_results, context, call)
    return _grep_result(lines, search_path, pattern, max_results, context, call)


def _grep_result(
    lines: list[str],
    search_path: Path,
    pattern: str,
    max_results: int,
    context: ToolUseContext,
    call: ToolCall,
) -> ToolResult:
    selected = lines[:max_results]
    formatted = "\n".join(_relativize_rg_line(line, context.workspace_root) for line in selected)
    truncated = len(lines) > len(selected)
    if truncated:
        formatted += f"\n[Output truncated. Showing {len(selected)} of {len(lines)} matches.]"

    data = {
        "type": "search_results",
        "path": str(search_path),
        "display_path": _display_path(search_path, context.workspace_root),
        "pattern": pattern,
        "content": formatted or "No matches found.",
        "matches": len(lines),
        "shown": len(selected),
        "truncated": truncated,
    }
    return ToolResult(
        tool_call_id=call.id,
        tool_name="Grep",
        content=json.dumps(data, ensure_ascii=False),
        data=data,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


def _error(
    call: ToolCall,
    tool_name: str,
    content: str,
    data: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=content,
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data or {},
    )


def _positive_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _relativize_rg_line(line: str, root: Path) -> str:
    file_part, sep, rest = line.partition(":")
    if not sep:
        return line
    return f"{_display_path(Path(file_part), root)}:{rest}"


def _is_ignored(path: Path) -> bool:
    return bool(set(path.parts).intersection(_IGNORED_DIRS))


def _diff(old_content: str, new_content: str, filename: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
    )


def _diff_line_counts(diff: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _line_count(content: str) -> int:
    if content == "":
        return 0
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return len(lines)


def _file_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {"const": "file_read"},
            "path": {"type": "string"},
            "display_path": {"type": "string"},
            "content": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "total_lines": {"type": "integer"},
            "returned_lines": {"type": "integer"},
            "requested_offset": {"type": "integer"},
            "requested_limit": {"type": "integer"},
            "effective_limit": {"type": "integer"},
            "limit_was_capped": {"type": "boolean"},
            "has_more": {"type": "boolean"},
            "next_offset": {"type": ["integer", "null"]},
            "truncated": {"type": "boolean"},
        },
        "required": ["type", "path", "display_path", "content"],
        "additionalProperties": True,
    }


def _mutation_output_schema(kind: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {"const": kind},
            "path": {"type": "string"},
            "display_path": {"type": "string"},
            "content": {"type": "string"},
            "diff": {"type": "string"},
            "written_content": {"type": "string"},
            "added_lines": {"type": "integer"},
            "removed_lines": {"type": "integer"},
        },
        "required": ["type", "path", "display_path", "content"],
        "additionalProperties": True,
    }


def _search_output_schema(kind: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {"const": kind},
            "path": {"type": "string"},
            "display_path": {"type": "string"},
            "content": {"type": "string"},
            "truncated": {"type": "boolean"},
        },
        "required": ["type", "path", "display_path", "content"],
        "additionalProperties": True,
    }
