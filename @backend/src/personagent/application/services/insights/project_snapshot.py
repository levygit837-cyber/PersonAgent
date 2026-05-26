"""Project snapshot and Git/GitHub detail operations for the session panel."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from personagent.application.services.session import session_panel

_GITHUB_REMOTE_RE = re.compile(r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$")
_MAX_DETAIL_PATCH_CHARS = 80_000


async def project_snapshot_async(workspace: Path) -> dict[str, Any]:
    errors: list[str] = []
    # Run independent git/gh queries concurrently.
    repo_task = session_panel._run_async(
        ["gh", "repo", "view", "--json", "nameWithOwner,url,defaultBranchRef,pushedAt"],
        workspace,
        timeout=5,
    )
    prs_task = session_panel._run_async(
        [
            "gh",
            "pr",
            "list",
            "--limit",
            "5",
            "--state",
            "all",
            "--json",
            "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName",
        ],
        workspace,
        timeout=5,
    )
    # git branch uses ref-filter formatting, so %1f emits the unit-separator byte here.
    branch_task = session_panel._run_async(
        ["git", "branch", "--format=%(refname:short)%1f%(objectname:short)%1f%(committerdate:iso8601)%1f%(subject)"],
        workspace,
        timeout=5,
    )
    log_task = session_panel._run_async(
        ["git", "log", "-10", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%s"],
        workspace,
        timeout=5,
    )
    remote_task = session_panel._run_async(
        ["git", "remote", "get-url", "origin"],
        workspace,
        timeout=3,
    )
    current_branch_task = session_panel._run_async(
        ["git", "branch", "--show-current"],
        workspace,
        timeout=3,
    )

    repo_result, prs_result, branch_result, log_result, remote_result, current_branch_result = await asyncio.gather(
        repo_task,
        prs_task,
        branch_task,
        log_task,
        remote_task,
        current_branch_task,
    )

    repo = repo_info_from_results(repo_result, remote_result, current_branch_result, errors)
    return {
        "repo": repo,
        "prs": prs_from_result(prs_result, errors),
        "branches": branches_from_result(branch_result, current_branch_result, workspace, errors),
        "pushes": await last_pushes_async(workspace, repo, errors),
        "commits": commits_from_result(log_result, workspace, errors),
        "errors": errors,
    }


def repo_info_from_results(
    repo_result: Any,
    remote_result: Any,
    current_branch_result: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    if repo_result.ok:
        data = _json_object(repo_result.stdout)
        default_branch = data.get("defaultBranchRef")
        return {
            "name_with_owner": data.get("nameWithOwner"),
            "url": data.get("url"),
            "default_branch": default_branch.get("name") if isinstance(default_branch, dict) else None,
            "pushed_at": data.get("pushedAt"),
            "source": "gh",
        }
    errors.append(command_error("gh repo view", repo_result))
    if not remote_result.ok:
        return None
    name_with_owner = owner_repo_from_remote(remote_result.stdout.strip())
    return {
        "name_with_owner": name_with_owner,
        "url": f"https://github.com/{name_with_owner}" if name_with_owner else remote_result.stdout.strip(),
        "default_branch": current_branch_result.stdout.strip() if current_branch_result.ok else None,
        "pushed_at": None,
        "source": "git",
    }


def prs_from_result(result: Any, errors: list[str]) -> list[dict[str, Any]]:
    if not result.ok:
        errors.append(command_error("gh pr list", result))
        return []
    values = _json_list(result.stdout)
    return [
        {
            "id": str(item.get("number")),
            "type": "pr",
            "title": f"#{item.get('number')} {item.get('title')}",
            "subtitle": f"{item.get('state')} · {item.get('headRefName')} → {item.get('baseRefName')}",
            "url": item.get("url"),
            "timestamp": item.get("updatedAt") or item.get("createdAt"),
            "metadata": item,
        }
        for item in values
    ]


def branches_from_result(
    result: Any,
    current_branch_result: Any,
    workspace: Path,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not session_panel._is_git_repo(workspace):
        return []
    if not result.ok:
        errors.append(command_error("git branch", result))
        return []
    current = current_branch_result.stdout.strip() if current_branch_result.ok else ""
    branches = []
    for line in result.stdout.splitlines()[:20]:
        name, sha, date, subject = _split_record(line, 4)
        branches.append(
            {
                "id": name,
                "type": "branch",
                "title": name,
                "subtitle": f"{sha} · {subject}",
                "timestamp": date,
                "active": name == current,
                "metadata": {"sha": sha, "subject": subject},
            }
        )
    return branches


def commits_from_result(
    result: Any,
    workspace: Path,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not session_panel._is_git_repo(workspace):
        return []
    if not result.ok:
        errors.append(command_error("git log", result))
        return []
    commits = []
    for line in result.stdout.splitlines():
        sha, short, author, date, subject = _split_record(line, 5)
        commits.append(
            {
                "id": sha,
                "type": "commit",
                "title": subject,
                "subtitle": f"{short} · {author}",
                "timestamp": date,
                "metadata": {"sha": sha, "short_sha": short, "author": author},
            }
        )
    return commits


async def last_pushes_async(
    workspace: Path,
    repo: dict[str, Any] | None,
    errors: list[str],
) -> list[dict[str, Any]]:
    name_with_owner = (repo or {}).get("name_with_owner")
    if not name_with_owner:
        return []
    result = await session_panel._run_async(["gh", "api", f"repos/{name_with_owner}/events"], workspace, timeout=5)
    if not result.ok:
        errors.append(command_error("gh api events", result))
        return []
    events = [item for item in _json_list(result.stdout) if item.get("type") == "PushEvent"]
    pushes = []
    for item in events[:5]:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
        actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
        ref = str(payload.get("ref") or "")
        branch = ref.removeprefix("refs/heads/")
        pushes.append(
            {
                "id": str(item.get("id")),
                "type": "push",
                "title": f"Push to {branch or ref or 'repository'}",
                "subtitle": f"{len(commits)} commits · {actor.get('login', 'unknown')}",
                "timestamp": item.get("created_at"),
                "url": None,
                "metadata": {
                    "ref": ref,
                    "branch": branch,
                    "commits": commits,
                    "actor": actor,
                },
            }
        )
    return pushes


def commit_detail(workspace: Path, sha: str) -> dict[str, Any]:
    repo_name = owner_repo_from_workspace(workspace)
    if repo_name:
        remote = session_panel._run(["gh", "api", f"repos/{repo_name}/commits/{sha}"], workspace)
        if remote.ok:
            data = _json_object(remote.stdout)
            files = data.get("files") if isinstance(data.get("files"), list) else []
            commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
            message = str(commit.get("message") or "")
            return {
                "type": "commit",
                "id": sha,
                "title": message.splitlines()[0] if message.splitlines() else sha,
                "url": data.get("html_url"),
                "metadata": {
                    "sha": data.get("sha"),
                    "author": commit.get("author"),
                    "stats": data.get("stats"),
                    "message": message,
                },
                "files": [
                    {
                        "filename": item.get("filename"),
                        "status": item.get("status"),
                        "additions": item.get("additions"),
                        "deletions": item.get("deletions"),
                        "changes": item.get("changes"),
                        "patch": _truncate(
                            str(item.get("patch") or ""),
                            _MAX_DETAIL_PATCH_CHARS // max(1, len(files)),
                        ),
                    }
                    for item in files
                ],
                "source": "gh",
            }
    return local_commit_detail(workspace, sha)


def local_commit_detail(workspace: Path, sha: str) -> dict[str, Any]:
    show = session_panel._run(
        ["git", "show", "--stat", "--patch", "--format=fuller", sha],
        workspace,
        timeout=8,
    )
    meta = session_panel._run(
        ["git", "show", "-s", "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%B", sha],
        workspace,
    )
    full, short, author, date, message = _split_record(meta.stdout, 5) if meta.ok else (sha, sha[:7], "", "", "")
    return {
        "type": "commit",
        "id": sha,
        "title": message.splitlines()[0] if message else short,
        "metadata": {"sha": full, "short_sha": short, "author": author, "date": date, "message": message},
        "patch": _truncate(show.stdout if show.ok else show.stderr, _MAX_DETAIL_PATCH_CHARS),
        "source": "git",
        "error": None if show.ok else show.stderr,
    }


def push_detail(workspace: Path, event_id: str) -> dict[str, Any]:
    repo_name = owner_repo_from_workspace(workspace)
    if not repo_name:
        return {"type": "push", "id": event_id, "title": "Push", "error": "GitHub repository not detected."}
    events = session_panel._run(["gh", "api", f"repos/{repo_name}/events"], workspace)
    if not events.ok:
        return {"type": "push", "id": event_id, "title": "Push", "error": events.stderr or events.stdout}
    event = next((item for item in _json_list(events.stdout) if str(item.get("id")) == event_id), None)
    if not event:
        return {
            "type": "push",
            "id": event_id,
            "title": "Push",
            "error": "Push event not found in recent GitHub events.",
        }
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
    return {
        "type": "push",
        "id": event_id,
        "title": f"Push to {str(payload.get('ref') or '').removeprefix('refs/heads/')}",
        "metadata": {
            "created_at": event.get("created_at"),
            "actor": event.get("actor"),
            "ref": payload.get("ref"),
            "size": payload.get("size"),
        },
        "commits": commits,
        "source": "gh",
    }


def pr_detail(workspace: Path, pr_number: str) -> dict[str, Any]:
    result = session_panel._run(
        [
            "gh",
            "pr",
            "view",
            pr_number,
            "--json",
            "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName,body,commits,files,additions,deletions,changedFiles",
        ],
        workspace,
    )
    if not result.ok:
        return {"type": "pr", "id": pr_number, "title": f"PR #{pr_number}", "error": result.stderr or result.stdout}
    data = _json_object(result.stdout)
    return {
        "type": "pr",
        "id": str(data.get("number") or pr_number),
        "title": f"#{data.get('number')} {data.get('title')}",
        "url": data.get("url"),
        "metadata": data,
        "files": data.get("files") if isinstance(data.get("files"), list) else [],
        "source": "gh",
    }


def branch_detail(workspace: Path, branch: str) -> dict[str, Any]:
    log = session_panel._run(
        ["git", "log", "-1", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%B", branch],
        workspace,
    )
    stat = session_panel._run(["git", "log", "-1", "--stat", "--oneline", branch], workspace)
    full, short, author, date, message = _split_record(log.stdout, 5) if log.ok else ("", "", "", "", "")
    return {
        "type": "branch",
        "id": branch,
        "title": branch,
        "metadata": {
            "latest_commit": full,
            "short_sha": short,
            "author": author,
            "date": date,
            "message": message,
        },
        "patch": stat.stdout if stat.ok else stat.stderr,
        "source": "git",
        "error": None if log.ok else log.stderr,
    }


def owner_repo_from_workspace(workspace: Path) -> str | None:
    remote = session_panel._run(["git", "remote", "get-url", "origin"], workspace)
    if not remote.ok:
        return None
    return owner_repo_from_remote(remote.stdout.strip())


def owner_repo_from_remote(remote: str) -> str | None:
    match = _GITHUB_REMOTE_RE.search(remote)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


def git_default_branch(workspace: Path) -> str | None:
    result = session_panel._run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], workspace)
    if result.ok and "/" in result.stdout:
        return result.stdout.strip().split("/")[-1]
    result = session_panel._run(["git", "branch", "--show-current"], workspace)
    return result.stdout.strip() or None


def command_error(label: str, result: Any) -> str:
    detail = (result.stderr or result.stdout).strip()
    return f"{label}: {detail or f'exit {result.returncode}'}"


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _split_record(line: str, count: int) -> tuple[str, ...]:
    parts = line.split("\x1f", count - 1)
    return (*parts, *([""] * count))[:count]


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n[truncated]"
