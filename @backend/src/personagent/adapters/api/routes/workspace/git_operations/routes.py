"""Git operation endpoint handlers for workspace routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from personagent.adapters.api.routes.action_approvals import require_action_approval
from personagent.adapters.api.routes.workspace.git_operations.helpers import (
    _branch_worktree_path,
    _generate_commit_message,
    _git_branch_item,
    _local_branch_exists,
    _remote_tracking_branch_name,
    _safe_worktree_slug,
    _unique_branch_name,
    _unique_worktree_path,
)
from personagent.adapters.api.routes.workspace.git_operations.models import (
    GitBranchCreateRequest,
    GitCheckoutRequest,
    GitCommitRequest,
    GitPushRequest,
    GitWorktreeCreateRequest,
)
from personagent.adapters.api.routes.workspace.helpers import (
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
