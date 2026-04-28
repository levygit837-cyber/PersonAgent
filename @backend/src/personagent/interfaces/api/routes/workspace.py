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


def _is_git_repo(cwd: Path) -> bool:
    result = _run_git_command(cwd, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


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


def _resolve_workspace(workspace_root: str) -> Path:
    try:
        return _resolve_within_allowed_roots(workspace_root, workspace_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _git_error(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    return f"{message}: {detail}" if detail else message


def _git_branch_item(line: str, current_branch: str, kind: str) -> dict[str, Any] | None:
    parts = line.split("\x00", 3)
    if len(parts) != 4:
        return None
    name, upstream, last_commit_iso, last_commit_subject = parts
    if not name or name.endswith("/HEAD"):
        return None
    return {
        "name": name,
        "kind": kind,
        "current": kind == "local" and name == current_branch,
        "upstream": upstream or None,
        "last_commit_iso": last_commit_iso or None,
        "last_commit_subject": last_commit_subject or None,
    }


def _remote_tracking_branch_name(remote_ref: str) -> str:
    if "/" not in remote_ref:
        return remote_ref
    return remote_ref.split("/", 1)[1]


def _local_branch_exists(cwd: Path, branch_name: str) -> bool:
    result = _run_git_command(cwd, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
    return result.returncode == 0


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
    if workspace_root:
        resolved = _resolve_workspace(workspace_root)
    else:
        try:
            resolved = _resolve_within_allowed_roots(".", None)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not _is_git_repo(resolved):
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


class GitBranchCreateRequest(BaseModel):
    workspace_root: str
    name: str


class GitCheckoutRequest(BaseModel):
    workspace_root: str
    name: str
    kind: str = "local"


@router.get("/git-branches")
async def get_git_branches(
    workspace_root: str | None = Query(None, description="Workspace root path"),
) -> dict[str, Any]:
    """Return local and remote branches for the workspace."""
    if not workspace_root:
        return {"is_repo": False, "current": "", "branches": []}

    cwd = _resolve_workspace(workspace_root)
    if not _is_git_repo(cwd):
        return {"is_repo": False, "current": "", "branches": []}

    current_result = _run_git_command(cwd, ["branch", "--show-current"])
    current_branch = current_result.stdout.strip() if current_result.returncode == 0 else ""
    format_spec = "%(refname:short)%00%(upstream:short)%00%(committerdate:iso8601-strict)%00%(contents:subject)"
    branches: list[dict[str, Any]] = []
    local_branch_names: set[str] = set()
    local_upstreams: set[str] = set()

    local_result = _run_git_command(
        cwd,
        ["for-each-ref", f"--format={format_spec}", "--sort=-committerdate", "refs/heads"],
    )
    if local_result.returncode == 0:
        for line in local_result.stdout.splitlines():
            item = _git_branch_item(line, current_branch, "local")
            if item:
                branches.append(item)
                local_branch_names.add(str(item["name"]))
                if item["upstream"]:
                    local_upstreams.add(str(item["upstream"]))

    remote_result = _run_git_command(
        cwd,
        ["for-each-ref", f"--format={format_spec}", "--sort=-committerdate", "refs/remotes"],
    )
    if remote_result.returncode == 0:
        for line in remote_result.stdout.splitlines():
            item = _git_branch_item(line, current_branch, "remote")
            if item:
                remote_name = str(item["name"])
                if remote_name in local_upstreams:
                    continue
                if _remote_tracking_branch_name(remote_name) in local_branch_names:
                    continue
                branches.append(item)

    return {"is_repo": True, "current": current_branch, "branches": branches}


@router.post("/git-branches")
async def git_create_branch(payload: GitBranchCreateRequest) -> dict[str, Any]:
    """Create and switch to a new branch from the current HEAD."""
    cwd = _resolve_workspace(payload.workspace_root)
    if not _is_git_repo(cwd):
        raise HTTPException(status_code=400, detail="No Git repository detected")

    branch_name = payload.name.strip()
    if not branch_name or branch_name.startswith("-"):
        raise HTTPException(status_code=400, detail="Invalid branch name")

    check_result = _run_git_command(cwd, ["check-ref-format", "--branch", branch_name])
    if check_result.returncode != 0:
        raise HTTPException(status_code=400, detail=_git_error("Invalid branch name", check_result))

    switch_result = _run_git_command(cwd, ["switch", "-c", branch_name])
    if switch_result.returncode != 0:
        raise HTTPException(status_code=409, detail=_git_error("git switch failed", switch_result))

    return {"success": True, "branch": branch_name, "output": switch_result.stdout.strip()}


@router.post("/git-checkout")
async def git_checkout_branch(payload: GitCheckoutRequest) -> dict[str, Any]:
    """Switch to an existing local branch or create a tracking branch from a remote."""
    cwd = _resolve_workspace(payload.workspace_root)
    if not _is_git_repo(cwd):
        raise HTTPException(status_code=400, detail="No Git repository detected")

    branch_name = payload.name.strip()
    if not branch_name or branch_name.startswith("-"):
        raise HTTPException(status_code=400, detail="Invalid branch name")

    if payload.kind == "local":
        switch_args = ["switch", branch_name]
    elif payload.kind == "remote":
        tracking_branch = _remote_tracking_branch_name(branch_name)
        switch_args = ["switch", tracking_branch] if _local_branch_exists(cwd, tracking_branch) else ["switch", "--track", branch_name]
    else:
        raise HTTPException(status_code=400, detail="Branch kind must be 'local' or 'remote'")

    switch_result = _run_git_command(cwd, switch_args)
    if switch_result.returncode != 0:
        raise HTTPException(status_code=409, detail=_git_error("git switch failed", switch_result))

    current_result = _run_git_command(cwd, ["branch", "--show-current"])
    current_branch = current_result.stdout.strip() if current_result.returncode == 0 else branch_name
    return {"success": True, "branch": current_branch, "output": switch_result.stdout.strip()}


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
