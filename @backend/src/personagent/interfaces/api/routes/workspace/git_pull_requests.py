"""GitHub pull-request and recent-actions endpoints for workspace routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from personagent.interfaces.api.action_approvals import require_action_approval
from personagent.interfaces.api.routes.workspace.helpers import (
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


def _split_record(line: str, expected: int) -> tuple[str, ...]:
    parts = line.split("\x1f")
    return tuple((parts + [""] * expected)[:expected])


def _owner_repo_from_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    value = remote_url.strip().removesuffix(".git")
    if value.startswith("git@github.com:"):
        value = value.split(":", 1)[1]
    elif "github.com/" in value:
        value = value.split("github.com/", 1)[1]
    else:
        return None
    parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _recent_commits(cwd: Path) -> list[dict[str, Any]]:
    format_spec = "%H%x1f%h%x1f%an%x1f%aI%x1f%s"
    result = _run_git_command(cwd, ["log", "-n", "5", f"--format={format_spec}"])
    if result.returncode != 0:
        return []
    actions: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        sha, short, author, date, subject = _split_record(line, 5)
        if not sha:
            continue
        actions.append(
            {
                "id": f"commit:{sha}",
                "type": "commit",
                "title": subject or short,
                "subtitle": f"{short} · {author}" if author else short,
                "timestamp": date or None,
                "url": None,
            }
        )
    return actions


def _recent_prs(cwd: Path, errors: list[str]) -> list[dict[str, Any]]:
    result = _run_command(
        cwd,
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "5",
            "--json",
            "number,title,url,updatedAt,state,headRefName",
        ],
        timeout=8,
    )
    if result.returncode != 0:
        if result.returncode != 127:
            errors.append(_git_error("GitHub pull requests unavailable", result))
        return []
    actions: list[dict[str, Any]] = []
    for item in _json_list(result.stdout):
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        title = str(item.get("title") or f"Pull request #{number}")
        state = str(item.get("state") or "PR")
        branch = str(item.get("headRefName") or "")
        subtitle = f"#{number} · {state.lower()}" if number is not None else state.lower()
        if branch:
            subtitle = f"{subtitle} · {branch}"
        actions.append(
            {
                "id": f"pr:{number or title}",
                "type": "pr",
                "title": title,
                "subtitle": subtitle,
                "timestamp": item.get("updatedAt"),
                "url": item.get("url"),
            }
        )
    return actions


def _recent_pushes(cwd: Path, repo_name: str | None, errors: list[str]) -> list[dict[str, Any]]:
    if not repo_name:
        return []
    result = _run_command(cwd, ["gh", "api", f"repos/{repo_name}/events"], timeout=8)
    if result.returncode != 0:
        if result.returncode != 127:
            errors.append(_git_error("GitHub pushes unavailable", result))
        return []

    actions: list[dict[str, Any]] = []
    for item in _json_list(result.stdout):
        if not isinstance(item, dict) or item.get("type") != "PushEvent":
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
        ref = str(payload.get("ref") or "")
        branch = ref.removeprefix("refs/heads/")
        commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
        actions.append(
            {
                "id": f"push:{item.get('id')}",
                "type": "push",
                "title": f"Push to {branch or ref or 'repository'}",
                "subtitle": f"{len(commits)} commit{'s' if len(commits) != 1 else ''} · {actor.get('login', 'unknown')}",
                "timestamp": item.get("created_at"),
                "url": None,
            }
        )
        if len(actions) >= 5:
            break
    return actions


PR_JSON_FIELDS = ",".join(
    [
        "additions",
        "author",
        "baseRefName",
        "body",
        "comments",
        "deletions",
        "files",
        "headRefName",
        "isDraft",
        "labels",
        "latestReviews",
        "mergeStateStatus",
        "mergeable",
        "number",
        "reviewDecision",
        "state",
        "statusCheckRollup",
        "title",
        "updatedAt",
        "url",
    ]
)

PR_STATUS_LABELS = {
    "needs_review": "Needs review",
    "approved": "Approved",
    "merged": "Merged",
    "refused": "Refused",
}


def _author_login(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("login") or value.get("name") or "Unknown")
    return str(value or "Unknown")


def _author_is_bot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    login = str(value.get("login") or "").lower()
    return bool(value.get("is_bot")) or login.endswith("[bot]") or login.endswith("-bot") or login == "github-actions"


def _contains_ai_marker(body: str) -> bool:
    normalized = body.lower()
    return any(
        marker in normalized
        for marker in (
            "personagent ai analysis",
            "ai analysis",
            "ai review",
            "[ai]",
            "generated by ai",
        )
    )


def _pr_status(item: dict[str, Any]) -> str:
    state = str(item.get("state") or "").upper()
    review_decision = str(item.get("reviewDecision") or "").upper()
    merge_state = str(item.get("mergeStateStatus") or "").upper()
    mergeable = str(item.get("mergeable") or "").upper()
    if state == "MERGED":
        return "merged"
    if state == "CLOSED" or review_decision == "CHANGES_REQUESTED" or merge_state == "DIRTY" or mergeable == "CONFLICTING":
        return "refused"
    if review_decision == "APPROVED":
        return "approved"
    return "needs_review"


def _status_from_review_state(state: str) -> str | None:
    normalized = state.upper()
    if normalized == "APPROVED":
        return "approved"
    if normalized == "CHANGES_REQUESTED":
        return "refused"
    if normalized in {"COMMENTED", "REVIEW_REQUIRED", "PENDING"}:
        return "needs_review"
    return None


def _relative_time_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "recently"
    raw = value.replace("Z", "+00:00")
    try:
        updated = datetime.fromisoformat(raw)
    except ValueError:
        return value
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    seconds = max(0, int((datetime.now(UTC) - updated).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{months // 12}y ago"


def _first_body_paragraph(body: Any, title: str) -> str:
    if not isinstance(body, str) or not body.strip():
        return title
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("-", "*")):
            stripped = stripped.lstrip("-* ").strip()
        if stripped:
            lines.append(stripped)
        if len(" ".join(lines)) > 220:
            break
    summary = " ".join(lines).strip() or title
    return summary[:260]


def _check_summary(items: Any) -> tuple[str, bool]:
    if not isinstance(items, list) or not items:
        return "No checks", False
    failing = 0
    pending = 0
    passing = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        conclusion = str(item.get("conclusion") or "").upper()
        status = str(item.get("status") or item.get("state") or "").upper()
        if conclusion in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
            failing += 1
        elif conclusion in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            passing += 1
        elif status and status not in {"COMPLETED", "SUCCESS"}:
            pending += 1
        else:
            pending += 1
    total = passing + failing + pending
    if total == 0:
        return "No checks", False
    if failing:
        return f"{failing} failing / {total} checks", True
    if pending:
        return f"{pending} pending / {total} checks", False
    return f"{passing} passing", False


def _risk_label(item: dict[str, Any], status: str, checks_failing: bool) -> str:
    additions = int(item.get("additions") or 0)
    deletions = int(item.get("deletions") or 0)
    files = item.get("files") if isinstance(item.get("files"), list) else []
    changed = additions + deletions
    if status == "refused" or checks_failing or changed >= 1000 or len(files) >= 20:
        return "High"
    if status == "needs_review" or changed >= 250 or len(files) >= 6:
        return "Medium"
    return "Low"


def _pr_file(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    path = str(item.get("path") or item.get("filename") or "")
    if not path:
        return None
    additions = int(item.get("additions") or 0)
    deletions = int(item.get("deletions") or 0)
    if additions and deletions:
        change_type = "modified"
    elif additions:
        change_type = "added"
    elif deletions:
        change_type = "deleted"
    else:
        change_type = "modified"
    return {
        "id": f"file-{index}-{path.replace('/', '-')}",
        "path": path,
        "changeType": change_type,
        "additions": additions,
        "deletions": deletions,
        "summary": f"{change_type.title()} file from GitHub PR metadata.",
        "lines": [],
    }


def _pr_comment(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    body = str(item.get("body") or "").strip()
    if not body:
        return None
    author = item.get("author")
    source = "ai" if _author_is_bot(author) or _contains_ai_marker(body) else "human"
    return {
        "id": str(item.get("id") or item.get("url") or f"comment-{index}"),
        "kind": "ai_review" if source == "ai" else "human_review",
        "source": source,
        "author": _author_login(author),
        "body": body,
        "createdAt": item.get("createdAt") or item.get("updatedAt"),
        "url": item.get("url"),
        "status": None,
    }


def _pr_review_comment(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    state = str(item.get("state") or "")
    status = _status_from_review_state(state)
    body = str(item.get("body") or "").strip()
    if not status and not body:
        return None
    author = item.get("author")
    source = "ai" if _author_is_bot(author) or _contains_ai_marker(body) else "human"
    if not body:
        body = f"{PR_STATUS_LABELS.get(status or 'needs_review', 'Needs review')} review recorded."
    return {
        "id": str(item.get("id") or item.get("submittedAt") or f"review-{index}"),
        "kind": "status" if status else ("ai_review" if source == "ai" else "human_review"),
        "source": source,
        "author": _author_login(author),
        "body": body,
        "createdAt": item.get("submittedAt") or item.get("createdAt"),
        "url": item.get("url"),
        "status": status,
    }


def _normalize_pr(item: dict[str, Any], cwd: Path, viewer_login: str | None) -> dict[str, Any]:
    number = int(item.get("number") or 0)
    title = str(item.get("title") or f"Pull request #{number}")
    status = _pr_status(item)
    check_summary, checks_failing = _check_summary(item.get("statusCheckRollup"))
    comments = [
        comment
        for comment in (_pr_comment(raw, index) for index, raw in enumerate(item.get("comments") or []))
        if comment is not None
    ]
    comments.extend(
        comment
        for comment in (_pr_review_comment(raw, index) for index, raw in enumerate(item.get("latestReviews") or []))
        if comment is not None
    )
    files = [
        file
        for file in (_pr_file(raw, index) for index, raw in enumerate(item.get("files") or []))
        if file is not None
    ]
    labels = [
        str(label.get("name") or "")
        for label in item.get("labels") or []
        if isinstance(label, dict) and str(label.get("name") or "").strip()
    ]
    author = _author_login(item.get("author"))
    risk = _risk_label(item, status, checks_failing)
    return {
        "id": f"pr-{number}",
        "project": cwd.name,
        "projectPath": str(cwd),
        "number": number,
        "title": title,
        "author": author,
        "branch": str(item.get("headRefName") or ""),
        "baseBranch": str(item.get("baseRefName") or ""),
        "updated": _relative_time_label(item.get("updatedAt")),
        "updatedAt": item.get("updatedAt"),
        "url": item.get("url"),
        "status": status,
        "statusLabel": PR_STATUS_LABELS.get(status, "Needs review"),
        "risk": risk,
        "checkSummary": check_summary,
        "description": _first_body_paragraph(item.get("body"), title),
        "labels": labels,
        "commentsCount": len(comments),
        "comments": comments,
        "files": files,
        "isMine": bool(viewer_login and author.lower() == viewer_login.lower()),
        "isFlagged": status in {"needs_review", "refused"} or risk == "High",
        "reviewDecision": item.get("reviewDecision") or None,
        "mergeState": item.get("mergeStateStatus") or item.get("mergeable") or None,
    }


def _viewer_login(cwd: Path) -> str | None:
    result = _run_command(cwd, ["gh", "api", "user", "--jq", ".login"], timeout=8)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _format_pr_comment(kind: str, status: str | None, body: str) -> str:
    clean_body = body.strip()
    if kind == "ai_review":
        return f"PersonAgent AI analysis\n\n{clean_body}"
    if kind == "status":
        status_label = PR_STATUS_LABELS.get(status or "needs_review", "Needs review")
        return f"PersonAgent PR status: {status_label}\n\n{clean_body}".strip()
    return clean_body


class GitPullRequestCommentRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    body: str
    kind: str = "human_review"
    status: str | None = None


class GitPrRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


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
