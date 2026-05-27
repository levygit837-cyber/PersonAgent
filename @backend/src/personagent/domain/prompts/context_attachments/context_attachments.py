"""Structured model-visible context attachments for chat turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personagent.domain.prompts.context_attachments._browser_resolvers import (
    _resolve_browser_annotation,
    _resolve_browser_tab,
)
from personagent.domain.prompts.context_attachments._file_resolvers import (
    _resolve_directory,
    _resolve_file,
    _resolve_file_range,
)
from personagent.domain.prompts.context_attachments._other_resolvers import (
    _resolve_command_context,
    _resolve_mcp_resource,
    _resolve_skill,
    _resolve_terminal_output,
)
from personagent.domain.prompts.context_attachments._utils import (
    MAX_ATTACHMENTS,
    _resolve_workspace_path,
)


@dataclass(frozen=True, slots=True)
class ResolvedContextAttachments:
    """Normalized context attachments ready for prompt injection and UI metadata."""

    reminders: list[str] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)


def resolve_context_attachments(
    attachments: list[dict[str, Any]] | None,
    *,
    workspace_root: str | Path,
    cwd: str | Path | None = None,
    extra_skill_roots: tuple[str | Path, ...] = (),
) -> ResolvedContextAttachments:
    """Validate and expand structured context attachments.

    The returned reminders are model-visible system-reminder payloads. The metadata is
    deliberately compact and safe to persist/render in the chat UI.
    """

    if not attachments:
        return ResolvedContextAttachments()

    root = Path(workspace_root).expanduser().resolve()
    skill_cwd = Path(cwd).expanduser().resolve() if cwd else root
    reminders: list[str] = []
    metadata: list[dict[str, Any]] = []
    for index, raw in enumerate(attachments[:MAX_ATTACHMENTS], start=1):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip()
        if kind in {"viewer_annotation", "file_range"}:
            reminder, summary = _resolve_file_range(raw, root, index=index, kind=kind)
        elif kind == "browser_annotation":
            reminder, summary = _resolve_browser_annotation(raw, index=index)
        elif kind == "browser_tab":
            reminder, summary = _resolve_browser_tab(raw, index=index)
        elif kind == "file":
            reminder, summary = _resolve_file(raw, root, index=index)
        elif kind == "directory":
            reminder, summary = _resolve_directory(raw, root, index=index)
        elif kind == "terminal_output":
            reminder, summary = _resolve_terminal_output(raw, index=index)
        elif kind == "mcp_resource":
            reminder, summary = _resolve_mcp_resource(raw, index=index)
        elif kind == "command_context":
            reminder, summary = _resolve_command_context(raw, index=index)
        elif kind == "skill":
            reminder, summary = _resolve_skill(
                raw,
                root,
                skill_cwd,
                extra_skill_roots=extra_skill_roots,
                index=index,
            )
        else:
            raise ValueError(f"Unsupported context attachment type: {kind or '(missing)'}")
        reminders.append(reminder)
        metadata.append(summary)
    return ResolvedContextAttachments(reminders=reminders, metadata=metadata)
