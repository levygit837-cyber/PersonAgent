"""Resolvers for terminal, MCP, command-context, and skill attachments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.domain.prompts.context_attachments._utils import (
    MAX_COMMAND_CONTEXT_CHARS,
    MAX_MCP_RESOURCE_CHARS,
    MAX_SKILL_CHARS,
    MAX_TERMINAL_CHARS,
    _attachment_label,
    _display_path,
    _single_line_preview,
    _string,
    _truncate,
    _wrap_attached_context,
)
from personagent.domain.prompts.skills import find_skill, is_skill_enabled, skill_source


def _resolve_terminal_output(raw: dict[str, Any], *, index: int) -> tuple[str, dict[str, Any]]:
    content = _string(raw, "content", "output")
    shell = _string(raw, "shell", default="bash") or "bash"
    content, truncated = _truncate(content, MAX_TERMINAL_CHARS)
    metadata = {
        "type": "terminal_output",
        "id": raw.get("id", index),
        "label": _attachment_label(raw, index=index, fallback="@terminal"),
        "shell": shell,
        "content_preview": _single_line_preview(content),
        "content_char_count": len(content),
        "truncated": truncated,
    }
    reminder = _wrap_attached_context(
        "terminal_output",
        [
            f"Shell: {shell}",
            "",
            "Attached terminal output:",
            f"```{shell}",
            content,
            "```",
        ],
    )
    return reminder, metadata


def _resolve_mcp_resource(raw: dict[str, Any], *, index: int) -> tuple[str, dict[str, Any]]:
    server = _string(raw, "server", "server_name")
    uri = _string(raw, "uri", "resource_uri")
    content = _string(raw, "content", default="")
    content, truncated = _truncate(content, MAX_MCP_RESOURCE_CHARS)
    metadata = {
        "type": "mcp_resource",
        "id": raw.get("id", index),
        "label": _attachment_label(raw, index=index, fallback="@mcp"),
        "server": server,
        "uri": uri,
        "has_content": bool(content),
        "truncated": truncated,
    }
    body = [
        f"MCP server: {server}",
        f"Resource URI: {uri}",
    ]
    if content:
        body.extend(["", "Attached MCP resource content:", "```", content, "```"])
    else:
        body.extend(
            [
                "",
                "The user referenced this MCP resource. If the content is required and the "
                "ReadMcpResourceTool is available, read it before relying on it.",
            ]
        )
    return _wrap_attached_context("mcp_resource", body), metadata


def _resolve_command_context(raw: dict[str, Any], *, index: int) -> tuple[str, dict[str, Any]]:
    command = _string(raw, "command", "name", default="command_context")
    content = _string(raw, "content", "hidden_context")
    content, truncated = _truncate(content, MAX_COMMAND_CONTEXT_CHARS)
    metadata = {
        "type": "command_context",
        "id": raw.get("id", index),
        "label": _attachment_label(raw, index=index, fallback=f"/{command.lstrip('/')}"),
        "command": command,
        "truncated": truncated,
    }
    return _wrap_attached_context("command_context", [f"Command: {command}", "", content]), metadata


def _resolve_skill(
    raw: dict[str, Any],
    root: Path,
    cwd: Path,
    *,
    extra_skill_roots: tuple[str | Path, ...],
    index: int,
) -> tuple[str, dict[str, Any]]:
    invocation = _string(raw, "invocation_name", "name", "skill")
    if not invocation:
        raise ValueError("Context attachment is missing a skill invocation name.")
    skill = find_skill(
        invocation,
        workspace_root=root,
        cwd=cwd,
        extra_roots=extra_skill_roots,
        include_global=True,
    )
    if skill is None:
        raise ValueError(f"Context attachment skill not found: {invocation}")
    if not is_skill_enabled(
        skill,
        workspace_root=root,
        cwd=cwd,
        extra_roots=extra_skill_roots,
    ):
        raise ValueError(f"Context attachment skill is disabled: {skill.invocation_name}")

    content, truncated = _truncate(skill.body.strip(), MAX_SKILL_CHARS)
    source = skill_source(
        skill,
        workspace_root=root,
        cwd=cwd,
        extra_roots=extra_skill_roots,
    )
    label = _attachment_label(raw, index=index, fallback=f"@skill:{skill.invocation_name}")
    metadata = {
        "type": "skill",
        "id": raw.get("id", index),
        "label": label,
        "name": skill.name,
        "invocation_name": skill.invocation_name,
        "slash_name": skill.slash_name,
        "description": skill.description,
        "path": str(skill.path),
        "display_path": _display_path(raw, skill.path, root),
        "source": source,
        "truncated": truncated,
    }
    reminder = _wrap_attached_context(
        "skill",
        [
            f"Skill: {skill.name}",
            f"Invocation: {skill.slash_name}",
            f"Source: {source}",
            f"Path: {skill.path}",
            f"Description: {skill.description or '(none)'}",
            "",
            "Attached skill instructions:",
            content,
        ],
    )
    return reminder, metadata
