"""Short-lived signed action approvals bound to normalized arguments."""

from __future__ import annotations

import hmac
import json
import secrets
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from personagent.infrastructure.config.settings import get_settings

APPROVABLE_ACTION_KINDS = frozenset(
    {
        "workspace.git_commit",
        "workspace.git_push",
        "workspace.git_pr",
        "memory.create",
        "memory.update",
        "memory.delete",
    }
)
_CONSUMED_APPROVALS: dict[str, float] = {}


def canonical_args_hash(action_kind: str, arguments: dict[str, Any]) -> str:
    payload = {
        "action_kind": action_kind,
        "arguments": arguments,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def create_action_approval(action_kind: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if action_kind not in APPROVABLE_ACTION_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported action approval kind: {action_kind}")
    ttl = max(30, int(get_settings().personagent_action_approval_ttl_seconds))
    approval_id = f"act_{secrets.token_urlsafe(24)}"
    args_hash = canonical_args_hash(action_kind, arguments)
    expires_at = int(time.time()) + ttl
    approval_signature = _sign_action_approval(
        approval_id=approval_id,
        action_kind=action_kind,
        args_hash=args_hash,
        expires_at=expires_at,
    )
    _cleanup_expired()
    return {
        "approval_id": approval_id,
        "action_kind": action_kind,
        "args_hash": args_hash,
        "expires_at": expires_at,
        "approval_signature": approval_signature,
    }


def require_action_approval(
    *,
    action_kind: str,
    approval_id: str | None,
    args_hash: str | None,
    approval_signature: str | None,
    expires_at: int | float | str | None,
    arguments: dict[str, Any],
) -> None:
    _cleanup_expired()
    if action_kind not in APPROVABLE_ACTION_KINDS:
        raise HTTPException(status_code=403, detail="Action approval kind is not supported.")
    expected_hash = canonical_args_hash(action_kind, arguments)
    if not approval_id or not args_hash or not approval_signature or expires_at is None:
        raise HTTPException(status_code=403, detail="Action approval is required.")
    try:
        expires_at_int = int(float(expires_at))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Action approval expiry is invalid.") from exc
    if args_hash != expected_hash:
        raise HTTPException(status_code=403, detail="Action approval argument hash mismatch.")
    if expires_at_int <= int(time.time()):
        raise HTTPException(status_code=403, detail="Action approval expired.")
    if approval_id in _CONSUMED_APPROVALS:
        raise HTTPException(status_code=403, detail="Action approval was already used.")
    expected_signature = _sign_action_approval(
        approval_id=approval_id,
        action_kind=action_kind,
        args_hash=args_hash,
        expires_at=expires_at_int,
    )
    if not hmac.compare_digest(approval_signature, expected_signature):
        raise HTTPException(status_code=403, detail="Action approval signature mismatch.")
    _CONSUMED_APPROVALS[approval_id] = float(expires_at_int)


def _sign_action_approval(
    *,
    approval_id: str,
    action_kind: str,
    args_hash: str,
    expires_at: int,
) -> str:
    payload = f"{approval_id}\n{action_kind}\n{args_hash}\n{expires_at}"
    return hmac.new(
        _action_approval_secret().encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()


def _action_approval_secret() -> str:
    settings = get_settings()
    configured = str(getattr(settings, "personagent_action_approval_secret", "") or "").strip()
    if configured:
        return configured
    path = Path(str(settings.personagent_action_approval_secret_path)).expanduser()
    return _read_or_create_secret(path)


def _read_or_create_secret(path: Path) -> str:
    try:
        secret = path.read_text(encoding="utf-8").strip()
        if secret:
            _chmod_private(path, file_mode=0o600)
            return secret
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private(path.parent, file_mode=0o700)
    secret = secrets.token_urlsafe(48)
    path.write_text(f"{secret}\n", encoding="utf-8")
    _chmod_private(path, file_mode=0o600)
    return secret


def _chmod_private(path: Path, *, file_mode: int) -> None:
    try:
        path.chmod(file_mode)
    except OSError:
        return


def _cleanup_expired() -> None:
    now = time.time()
    for approval_id, expires_at in list(_CONSUMED_APPROVALS.items()):
        if float(expires_at or 0) <= now:
            _CONSUMED_APPROVALS.pop(approval_id, None)
