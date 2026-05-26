"""Utility helpers for QA service."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from personagent.application.qa.contracts import QARequestRunRequest
from personagent.application.qa.redaction import redact_mapping, redact_value
from personagent.application.qa.runtime_tracer import PythonRuntimeTracer
from personagent.domain.exceptions import InvalidRequestError


def _request_payload(request: QARequestRunRequest) -> dict[str, Any]:
    return {
        "method": request.method.upper(),
        "path": request.path,
        "query": redact_mapping(request.query),
        "headers": redact_mapping(request.headers),
        "json": redact_value(request.json_body),
        "body": redact_value(request.body),
        "trace_mode": (request.trace_mode.value if request.trace_mode else None),
    }


def _safe_response_text(text: str) -> str:
    return str(redact_value(text, max_string=8_000))


def _safe_env_profile(env_profile: dict[str, str] | str | None) -> dict[str, Any] | str | None:
    if isinstance(env_profile, dict):
        return dict(redact_mapping(env_profile))
    return env_profile


def _source_root(repo_root: Path) -> Path:
    for candidate in (
        repo_root / "@backend" / "src" / "personagent",
        repo_root / "src" / "personagent",
        repo_root / "personagent",
    ):
        if candidate.exists():
            return candidate
    return repo_root


def _git_output(cwd: Path, args: list[str]) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _create_worktree(repo_root: Path, branch_name: str, base_commit: str, session_id: str) -> str:
    sandbox_root = Path(tempfile.gettempdir()) / "personagent-qa-sessions" / session_id
    sandbox_root.mkdir(parents=True, exist_ok=True)
    worktree_path = sandbox_root / "worktree"
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_path), base_commit],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise InvalidRequestError(
            f"Could not create QA worktree: {result.stderr.strip() or result.stdout.strip()}",
            code="qa.worktree_failed",
            http_status=500,
        )
    return str(worktree_path)


_GLOBAL_TRACER = PythonRuntimeTracer()
