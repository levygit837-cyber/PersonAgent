"""Formatting helpers for PR comments and viewer info."""

from __future__ import annotations

from pathlib import Path

from personagent.adapters.api.routes.workspace.git_pull_requests.pr_normalization import (
    PR_STATUS_LABELS,
)
from personagent.adapters.api.routes.workspace.helpers import _run_command


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
