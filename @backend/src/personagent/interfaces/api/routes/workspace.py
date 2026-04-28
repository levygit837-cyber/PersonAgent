"""Routes for workspace filesystem navigation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from personagent.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/workspace", tags=["workspace"])
MAX_FILE_BYTES = 2 * 1024 * 1024


def _run_git_command(cwd: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
    """List files and directories for a path inside allowed roots."""
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
    """Read a text file inside the active workspace."""
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


@router.get("/git-status")
async def get_git_status(
    workspace_root: str | None = Query(None, description="Workspace root path"),
) -> dict[str, Any]:
    """Return current git status for the workspace."""
    try:
        resolved = _resolve_within_allowed_roots(workspace_root or ".", workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not (resolved / ".git").exists() and not (resolved.parent / ".git").exists():
        return {
            "branch": "",
            "ahead": 0,
            "behind": 0,
            "modified_count": 0,
            "untracked_count": 0,
            "is_dirty": False,
            "remote_url": None,
        }

    # Branch
    branch_result = _run_git_command(resolved, ["branch", "--show-current"])
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    # Ahead/Behind
    ahead, behind = 0, 0
    rev_result = _run_git_command(resolved, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if rev_result.returncode == 0:
        parts = rev_result.stdout.strip().split("\t")
        if len(parts) == 2:
            try:
                ahead = int(parts[0])
                behind = int(parts[1])
            except ValueError:
                pass

    # Modified / Untracked
    status_result = _run_git_command(resolved, ["status", "--short"])
    modified_count = 0
    untracked_count = 0
    if status_result.returncode == 0:
        for line in status_result.stdout.strip().splitlines():
            if not line:
                continue
            if line.startswith("??"):
                untracked_count += 1
            else:
                modified_count += 1

    # Remote URL
    remote_result = _run_git_command(resolved, ["remote", "get-url", "origin"])
    remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None

    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "modified_count": modified_count,
        "untracked_count": untracked_count,
        "is_dirty": modified_count > 0 or untracked_count > 0,
        "remote_url": remote_url,
    }


class GitCommitRequest(BaseModel):
    workspace_root: str
    message: str


@router.post("/git-commit")
async def git_commit(payload: GitCommitRequest) -> dict[str, Any]:
    """Stage all changes and create a git commit."""
    try:
        cwd = _resolve_within_allowed_roots(payload.workspace_root, payload.workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    add_result = _run_git_command(cwd, ["add", "-A"])
    if add_result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"git add failed: {add_result.stderr}")

    commit_result = _run_git_command(cwd, ["commit", "-m", payload.message])
    if commit_result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"git commit failed: {commit_result.stderr}")

    return {"success": True, "output": commit_result.stdout.strip()}


class GitPushRequest(BaseModel):
    workspace_root: str


@router.post("/git-push")
async def git_push(payload: GitPushRequest) -> dict[str, Any]:
    """Push current branch to remote."""
    try:
        cwd = _resolve_within_allowed_roots(payload.workspace_root, payload.workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    push_result = _run_git_command(cwd, ["push"], timeout=30)
    if push_result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"git push failed: {push_result.stderr}")

    return {"success": True, "output": push_result.stdout.strip()}


class GitPrRequest(BaseModel):
    workspace_root: str


@router.post("/git-pr")
async def git_open_pr(payload: GitPrRequest) -> dict[str, Any]:
    """Try to open a PR using gh CLI, or return the remote URL."""
    try:
        cwd = _resolve_within_allowed_roots(payload.workspace_root, payload.workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # Try gh pr create
    pr_result = _run_git_command(cwd, ["gh", "pr", "create", "--fill"], timeout=30)
    if pr_result.returncode == 0:
        # Extract URL from output
        url = pr_result.stdout.strip().splitlines()[-1]
        return {"success": True, "url": url, "output": pr_result.stdout.strip()}

    # Fallback: return remote URL
    remote_result = _run_git_command(cwd, ["remote", "get-url", "origin"])
    remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None
    if remote_url and remote_url.endswith(".git"):
        remote_url = remote_url[:-4]
    if remote_url:
        remote_url = remote_url.replace(":", "/").replace("git@", "https://")

    return {"success": False, "url": remote_url, "output": pr_result.stderr.strip()}
