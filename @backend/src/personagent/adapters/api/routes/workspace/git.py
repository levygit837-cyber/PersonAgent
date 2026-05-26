"""Git endpoints and helpers for workspace routes.

Thin wrapper that wires the two focused sub-modules into a single
registration function that ``workspace/__init__.py`` can call.
"""

from __future__ import annotations

from fastapi import APIRouter

from personagent.adapters.api.routes.workspace.git_operations import (
    register_git_operation_routes,
)
from personagent.adapters.api.routes.workspace.git_pull_requests import (
    register_git_pr_routes,
)


def register_git_routes(router: APIRouter) -> None:
    """Register all git-related endpoints on the given router."""
    register_git_operation_routes(router)
    register_git_pr_routes(router)
