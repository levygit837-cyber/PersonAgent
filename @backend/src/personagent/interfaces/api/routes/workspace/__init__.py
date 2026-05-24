"""Routes for workspace filesystem navigation."""

from __future__ import annotations

from fastapi import APIRouter

from personagent.interfaces.api.routes.workspace.filesystem import register_filesystem_routes
from personagent.interfaces.api.routes.workspace.git import register_git_routes
from personagent.interfaces.api.routes.workspace.grant import register_grant_routes
from personagent.interfaces.api.routes.workspace.helpers import (
    _is_git_repo,
    _resolve_workspace,
    _run_git_command,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])

register_grant_routes(router)
register_filesystem_routes(router)
register_git_routes(router)

__all__ = [
    "_is_git_repo",
    "_resolve_workspace",
    "_run_git_command",
    "router",
]
