"""Utilitários de segurança de paths para ferramentas locais."""

from __future__ import annotations

from pathlib import Path

from personagent.domain.tools import ToolUseContext


def resolve_within_allowed_roots(raw_path: str | None, context: ToolUseContext) -> Path:
    """Resolve um path relativo ao cwd e garante que ele esteja em roots permitidos."""
    active_cwd = context.metadata.get("active_cwd")
    cwd = Path(str(active_cwd)).expanduser().resolve() if active_cwd else context.cwd
    roots = _allowed_roots(context)
    if raw_path is None or raw_path.strip() == "":
        candidate: Path = cwd
    else:
        path = Path(raw_path).expanduser()
        candidate = path if path.is_absolute() else cwd / path

    resolved: Path = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in roots):
        roots_text = ", ".join(str(root) for root in roots)
        raise ValueError(f"Path '{raw_path}' is outside allowed roots: {roots_text}")
    return resolved


def _allowed_roots(context: ToolUseContext) -> tuple[Path, ...]:
    active_roots = context.metadata.get("active_allowed_roots")
    if not active_roots:
        return context.allowed_roots
    return tuple(Path(str(root)).expanduser().resolve() for root in active_roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
