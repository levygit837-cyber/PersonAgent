"""Helpers for fetching recent Git/GitHub actions (commits, PRs, pushes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.adapters.api.routes.workspace.helpers import (
    _git_error,
    _json_list,
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
