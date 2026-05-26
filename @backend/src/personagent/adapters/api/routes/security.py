"""Security coordination routes for the local desktop client."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/security", tags=["security"])


class ActionApprovalRequest(BaseModel):
    action_kind: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/action-approvals")
async def create_approval(request: ActionApprovalRequest) -> dict[str, Any]:
    normalized_kind = request.action_kind.strip()
    if not normalized_kind:
        raise HTTPException(status_code=400, detail="action_kind is required.")
    raise HTTPException(
        status_code=403,
        detail="Action approvals must be created by the desktop confirmation boundary.",
    )
