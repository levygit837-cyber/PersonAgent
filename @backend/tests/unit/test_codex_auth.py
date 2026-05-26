import base64
import json

import pytest

from personagent.domain.exceptions import LLMBackendConnectionError
from personagent.infrastructure.llm.codex.auth import CodexAuthSnapshot, CodexAuthStore


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    return f"header.{payload.rstrip('=')}.signature"


def test_auth_snapshot_public_dict_excludes_access_token():
    snapshot = CodexAuthSnapshot(
        authenticated=True,
        access_token="secret",
        email="user@example.com",
    )
    public = snapshot.public_dict()
    assert "access_token" not in public
    assert public["authenticated"] is True
    assert public["email"] == "user@example.com"


def test_auth_store_reads_chatgpt_tokens(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "last_refresh": "2026-04-27T12:00:00Z",
                "tokens": {
                    "access_token": "secret-access-token",
                    "account_id": "acct_123",
                    "id_token": _jwt(
                        {
                            "email": "user@example.com",
                            "chatgpt_plan_type": "plus",
                        }
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    store = CodexAuthStore(tmp_path)
    snapshot = store.read_status()

    assert snapshot.authenticated is True
    assert snapshot.access_token == "secret-access-token"
    assert snapshot.account_id == "acct_123"
    assert snapshot.email == "user@example.com"
    assert snapshot.plan_type == "plus"
    assert snapshot.auth_mode == "chatgpt"


def test_auth_store_missing_file_returns_not_authenticated(tmp_path):
    store = CodexAuthStore(tmp_path)
    snapshot = store.read_status()

    assert snapshot.authenticated is False
    assert "not logged in" in (snapshot.error or "").lower()
    assert snapshot.auth_path == str(tmp_path / "auth.json")


def test_auth_store_corrupted_json_returns_error(tmp_path):
    (tmp_path / "auth.json").write_text("not-json", encoding="utf-8")
    store = CodexAuthStore(tmp_path)
    snapshot = store.read_status()

    assert snapshot.authenticated is False
    assert "could not read" in (snapshot.error or "").lower()


def test_auth_store_missing_access_token_returns_error(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps({"tokens": {}}),
        encoding="utf-8",
    )
    store = CodexAuthStore(tmp_path)
    snapshot = store.read_status()

    assert snapshot.authenticated is False
    assert "does not contain a chatgpt access token" in (snapshot.error or "").lower()


def test_auth_store_reads_account_id_from_jwt_claims(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "token",
                    "id_token": _jwt(
                        {
                            "https://api.openai.com/auth.chatgpt_account_id": "jwt_acct",
                        }
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    store = CodexAuthStore(tmp_path)
    snapshot = store.read_status()

    assert snapshot.account_id == "jwt_acct"


def test_auth_store_auth_headers_raises_when_not_logged_in(tmp_path):
    store = CodexAuthStore(tmp_path)
    with pytest.raises(LLMBackendConnectionError):
        store.auth_headers()


def test_auth_store_auth_headers_with_stream_and_version(tmp_path):
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "token",
                    "account_id": "acct",
                },
            }
        ),
        encoding="utf-8",
    )

    store = CodexAuthStore(tmp_path)
    headers = store.auth_headers(accept_stream=True, client_version="0.124.0")

    assert headers["Authorization"] == "Bearer token"
    assert headers["Accept"] == "text/event-stream"
    assert headers["ChatGPT-Account-ID"] == "acct"
    assert headers["version"] == "0.124.0"


def test_auth_store_auth_signature_changes_with_content(tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"tokens": {"access_token": "a"}}), encoding="utf-8")

    store = CodexAuthStore(tmp_path)
    sig1 = store.auth_signature()

    auth_path.write_text(json.dumps({"tokens": {"access_token": "b"}}), encoding="utf-8")
    sig2 = store.auth_signature()

    assert sig1 != sig2
    assert sig1.startswith("present:")
    assert sig2.startswith("present:")


def test_auth_store_auth_signature_when_missing(tmp_path):
    store = CodexAuthStore(tmp_path)
    sig = store.auth_signature()
    assert sig.startswith("missing:")


def test_auth_store_decode_jwt_claims_malformed():
    assert CodexAuthStore._decode_jwt_claims(None) == {}
    assert CodexAuthStore._decode_jwt_claims("no-dot") == {}
    assert CodexAuthStore._decode_jwt_claims("one.two") == {}


def test_auth_store_string_or_none():
    assert CodexAuthStore._string_or_none(" hello ") == "hello"
    assert CodexAuthStore._string_or_none("") is None
    assert CodexAuthStore._string_or_none(None) is None
    assert CodexAuthStore._string_or_none(123) is None


@pytest.mark.asyncio
async def test_auth_store_refresh_via_cli_not_found_raises(tmp_path):
    store = CodexAuthStore(tmp_path, codex_cli_path="nonexistent_cli_12345")
    with pytest.raises(LLMBackendConnectionError):
        await store.refresh_via_cli(timeout=1.0)


@pytest.mark.asyncio
async def test_auth_store_logout_not_found_raises(tmp_path):
    store = CodexAuthStore(tmp_path, codex_cli_path="nonexistent_cli_12345")
    with pytest.raises(LLMBackendConnectionError):
        await store.logout(timeout=1.0)
