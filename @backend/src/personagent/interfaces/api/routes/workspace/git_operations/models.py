"""Pydantic request models for git operation endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class GitCommitRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    message: str | None = None
    auto_generate_message: bool = False
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None


class GitBranchCreateRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str


class GitWorktreeCreateRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str | None = None
    branch: str | None = None
    source_message_id: str | None = None


class GitCheckoutRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    name: str
    kind: str = "local"


class GitPushRequest(BaseModel):
    workspace_root: str | None = None
    workspace_id: str | None = None
    approval_id: str | None = None
    args_hash: str | None = None
    approval_signature: str | None = None
    expires_at: int | None = None
