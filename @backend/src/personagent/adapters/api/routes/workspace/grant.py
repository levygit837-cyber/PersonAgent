"""Workspace grant endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from personagent.adapters.api.routes.workspace.helpers import WorkspaceGrantRequest
from personagent.adapters.api.routes.workspace_grants import register_workspace_grant


def register_grant_routes(router: APIRouter) -> None:
    """Register workspace grant endpoints on the given router."""

    @router.post("/grants")
    async def create_workspace_grant(payload: WorkspaceGrantRequest) -> dict[str, Any]:
        """Register a user-selected workspace root and return its stable grant id."""
        try:
            return register_workspace_grant(payload.root, source=payload.source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
