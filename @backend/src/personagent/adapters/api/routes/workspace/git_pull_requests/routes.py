"""GitHub pull-request and recent-actions endpoints for workspace routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from personagent.adapters.api.routes.action_approvals import require_action_approval
from personagent.adapters.api.routes.workspace.git_pull_requests.formatting import (
    _format_pr_comment,
    _viewer_login,
)
from personagent.adapters.api.routes.workspace.git_pull_requests.models import (
    GitPrRequest,
    GitPullRequestCommentRequest,
)
from personagent.adapters.api.routes.workspace.git_pull_requests.pr_normalization import (
    PR_JSON_FIELDS,
    PR_STATUS_LABELS,
    _normalize_pr,
)
from personagent.adapters.api.routes.workspace.git_pull_requests.recent_actions import (
    _owner_repo_from_remote,
    _recent_commits,
    _recent_prs,
    _recent_pushes,
)
from personagent.adapters.api.routes.workspace.helpers import (
    _approval_arguments,
    _git_error,
    _git_output,
    _is_git_repo,
    _json_list,
    _publish_git_change,
    _resolve_workspace,
    _run_command,
    _run_git_command,
)


def register_git_pr_routes(router: APIRouter) -> None:
    """Register GitHub pull-request and recent-actions endpoints on the given router."""

    @router.get("/git-recent-actions")
    async def get_git_recent_actions(
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, Any]:
        """Return recent commits, pushes, and pull requests for the workspace repository."""
        cwd = _resolve_workspace(workspace_root, workspace_id)
        if not _is_git_repo(cwd):
            return {"is_repo": False, "actions": [], "errors": []}

        errors: list[str] = []
        remote_result = _run_git_command(cwd, ["remote", "get-url", "origin"])
        repo_name = _owner_repo_from_remote(remote_result.stdout.strip() if remote_result.returncode == 0 else None)
        actions = [
            *_recent_commits(cwd),
            *_recent_pushes(cwd, repo_name, errors),
            *_recent_prs(cwd, errors),
        ]
        actions.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return {"is_repo": True, "actions": actions[:12], "errors": errors}

    @router.get("/git-pull-requests")
    async def get_git_pull_requests(
        workspace_root: str | None = Query(None, description="Legacy workspace root path"),
        workspace_id: str | None = Query(None, description="Granted workspace id"),
    ) -> dict[str, Any]:
        """Return pull requests for the workspace repository using GitHub CLI metadata."""
        cwd = _resolve_workspace(workspace_root, workspace_id)
        if not _is_git_repo(cwd):
            return {"is_repo": False, "viewerLogin": None, "pullRequests": [], "errors": []}

        result = _run_command(
            cwd,
            ["gh", "pr", "list", "--state", "all", "--limit", "30", "--json", PR_JSON_FIELDS],
            timeout=15,
        )
        if result.returncode != 0:
            errors = [] if result.returncode == 127 else [_git_error("GitHub pull requests unavailable", result)]
            return {"is_repo": True, "viewerLogin": None, "pullRequests": [], "errors": errors}

        viewer_login = _viewer_login(cwd)
        pull_requests = [
            _normalize_pr(item, cwd, viewer_login)
            for item in _json_list(result.stdout)
            if isinstance(item, dict)
        ]
        pull_requests.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        return {"is_repo": True, "viewerLogin": viewer_login, "pullRequests": pull_requests, "errors": []}

    @router.post("/git-pull-requests/{number}/comments")
    async def create_git_pull_request_comment(number: int, payload: GitPullRequestCommentRequest) -> dict[str, Any]:
        """Create a standardized pull request comment through GitHub CLI."""
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)
        if not _is_git_repo(cwd):
            raise HTTPException(status_code=400, detail="No Git repository detected")

        body = payload.body.strip()
        if not body:
            raise HTTPException(status_code=400, detail="Comment body is required")
        if payload.kind not in {"human_review", "ai_review", "status"}:
            raise HTTPException(status_code=400, detail="Unsupported pull request comment type")
        if payload.status is not None and payload.status not in PR_STATUS_LABELS:
            raise HTTPException(status_code=400, detail="Unsupported pull request status")

        formatted_body = _format_pr_comment(payload.kind, payload.status, body)
        result = _run_command(cwd, ["gh", "pr", "comment", str(number), "--body", formatted_body], timeout=20)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=_git_error("GitHub pull request comment failed", result))

        output = _git_output(result)
        url = next((line.strip() for line in output.splitlines() if line.strip().startswith("http")), None)
        _publish_git_change(cwd, "git-recent-actions", "git-pull-requests")
        return {"success": True, "output": output, "url": url}

    @router.post("/git-pr")
    async def git_open_pr(payload: GitPrRequest) -> dict[str, Any]:
        """Try to open a PR using gh CLI, or return the remote URL."""
        approval_arguments = _approval_arguments(payload, "workspace_root", "workspace_id")
        require_action_approval(
            action_kind="workspace.git_pr",
            approval_id=payload.approval_id,
            args_hash=payload.args_hash,
            approval_signature=payload.approval_signature,
            expires_at=payload.expires_at,
            arguments=approval_arguments,
        )
        cwd = _resolve_workspace(payload.workspace_root, payload.workspace_id)

        # Try gh pr create
        pr_result = _run_git_command(cwd, ["gh", "pr", "create", "--fill"], timeout=30)
        if pr_result.returncode == 0:
            # Extract URL from output
            url = pr_result.stdout.strip().splitlines()[-1]
            _publish_git_change(cwd, "git-recent-actions", "git-pull-requests")
            return {"success": True, "url": url, "output": pr_result.stdout.strip()}

        # Fallback: return remote URL
        remote_result = _run_git_command(cwd, ["remote", "get-url", "origin"])
        remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None
        if remote_url and remote_url.endswith(".git"):
            remote_url = remote_url[:-4]
        if remote_url:
            remote_url = remote_url.replace(":", "/").replace("git@", "https://")

        _publish_git_change(cwd, "git-recent-actions", "git-pull-requests")
        return {"success": False, "url": remote_url, "output": pr_result.stderr.strip()}
