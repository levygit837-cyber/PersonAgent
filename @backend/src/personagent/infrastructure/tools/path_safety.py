"""Utilitários de segurança de paths para ferramentas locais."""

from __future__ import annotations

from pathlib import Path

from personagent.domain.tools import ToolUseContext


def resolve_within_allowed_roots(raw_path: str | None, context: ToolUseContext) -> Path:
    """Resolve um path relativo ao cwd e garante que ele esteja em roots permitidos."""
    if raw_path is None or raw_path.strip() == "":
        candidate: Path = context.cwd
    else:
        path = Path(raw_path).expanduser()
        candidate = path if path.is_absolute() else context.cwd / path

    resolved: Path = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in context.allowed_roots):
        roots = ", ".join(str(root) for root in context.allowed_roots)
        raise ValueError(f"Path '{raw_path}' is outside allowed roots: {roots}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
