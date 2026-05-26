"""Shared helper functions for git operation endpoints."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from personagent.adapters.api.routes.workspace.helpers import (
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
