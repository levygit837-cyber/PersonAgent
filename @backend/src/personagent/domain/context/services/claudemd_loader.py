"""Compatibility wrapper for Claude-style memory files."""

from __future__ import annotations

from pathlib import Path

from personagent.domain.context.services.personamd_loader import PersonaMdLoader


class ClaudeMdLoader(PersonaMdLoader):  # type: ignore[misc]
    """Backward-compatible loader name for callers that still use ClaudeMdLoader."""

    def __init__(
        self,
        workspace_root: str | Path,
        enable_claude_md: bool = True,
        additional_directories: list[str | Path] | None = None,
    ) -> None:
        super().__init__(
            workspace_root=workspace_root,
            enable_persona_md=enable_claude_md,
            additional_directories=additional_directories,
        )


__all__ = ["ClaudeMdLoader"]
