"""Request models for Git pull request endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class GitPullRequestCommentRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    body: str
    kind: str = "human_review"
    status: str | None = None


class GitPrRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None
