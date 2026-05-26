"""Filesystem and mention endpoints for workspace routes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from personagent.adapters.api.routes.workspace.helpers import (
    MAX_FILE_BYTES,
    MAX_MENTION_SCAN_PATHS,
    MENTION_SKIP_DIRS,
    WorkspaceMentionSuggestion,
    _git_repo_root,
    _is_relative_to,
    _looks_like_git_repo,
    _resolve_within_allowed_roots,
    _resolve_workspace,
    _run_git_command,
)
from personagent.infrastructure.settings.settings import get_settings


def _display_workspace_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _mention_score(display_path: str, name: str, query: str) -> float | None:
    normalized_query = query.strip().replace("\\", "/").lower()
    display = display_path.lower()
    basename = name.lower()
    depth_penalty = min(display.count("/"), 20) * 0.01
    if not normalized_query:
        return depth_penalty
    if display == normalized_query or basename == normalized_query:
        return depth_penalty
    if display.startswith(normalized_query):
        return 1 + depth_penalty
    if basename.startswith(normalized_query):
        return 2 + depth_penalty
    if normalized_query in display:
        return 3 + depth_penalty
    if _is_subsequence(normalized_query, display):
        return 4 + depth_penalty
    return None


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    index = 0
    for char in haystack:
        if char == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


def _workspace_mention_item(path: Path, root: Path, query: str) -> WorkspaceMentionSuggestion | None:
    resolved = path.resolve()
    if not _is_relative_to(resolved, root):
        return None
    display_path = _display_workspace_path(resolved, root)
    if not display_path or display_path == ".":
        return None
    name = resolved.name or display_path.rstrip("/").rsplit("/", 1)[-1]
    score = _mention_score(display_path, name, query)
    if score is None:
        return None
    is_directory = resolved.is_dir()
    return WorkspaceMentionSuggestion(
        type="directory" if is_directory else "file",
        name=name,
        path=str(resolved),
        display_path=display_path + ("/" if is_directory and not display_path.endswith("/") else ""),
        is_directory=is_directory,
        score=score,
    )


def _git_workspace_paths(root: Path) -> list[Path] | None:
    repo_root = _git_repo_root(root)
    if repo_root is None:
        return None
    file_paths: set[Path] = set()
    for args in (
        ["-c", "core.quotepath=false", "ls-files", "--full-name", "--recurse-submodules"],
        ["-c", "core.quotepath=false", "ls-files", "--full-name", "--others", "--exclude-standard"],
    ):
        result = _run_git_command(root, args, timeout=8)
        if result.returncode != 0:
            return None
        for raw in result.stdout.splitlines():
            if not raw.strip():
                continue
            candidate = (repo_root / raw).resolve()
            if _is_relative_to(candidate, root):
                file_paths.add(candidate)

    paths: set[Path] = set(file_paths)
    for file_path in file_paths:
        parent = file_path.parent
        while parent != root and _is_relative_to(parent, root):
            paths.add(parent)
            next_parent = parent.parent
            if next_parent == parent:
                break
            parent = next_parent
    return list(paths)


def _walk_workspace_paths(root: Path, query: str) -> list[Path]:
    paths: list[Path] = []
    if not query.strip():
        try:
            return [entry for entry in root.iterdir() if entry.name not in MENTION_SKIP_DIRS]
        except OSError:
            return []

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in MENTION_SKIP_DIRS]
        current = Path(current_root)
        for dirname in dirnames:
            paths.append(current / dirname)
            if len(paths) >= MAX_MENTION_SCAN_PATHS:
                return paths
        for filename in filenames:
            paths.append(current / filename)
            if len(paths) >= MAX_MENTION_SCAN_PATHS:
                return paths
    return paths


def _workspace_mention_suggestions(root: Path, query: str, limit: int) -> list[WorkspaceMentionSuggestion]:
    paths = _git_workspace_paths(root)
    if paths is None:
        paths = _walk_workspace_paths(root, query)
    suggestions = [
        item
        for item in (_workspace_mention_item(path, root, query) for path in paths)
        if item is not None
    ]
    suggestions.sort(
        key=lambda item: (
            item.score,
            0 if item.is_directory else 1,
            item.display_path.lower(),
        )
    )
    return suggestions[: max(1, min(limit, 100))]


def _workspace_project_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved in seen or not _looks_like_git_repo(resolved):
            return
        seen.add(resolved)
        candidates.append(resolved)

    for root in get_settings().tool_allowed_root_paths:
        try:
            resolved_root = root.expanduser().resolve()
        except OSError:
            continue
        add(resolved_root)
        if resolved_root.is_dir():
            for child in sorted(resolved_root.iterdir(), key=lambda item: item.name.lower()):
                add(child)
        parent = resolved_root.parent
        if parent.name.lower() in {"projetos", "projects"} and parent.is_dir():
            for child in sorted(parent.iterdir(), key=lambda item: item.name.lower()):
                add(child)

    return candidates[:50]


def register_filesystem_routes(router: APIRouter) -> None:
    """Register filesystem and mention endpoints on the given router."""

    @router.get("/files")
    async def list_workspace_files(
        path: str = Query(..., description="Absolute path to the directory to list"),
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> list[dict[str, str | bool]]:
        """List files and directories for a path inside allowed roots."""
        try:
            resolved = _resolve_within_allowed_roots(path, workspace_root, workspace_id)
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

    @router.get("/mentions", response_model=list[WorkspaceMentionSuggestion])
    async def list_workspace_mentions(
        q: str = Query(default="", description="Partial @ mention query"),
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
        limit: int = Query(default=40, ge=1, le=100),
    ) -> list[WorkspaceMentionSuggestion]:
        """Return file and directory suggestions for composer @ mentions."""
        root = _resolve_workspace(workspace_root, workspace_id)
        return _workspace_mention_suggestions(root, q, limit)

    @router.get("/file")
    async def read_workspace_file(
        path: str = Query(..., description="Absolute path to the file to read"),
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, str]:
        """Read a text file inside the active workspace."""
        try:
            resolved = _resolve_within_allowed_roots(path, workspace_root, workspace_id)
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

    @router.get("/projects")
    async def get_workspace_projects() -> dict[str, Any]:
        """Return nearby Git workspaces for project selection."""
        projects = [{"name": path.name, "path": str(path), "is_repo": True} for path in _workspace_project_candidates()]
        return {"projects": projects}
