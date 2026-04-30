"""Short-lived action approvals bound to normalized arguments."""

from __future__ import annotations

import json
import secrets
import time
from hashlib import sha256
from typing import Any

from fastapi import HTTPException

from personagent.infrastructure.config.settings import get_settings

_APPROVALS: dict[str, dict[str, Any]] = {}


def canonical_args_hash(action_kind: str, arguments: dict[str, Any]) -> str:
    payload = {
        "action_kind": action_kind,
        "arguments": arguments,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def create_action_approval(action_kind: str, arguments: dict[str, Any]) -> dict[str, Any]:
    ttl = max(30, int(get_settings().personagent_action_approval_ttl_seconds))
    approval_id = f"act_{secrets.token_urlsafe(24)}"
    args_hash = canonical_args_hash(action_kind, arguments)
    expires_at = time.time() + ttl
    _APPROVALS[approval_id] = {
        "approval_id": approval_id,
        "action_kind": action_kind,
        "args_hash": args_hash,
        "expires_at": expires_at,
    }
    _cleanup_expired()
    return {
        "approval_id": approval_id,
        "action_kind": action_kind,
        "args_hash": args_hash,
        "expires_at": expires_at,
    }


def require_action_approval(
    *,
    action_kind: str,
    approval_id: str | None,
    args_hash: str | None,
    arguments: dict[str, Any],
) -> None:
    _cleanup_expired()
    expected_hash = canonical_args_hash(action_kind, arguments)
    if not approval_id or not args_hash:
        raise HTTPException(status_code=403, detail="Action approval is required.")
    approval = _APPROVALS.get(approval_id)
    if not approval:
        raise HTTPException(status_code=403, detail="Action approval is missing or expired.")
    if approval.get("action_kind") != action_kind:
        raise HTTPException(status_code=403, detail="Action approval kind mismatch.")
    if approval.get("args_hash") != args_hash or args_hash != expected_hash:
        raise HTTPException(status_code=403, detail="Action approval argument hash mismatch.")
    if float(approval.get("expires_at") or 0) <= time.time():
        _APPROVALS.pop(approval_id, None)
        raise HTTPException(status_code=403, detail="Action approval expired.")
    _APPROVALS.pop(approval_id, None)


def _cleanup_expired() -> None:
    now = time.time()
    for approval_id, approval in list(_APPROVALS.items()):
        if float(approval.get("expires_at") or 0) <= now:
            _APPROVALS.pop(approval_id, None)
