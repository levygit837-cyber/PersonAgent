from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from personagent.interfaces.api import action_approvals


class _ApprovalSettings:
    personagent_action_approval_ttl_seconds = 300
    personagent_action_approval_secret = "test-approval-secret"
    personagent_action_approval_secret_path = ""


@pytest.fixture(autouse=True)
def _approval_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    action_approvals._CONSUMED_APPROVALS.clear()
    settings = _ApprovalSettings()
    settings.personagent_action_approval_secret_path = str(tmp_path / "approval_secret")
    monkeypatch.setattr(action_approvals, "get_settings", lambda: settings)
    yield
    action_approvals._CONSUMED_APPROVALS.clear()


def test_signed_action_approval_is_single_use() -> None:
    args = {"workspace_root": "/tmp/repo"}
    approval = action_approvals.create_action_approval("workspace.git_push", args)

    action_approvals.require_action_approval(
        action_kind="workspace.git_push",
        approval_id=approval["approval_id"],
        args_hash=approval["args_hash"],
        approval_signature=approval["approval_signature"],
        expires_at=approval["expires_at"],
        arguments=args,
    )

    with pytest.raises(HTTPException) as exc:
        action_approvals.require_action_approval(
            action_kind="workspace.git_push",
            approval_id=approval["approval_id"],
            args_hash=approval["args_hash"],
            approval_signature=approval["approval_signature"],
            expires_at=approval["expires_at"],
            arguments=args,
        )

    assert exc.value.status_code == 403
    assert "already used" in str(exc.value.detail)


def test_canonical_args_hash_matches_desktop_json_stringify() -> None:
    args = {"workspace_root": "/tmp/repo", "message": "ação"}

    assert (
        action_approvals.canonical_args_hash("workspace.git_commit", args)
        == "e6402f9cf683eca32773a76710d5cd58d2931fd4197fce773a89ca98707f56a2"
    )


def test_action_approval_rejects_tampered_arguments() -> None:
    args = {"workspace_root": "/tmp/repo"}
    approval = action_approvals.create_action_approval("workspace.git_push", args)

    with pytest.raises(HTTPException) as exc:
        action_approvals.require_action_approval(
            action_kind="workspace.git_push",
            approval_id=approval["approval_id"],
            args_hash=approval["args_hash"],
            approval_signature=approval["approval_signature"],
            expires_at=approval["expires_at"],
            arguments={"workspace_root": "/tmp/other"},
        )

    assert exc.value.status_code == 403
    assert "argument hash" in str(exc.value.detail)


def test_action_approval_rejects_invalid_signature() -> None:
    args = {"workspace_root": "/tmp/repo"}
    approval = action_approvals.create_action_approval("workspace.git_push", args)

    with pytest.raises(HTTPException) as exc:
        action_approvals.require_action_approval(
            action_kind="workspace.git_push",
            approval_id=approval["approval_id"],
            args_hash=approval["args_hash"],
            approval_signature="bad",
            expires_at=approval["expires_at"],
            arguments=args,
        )

    assert exc.value.status_code == 403
    assert "signature" in str(exc.value.detail)


def test_action_approval_rejects_expired_payload() -> None:
    args = {"workspace_root": "/tmp/repo"}
    approval = action_approvals.create_action_approval("workspace.git_push", args)

    with pytest.raises(HTTPException) as exc:
        action_approvals.require_action_approval(
            action_kind="workspace.git_push",
            approval_id=approval["approval_id"],
            args_hash=approval["args_hash"],
            approval_signature=approval["approval_signature"],
            expires_at=int(time.time()) - 1,
            arguments=args,
        )

    assert exc.value.status_code == 403
    assert "expired" in str(exc.value.detail)
