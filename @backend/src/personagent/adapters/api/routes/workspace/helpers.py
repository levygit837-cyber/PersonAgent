"""Shared helpers, constants, and Pydantic models for workspace routes."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from personagent.adapters.api.routes.state_events import publish_state_change
from personagent.adapters.api.routes.workspace_grants import (
    is_path_inside,
    resolve_workspace_root,
)
from personagent.infrastructure.settings.settings import get_settings

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


class WorkspaceGrantRequest(BaseModel):
    root: str
    source: str = "api"


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


def _resolve_within_allowed_roots(
    raw_path: str,
    workspace_root: str | None = None,
    workspace_id: str | None = None,
) -> Path:
    settings = get_settings()
    path = Path(raw_path).expanduser()
    resolved = path.resolve()

    if workspace_id or workspace_root:
        active_workspace = resolve_workspace_root(
            workspace_id=workspace_id,
            workspace_root=workspace_root,
            settings=settings,
        )
        if not is_path_inside(resolved, active_workspace):
            raise ValueError(f"Path '{raw_path}' is outside active workspace: {active_workspace}")
        return resolved

    allowed_roots = list(settings.tool_allowed_root_paths)
    if not any(is_path_inside(resolved, root) for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(f"Path '{raw_path}' is outside allowed roots: {roots}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    return is_path_inside(path, root)


def _resolve_workspace(
    workspace_root: str | None = None,
    workspace_id: str | None = None,
) -> Path:
    try:
        return resolve_workspace_root(
            workspace_id=workspace_id,
            workspace_root=workspace_root,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _approval_arguments(payload: BaseModel, *fields: str) -> dict[str, Any]:
    data = payload.model_dump()
    return {field: data.get(field) for field in fields if data.get(field) is not None}


def _git_error(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    return f"{message}: {detail}" if detail else message


def _git_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout.strip() or result.stderr.strip()


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
