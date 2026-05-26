"""Codex CLI authentication and token management."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendTimeoutError,
)


@dataclass(frozen=True, slots=True)
class CodexAuthSnapshot:
    authenticated: bool
    auth_mode: str | None = None
    access_token: str | None = None
    account_id: str | None = None
    email: str | None = None
    plan_type: str | None = None
    last_refresh: str | None = None
    auth_path: str | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "authenticated": self.authenticated,
            "auth_mode": self.auth_mode,
            "account_id": self.account_id,
            "email": self.email,
            "plan_type": self.plan_type,
            "last_refresh": self.last_refresh,
            "auth_path": self.auth_path,
            "error": self.error,
        }


class CodexAuthStore:
    """Reads Codex CLI auth state from CODEX_HOME without copying tokens."""

    def __init__(
        self,
        codex_home: str | Path | None = None,
        *,
        codex_cli_path: str = "codex",
    ) -> None:
        configured_home = str(codex_home or os.environ.get("CODEX_HOME") or "").strip()
        self.codex_home = (
            Path(configured_home).expanduser()
            if configured_home
            else Path.home() / ".codex"
        )
        self.codex_cli_path = codex_cli_path or "codex"

    @property
    def auth_path(self) -> Path:
        return self.codex_home / "auth.json"

    @property
    def models_cache_path(self) -> Path:
        return self.codex_home / "models_cache.json"

    def auth_signature(self) -> str:
        path = self.auth_path
        if not path.exists():
            return f"missing:{path}"
        try:
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            return f"error:{path}:{exc}"
        return f"present:{path}:{stat.st_mtime_ns}:{stat.st_size}:{digest}"

    def read_status(self) -> CodexAuthSnapshot:
        path = self.auth_path
        if not path.exists():
            return CodexAuthSnapshot(
                authenticated=False,
                auth_path=str(path),
                error="Codex CLI is not logged in. Run `codex login`.",
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return CodexAuthSnapshot(
                authenticated=False,
                auth_path=str(path),
                error=f"Could not read Codex auth.json: {exc}",
            )

        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        access_token = self._string_or_none(tokens.get("access_token"))
        id_token = self._string_or_none(tokens.get("id_token"))
        claims = self._decode_jwt_claims(id_token)
        account_id = (
            self._string_or_none(tokens.get("account_id"))
            or self._string_or_none(claims.get("https://api.openai.com/auth.chatgpt_account_id"))
            or self._string_or_none(claims.get("chatgpt_account_id"))
        )
        auth_mode = self._string_or_none(data.get("auth_mode"))
        error = None
        if not access_token:
            error = "Codex CLI auth.json does not contain a ChatGPT access token."

        return CodexAuthSnapshot(
            authenticated=bool(access_token),
            auth_mode=auth_mode,
            access_token=access_token,
            account_id=account_id,
            email=self._string_or_none(claims.get("email")),
            plan_type=(
                self._string_or_none(claims.get("chatgpt_plan_type"))
                or self._string_or_none(claims.get("https://api.openai.com/auth.plan_type"))
            ),
            last_refresh=self._string_or_none(data.get("last_refresh")),
            auth_path=str(path),
            error=error,
        )

    def auth_headers(self, *, accept_stream: bool = False, client_version: str | None = None) -> dict[str, str]:
        snapshot = self.read_status()
        if not snapshot.access_token:
            raise LLMBackendConnectionError(snapshot.error or "Codex CLI is not logged in.")

        headers = {
            "Authorization": f"Bearer {snapshot.access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if accept_stream else "application/json",
            "User-Agent": "codex-cli",
        }
        if snapshot.account_id:
            headers["ChatGPT-Account-ID"] = snapshot.account_id
        if client_version:
            headers["version"] = client_version
        return headers

    async def refresh_via_cli(self, *, timeout: float = 45.0) -> bool:
        result = await self._run_cli(["debug", "models"], timeout=timeout)
        return result.returncode == 0

    async def logout(self, *, timeout: float = 30.0) -> bool:
        result = await self._run_cli(["logout"], timeout=timeout)
        return result.returncode == 0

    async def _run_cli(self, args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        command = [self.codex_cli_path, *args]
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                env=env,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout,
            )

        try:
            return await asyncio.to_thread(run)
        except FileNotFoundError as exc:
            raise LLMBackendConnectionError(
                f"Codex CLI not found at `{self.codex_cli_path}`."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMBackendTimeoutError(f"Codex CLI timed out after {timeout}s.") from exc

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _decode_jwt_claims(token: str | None) -> dict[str, Any]:
        if not token or token.count(".") < 2:
            return {}
        try:
            payload = token.split(".", 2)[1]
            padding = "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(f"{payload}{padding}")
            data = json.loads(decoded.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
