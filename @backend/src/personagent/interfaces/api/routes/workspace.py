"""Routes for workspace filesystem navigation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from personagent.infrastructure.config.settings import get_settings
from personagent.interfaces.api.state_events import publish_state_change

router = APIRouter(prefix="/workspace", tags=["workspace"])
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_MENTION_SCAN_PATHS = 12_000
STALE_GIT_INDEX_LOCK_SECONDS = 10 * 60
GIT_STAGE_TIMEOUT_SECONDS = 120
MENTION_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "release",
}


class WorkspaceMentionSuggestion(BaseModel):
    type: str
    name: str
    path: str
    display_path: str
    is_directory: bool
    score: float


def _command_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _run_command(cwd: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]} not found")
    except subprocess.TimeoutExpired as exc:
        stderr = _command_text(exc.stderr) or f"{args[0]} command timed out after {timeout}s"
        return subprocess.CompletedProcess(args, 124, _command_text(exc.stdout), stderr)


def _run_git_command(cwd: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return _run_command(
        cwd,
        ["git", *args],
        timeout=timeout,
    )


def _publish_git_change(cwd: Path, *resources: str) -> None:
    scope = {"workspace_root": str(cwd.resolve())}
    for resource in resources:
        publish_state_change(resource, scope)


def _is_git_repo(cwd: Path) -> bool:
    result = _run_git_command(cwd, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _looks_like_git_repo(path: Path) -> bool:
    return path.is_dir() and (path / ".git").exists()


def _git_repo_root(cwd: Path) -> Path | None:
    result = _run_git_command(cwd, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    return Path(raw).expanduser().resolve() if raw else None


def _git_path(cwd: Path, name: str) -> Path | None:
    result = _run_git_command(cwd, ["rev-parse", "--git-path", name])
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _path_has_open_handle(path: Path) -> bool:
    for args in (["fuser", "-s", str(path)], ["lsof", str(path)]):
        result = _run_command(path.parent, args, timeout=3)
        if result.returncode == 0:
            return True
        if result.returncode == 127:
            continue
    return False


def _cleanup_stale_git_index_lock(cwd: Path, stale_after_seconds: int = STALE_GIT_INDEX_LOCK_SECONDS) -> str | None:
    lock_path = _git_path(cwd, "index.lock")
    if lock_path is None or not lock_path.exists():
        return None

    try:
        stat = lock_path.stat()
    except OSError:
        return None

    age_seconds = time.time() - stat.st_mtime
    if age_seconds < stale_after_seconds:
        return None
    if _path_has_open_handle(lock_path):
        return None

    try:
        lock_path.unlink()
    except OSError:
        return None
    return str(lock_path)


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


def _git_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout.strip() or result.stderr.strip()


def _split_record(line: str, expected: int) -> tuple[str, ...]:
    parts = line.split("\x1f")
    return tuple((parts + [""] * expected)[:expected])


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


def _json_list(raw: str) -> list[Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


@router.get("/mentions", response_model=list[WorkspaceMentionSuggestion])
async def list_workspace_mentions(
    q: str = Query(default="", description="Partial @ mention query"),
    workspace_root: str = Query(..., description="Workspace root path"),
    limit: int = Query(default=40, ge=1, le=100),
) -> list[WorkspaceMentionSuggestion]:
    """Return file and directory suggestions for composer @ mentions."""
    root = _resolve_workspace(workspace_root)
    return _workspace_mention_suggestions(root, q, limit)


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
    message: str | None = None
    auto_generate_message: bool = False


class GitBranchCreateRequest(BaseModel):
    workspace_root: str
    name: str


class GitWorktreeCreateRequest(BaseModel):
    workspace_root: str
    name: str | None = None
    branch: str | None = None
    source_message_id: str | None = None


class GitCheckoutRequest(BaseModel):
    workspace_root: str
    name: str
    kind: str = "local"


class GitPullRequestCommentRequest(BaseModel):
    workspace_root: str
    body: str
    kind: str = "human_review"
    status: str | None = None


@router.get("/git-commit-message")
async def generate_git_commit_message(
    workspace_root: str = Query(..., description="Workspace root path"),
) -> dict[str, str]:
    """Generate a concise commit message from current workspace changes."""
    cwd = _resolve_workspace(workspace_root)
    if not _is_git_repo(cwd):
        raise HTTPException(status_code=400, detail="No Git repository detected")
    return {"message": _generate_commit_message(cwd)}


@router.get("/git-recent-actions")
async def get_git_recent_actions(
    workspace_root: str = Query(..., description="Workspace root path"),
) -> dict[str, Any]:
    """Return recent commits, pushes, and pull requests for the workspace repository."""
    cwd = _resolve_workspace(workspace_root)
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


@router.get("/projects")
async def get_workspace_projects() -> dict[str, Any]:
    """Return nearby Git workspaces for project selection."""
    projects = [{"name": path.name, "path": str(path), "is_repo": True} for path in _workspace_project_candidates()]
    return {"projects": projects}


@router.get("/git-pull-requests")
async def get_git_pull_requests(
    workspace_root: str = Query(..., description="Workspace root path"),
) -> dict[str, Any]:
    """Return pull requests for the workspace repository using GitHub CLI metadata."""
    cwd = _resolve_workspace(workspace_root)
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
    cwd = _resolve_workspace(payload.workspace_root)
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

    _publish_git_change(cwd, "git-status", "git-branches")
    return {"success": True, "branch": branch_name, "output": switch_result.stdout.strip()}


@router.post("/git-worktrees")
async def git_create_worktree(payload: GitWorktreeCreateRequest) -> dict[str, Any]:
    """Create an isolated worktree and branch from the workspace HEAD."""
    cwd = _resolve_workspace(payload.workspace_root)
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
    cwd = _resolve_workspace(payload.workspace_root)
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
    cwd = _resolve_workspace(payload.workspace_root)
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


class GitPushRequest(BaseModel):
    workspace_root: str


@router.post("/git-push")
async def git_push(payload: GitPushRequest) -> dict[str, Any]:
    """Push current branch to remote."""
    cwd = _resolve_workspace(payload.workspace_root)
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
