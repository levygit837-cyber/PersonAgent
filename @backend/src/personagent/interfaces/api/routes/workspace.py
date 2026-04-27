"""Rotas para navegação de workspace no filesystem."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from personagent.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/workspace", tags=["workspace"])
MAX_FILE_BYTES = 2 * 1024 * 1024


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_within_allowed_roots(raw_path: str, workspace_root: str | None = None) -> Path:
    settings = get_settings()
    path = Path(raw_path).expanduser()
    resolved = path.resolve()

    if workspace_root:
        active_workspace = Path(workspace_root).expanduser().resolve()
        if not _is_relative_to(resolved, active_workspace):
            raise ValueError(f"Path '{raw_path}' is outside active workspace: {active_workspace}")
        return resolved

    allowed_roots = list(settings.tool_allowed_root_paths)
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(f"Path '{raw_path}' is outside allowed roots: {roots}")
    return resolved


@router.get("/files")
async def list_workspace_files(
    path: str = Query(..., description="Absolute path to the directory to list"),
    workspace_root: str | None = Query(None, description="Optional workspace root to allow browsing outside default tool roots"),
) -> list[dict[str, str | bool]]:
    """Lista arquivos e diretórios de um caminho dentro dos roots permitidos."""
    try:
        resolved = _resolve_within_allowed_roots(path, workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

    try:
        entries = os.listdir(resolved)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read directory: {exc}") from exc

    result: list[dict[str, str | bool]] = []
    for name in entries:
        entry_path = resolved / name
        result.append(
            {
                "name": name,
                "isDirectory": entry_path.is_dir(),
                "path": str(entry_path),
            }
        )

    result.sort(key=lambda e: (not e["isDirectory"], str(e["name"]).lower()))
    return result


@router.get("/file")
async def read_workspace_file(
    path: str = Query(..., description="Absolute path to the file to read"),
    workspace_root: str | None = Query(None, description="Optional workspace root to allow browsing outside default tool roots"),
) -> dict[str, str]:
    """Lê um arquivo de texto dentro do workspace ativo."""
    try:
        resolved = _resolve_within_allowed_roots(path, workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File is too large to preview: {path}")

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc

    return {
        "path": str(resolved),
        "name": resolved.name,
        "content": content,
    }
