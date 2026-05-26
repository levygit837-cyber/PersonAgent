"""Resolvers for file-related context attachments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.domain.prompts.context_attachments._utils import (
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_CHARS,
    MAX_LINE_RANGE_LINES,
    _attachment_label,
    _display_path,
    _format_line_range,
    _int,
    _language_from_suffix,
    _read_line_range,
    _resolve_workspace_path,
    _string,
    _truncate,
    _wrap_attached_context,
)


def _resolve_file_range(
    raw: dict[str, Any],
    root: Path,
    *,
    index: int,
    kind: str,
) -> tuple[str, dict[str, Any]]:
    path = _resolve_workspace_path(_string(raw, "file_path", "path"), root)
    if not path.is_file():
        raise ValueError(f"Context attachment path is not a file: {path}")
    start_line = max(1, _int(raw, "start_line", "startLine", default=1))
    end_line = max(start_line, _int(raw, "end_line", "endLine", default=start_line))
    truncated_lines = False
    if end_line - start_line + 1 > MAX_LINE_RANGE_LINES:
        end_line = start_line + MAX_LINE_RANGE_LINES - 1
        truncated_lines = True
    language = _string(raw, "language", default="plaintext") or "plaintext"
    note = _string(raw, "text", "annotation", "note", default="")
    content, truncated_chars = _read_line_range(path, start_line, end_line)
    display_path = _display_path(raw, path, root)
    label = _attachment_label(
        raw,
        index=index,
        fallback="@Annotation" if kind == "viewer_annotation" else "@FileRange",
    )
    metadata = {
        "type": kind,
        "id": raw.get("id", index),
        "label": label,
        "file_name": path.name,
        "file_path": str(path),
        "display_path": display_path,
        "start_line": start_line,
        "end_line": end_line,
        "language": language,
        "text": note,
        "truncated": truncated_lines or truncated_chars,
    }
    reminder = _wrap_attached_context(
        kind,
        [
            f"Label: {label}",
            f"File: {display_path}",
            f"Absolute path: {path}",
            f"Lines: {_format_line_range(start_line, end_line)}",
            f"User annotation: {note or '(none)'}",
            "",
            "Attached file content:",
            f"```{'' if language == 'plaintext' else language}",
            content,
            "```",
        ],
    )
    return reminder, metadata


def _resolve_file(raw: dict[str, Any], root: Path, *, index: int) -> tuple[str, dict[str, Any]]:
    path = _resolve_workspace_path(_string(raw, "file_path", "path"), root)
    if not path.is_file():
        raise ValueError(f"Context attachment path is not a file: {path}")
    language = _string(raw, "language", default=_language_from_suffix(path)) or "plaintext"
    content, truncated = _truncate(path.read_text(encoding="utf-8", errors="replace"), MAX_FILE_CHARS)
    display_path = _display_path(raw, path, root)
    metadata = {
        "type": "file",
        "id": raw.get("id", index),
        "label": _attachment_label(raw, index=index, fallback="@File"),
        "file_name": path.name,
        "file_path": str(path),
        "display_path": display_path,
        "language": language,
        "truncated": truncated,
    }
    reminder = _wrap_attached_context(
        "file",
        [
            f"File: {display_path}",
            f"Absolute path: {path}",
            "",
            "Attached file content:",
            f"```{'' if language == 'plaintext' else language}",
            content,
            "```",
        ],
    )
    return reminder, metadata


def _resolve_directory(
    raw: dict[str, Any],
    root: Path,
    *,
    index: int,
) -> tuple[str, dict[str, Any]]:
    path = _resolve_workspace_path(_string(raw, "directory_path", "path"), root)
    if not path.is_dir():
        raise ValueError(f"Context attachment path is not a directory: {path}")
    entries: list[str] = []
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if len(entries) >= MAX_DIRECTORY_ENTRIES:
            break
        prefix = "dir " if child.is_dir() else "file"
        entries.append(f"{prefix}\t{child.name}")
    display_path = _display_path(raw, path, root)
    truncated = len(entries) >= MAX_DIRECTORY_ENTRIES
    metadata = {
        "type": "directory",
        "id": raw.get("id", index),
        "label": _attachment_label(raw, index=index, fallback="@Directory"),
        "display_path": display_path,
        "directory_path": str(path),
        "entry_count": len(entries),
        "truncated": truncated,
    }
    reminder = _wrap_attached_context(
        "directory",
        [
            f"Directory: {display_path}",
            f"Absolute path: {path}",
            f"Entries shown: {len(entries)}",
            "",
            "\n".join(entries) or "(empty)",
        ],
    )
    return reminder, metadata
