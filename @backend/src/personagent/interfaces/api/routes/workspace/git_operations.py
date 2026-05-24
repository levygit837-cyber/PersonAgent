"""Local git operation endpoints and helpers for workspace routes."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from personagent.interfaces.api.action_approvals import require_action_approval
from personagent.interfaces.api.routes.workspace.helpers import (
    GIT_STAGE_TIMEOUT_SECONDS,
    _approval_arguments,
    _cleanup_stale_git_index_lock,
    _git_error,
    _git_output,
    _git_repo_root,
    _is_git_repo,
    _publish_git_change,
    _resolve_within_allowed_roots,
    _resolve_workspace,
    _run_git_command,
)


def _git_branch_item(line: str, current_branch: str, kind: str) -> dict[str, Any] | None:
    parts = line.split("\x00", 4)
    if len(parts) != 5:
        return None
    name, upstream, last_commit_iso, last_commit_subject, worktree_path = parts
    if not name or name.endswith("/HEAD"):
        return None
    return {
        "name": name,
        "kind": kind,
        "current": kind == "local" and name == current_branch,
        "upstream": upstream or None,
        "last_commit_iso": last_commit_iso or None,
        "last_commit_subject": last_commit_subject or None,
        "worktree_path": worktree_path or None,
    }


def _remote_tracking_branch_name(remote_ref: str) -> str:
    if "/" not in remote_ref:
        return remote_ref
    return remote_ref.split("/", 1)[1]


def _local_branch_exists(cwd: Path, branch_name: str) -> bool:
    result = _run_git_command(cwd, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
    return result.returncode == 0


def _branch_worktree_path(cwd: Path, branch_name: str) -> str | None:
    result = _run_git_command(cwd, ["for-each-ref", "--format=%(worktreepath)", f"refs/heads/{branch_name}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _safe_worktree_slug(value: str | None) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip(".-")
    if not slug or not slug[0].isalnum():
        slug = "message"
    return slug[:48].lower()


def _worktree_base_path(repo_root: Path, slug: str) -> Path:
    digest = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:12]
    return Path(gettempdir()) / "personagent-worktrees" / digest / slug


def _unique_worktree_path(repo_root: Path, slug: str) -> Path:
    base = _worktree_base_path(repo_root, slug)
    if not base.exists():
        return base
    for index in range(2, 100):
        candidate = base.with_name(f"{base.name}-{index}")
        if not candidate.exists():
            return candidate
    return base.with_name(f"{base.name}-{int(time.time())}")


def _unique_branch_name(cwd: Path, requested: str) -> str:
    if not _local_branch_exists(cwd, requested):
        return requested
    base = requested[:56].rstrip("/-") or "personagent/branch"
    for index in range(2, 100):
        candidate = f"{base}-{index}"
        if not _local_branch_exists(cwd, candidate):
            return candidate
    return f"{base}-{int(time.time())}"


def _status_records(cwd: Path) -> list[tuple[str, str]]:
    result = _run_git_command(cwd, ["status", "--porcelain=v1"])
    if result.returncode != 0:
        return []

    records: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if path:
            records.append((status, path))
    return records


def _status_verb(status: str) -> str:
    if status.startswith("??") or "A" in status:
        return "Add"
    if "D" in status:
        return "Remove"
    if "R" in status:
        return "Rename"
    return "Update"


def _generate_commit_message(cwd: Path) -> str:
    records = _status_records(cwd)
    if not records:
        return "Update workspace"
    if len(records) == 1:
        status, path = records[0]
        return f"{_status_verb(status)} {path}"

    added = sum(1 for status, _ in records if status.startswith("??") or "A" in status)
    removed = sum(1 for status, _ in records if "D" in status)
    renamed = sum(1 for status, _ in records if "R" in status)
    updated = max(len(records) - added - removed - renamed, 0)
    parts: list[str] = []
    if added:
        parts.append(f"add {added} file{'s' if added != 1 else ''}")
    if updated:
        parts.append(f"update {updated} file{'s' if updated != 1 else ''}")
    if removed:
        parts.append(f"remove {removed} file{'s' if removed != 1 else ''}")
    if renamed:
        parts.append(f"rename {renamed} file{'s' if renamed != 1 else ''}")

    scopes = []
    for _, path in records:
        scope = path.split("/", 1)[0]
        if scope and scope not in scopes:
            scopes.append(scope)
    scope_suffix = ""
    if scopes:
        visible_scopes = ", ".join(scopes[:2])
        if len(scopes) > 2:
            visible_scopes = f"{visible_scopes}, +{len(scopes) - 2}"
        scope_suffix = f" in {visible_scopes}"

    summary = ", ".join(parts) or f"update {len(records)} files"
    return f"{summary[:1].upper()}{summary[1:]}{scope_suffix}"


class GitCommitRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    message: str | None = None
    auto_generate_message: bool = False
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


class GitBranchCreateRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str


class GitWorktreeCreateRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str | None = None
    branch: str | None = None
    source_message_id: str | None = None


class GitCheckoutRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str
    kind: str = "local"


class GitPushRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


def register_git_operation_routes(router: APIRouter) -> None:  # noqa: C901
    """Register local git operation endpoints on the given router."""

    @router.get("/git-status")
    async def get_git_status(
        workspace_root: str | None = Query(None, description="Workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, Any]:
        """Return current git status for the workspace."""
        if workspace_root or workspace_id:
            resolved = _resolve_workspace(workspace_root, workspace_id)
        else:
            try:
                resolved = _resolve_within_allowed_roots(".", None, None)
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

    @router.get("/git-commit-message")
    async def generate_git_commit_message(
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, str]:
        """Generate a concise commit message from current workspace changes."""
        cwd = _resolve_workspace(workspace_root, workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")
        return {"message": _generate_commit_message(cwd)}

    @router.get("/git-branches")
    async def get_git_branches(
        workspace_root: str | None = Query(None, description="Workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, Any]:
        """Return local and remote branches for the workspace."""
        if not workspace_root and not workspace_id:
            return {"is_repo": False, "current": "", "branches": []}

        cwd = _resolve_workspace(workspace_root, workspace_id)
        if not _is_git_repo(cwd):
            return {"is_repo": False, "current": "", "branches": []}

        current_result = _run_git_command(cwd, ["branch", "--show-current"])
        current_branch = current_result.stdout.strip() if current_result.returncode == 0 else ""
        current_worktree = str(cwd.resolve())
        format_spec = "%(refname:short)%00%(upstream:short)%00%(committerdate:iso8601-strict)%00%(contents:subject)%00%(worktreepath)"
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
                    worktree_path = item["worktree_path"]
                    item["checked_out_elsewhere"] = bool(
                        worktree_path and Path(str(worktree_path)).resolve() != Path(current_worktree).resolve()
                    )
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
                    if "/" not in remote_name:
                        continue
                    if remote_name in local_upstreams:
                        continue
                    if _remote_tracking_branch_name(remote_name) in local_branch_names:
                        continue
                    item["checked_out_elsewhere"] = False
                    item["worktree_path"] = None
                    branches.append(item)

        return {"is_repo": True, "current": current_branch, "branches": branches}

    @router.post("/git-branches")
    async def git_create_branch(payload: GitBranchCreateRequest) -> dict[str, Any]:
        """Create and switch to a new branch from the current HEAD."""
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
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

        _publish_git_change(cwd, "git-status", "git-branches")
        return {"success": True, "branch": branch_name, "output": switch_result.stdout.strip()}

    @router.post("/git-worktrees")
    async def git_create_worktree(payload: GitWorktreeCreateRequest) -> dict[str, Any]:
        """Create an isolated worktree and branch from the workspace HEAD."""
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")

        repo_root = _git_repo_root(cwd) or cwd
        source = payload.name or payload.source_message_id or "message"
        slug = _safe_worktree_slug(source)
        requested_branch = (payload.branch or f"personagent/{slug}").strip()
        if not requested_branch or requested_branch.startswith("-"):
            raise HTTPException(status_code=400, detail="Invalid branch name")

        branch_name = _unique_branch_name(cwd, requested_branch)
        check_result = _run_git_command(cwd, ["check-ref-format", "--branch", branch_name])
        if check_result.returncode != 0:
            raise HTTPException(status_code=400, detail=_git_error("Invalid branch name", check_result))

        worktree_path = _unique_worktree_path(repo_root, slug)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        add_result = _run_git_command(
            cwd,
            ["worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
            timeout=60,
        )
        if add_result.returncode != 0:
            raise HTTPException(status_code=409, detail=_git_error("git worktree add failed", add_result))

        _publish_git_change(cwd, "git-status", "git-branches")
        return {
            "success": True,
            "branch": branch_name,
            "path": str(worktree_path),
            "output": _git_output(add_result),
        }

    @router.post("/git-checkout")
    async def git_checkout_branch(payload: GitCheckoutRequest) -> dict[str, Any]:
        """Switch to an existing local branch or create a tracking branch from a remote."""
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")

        branch_name = payload.name.strip()
        if not branch_name or branch_name.startswith("-"):
            raise HTTPException(status_code=400, detail="Invalid branch name")

        if payload.kind == "local":
            worktree_path = _branch_worktree_path(cwd, branch_name)
            if worktree_path and Path(worktree_path).resolve() != cwd.resolve():
                raise HTTPException(
                    status_code=409,
                    detail=f"Branch '{branch_name}' is already checked out in another worktree: {worktree_path}",
                )
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
        _publish_git_change(cwd, "git-status", "git-branches")
        return {"success": True, "branch": current_branch, "output": switch_result.stdout.strip()}

    @router.post("/git-commit")
    async def git_commit(payload: GitCommitRequest) -> dict[str, Any]:
        """Stage all changes and create a git commit."""
        approval_arguments = _approval_arguments(
            payload,
            "workspace_root",
            "workspace_id",
            "message",
            "auto_generate_message",
        )
        require_action_approval(
            action_kind="workspace.git_commit",
            approval_id=payload.approval_id,
            args_hash=payload.args_hash,
            approval_signature=payload.approval_signature,
            expires_at=payload.expires_at,
            arguments=approval_arguments,
        )
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")

        message = (payload.message or "").strip()
        if payload.auto_generate_message and not message:
            message = _generate_commit_message(cwd)
        if not message:
            raise HTTPException(status_code=400, detail="Commit message is required")

        _cleanup_stale_git_index_lock(cwd)
        add_result = _run_git_command(cwd, ["add", "-A"], timeout=GIT_STAGE_TIMEOUT_SECONDS)
        if add_result.returncode != 0:
            raise HTTPException(status_code=500, detail=_git_error("git add failed", add_result))

        diff_result = _run_git_command(cwd, ["diff", "--cached", "--quiet"])
        if diff_result.returncode == 0:
            raise HTTPException(status_code=400, detail="No changes to commit")
        if diff_result.returncode not in (0, 1):
            raise HTTPException(status_code=500, detail=_git_error("git diff failed", diff_result))

        commit_result = _run_git_command(cwd, ["commit", "-m", message], timeout=45)
        if commit_result.returncode != 0:
            raise HTTPException(status_code=500, detail=_git_error("git commit failed", commit_result))

        sha_result = _run_git_command(cwd, ["rev-parse", "HEAD"])
        short_result = _run_git_command(cwd, ["rev-parse", "--short", "HEAD"])
        _publish_git_change(cwd, "git-status", "git-branches", "git-recent-actions")
        return {
            "success": True,
            "message": message,
            "sha": sha_result.stdout.strip() if sha_result.returncode == 0 else None,
            "short_sha": short_result.stdout.strip() if short_result.returncode == 0 else None,
            "output": _git_output(commit_result),
        }

    @router.post("/git-push")
    async def git_push(payload: GitPushRequest) -> dict[str, Any]:
        """Push current branch to remote."""
        approval_arguments = _approval_arguments(payload, "workspace_root", "workspace_id")
        require_action_approval(
            action_kind="workspace.git_push",
            approval_id=payload.approval_id,
            args_hash=payload.args_hash,
            approval_signature=payload.approval_signature,
            expires_at=payload.expires_at,
            arguments=approval_arguments,
        )
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")

        branch_result = _run_git_command(cwd, ["branch", "--show-current"])
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
        if not branch:
            raise HTTPException(status_code=400, detail="Cannot push while HEAD is detached")

        upstream_result = _run_git_command(cwd, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        push_args = ["push"]
        if upstream_result.returncode != 0:
            remote_result = _run_git_command(cwd, ["remote", "get-url", "origin"])
            if remote_result.returncode != 0:
                raise HTTPException(status_code=400, detail=_git_error("No upstream branch or origin remote", remote_result))
            push_args = ["push", "-u", "origin", branch]

        push_result = _run_git_command(cwd, push_args, timeout=60)
        if push_result.returncode != 0:
            raise HTTPException(status_code=500, detail=_git_error("git push failed", push_result))

        _publish_git_change(cwd, "git-status", "git-branches", "git-recent-actions", "git-pull-requests")
        return {
            "success": True,
            "branch": branch,
            "upstream": upstream_result.stdout.strip() if upstream_result.returncode == 0 else f"origin/{branch}",
            "output": _git_output(push_result),
        }
