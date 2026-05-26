"""Tests for Kimi token management."""

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from personagent.infrastructure.llm.kimi.auth import KimiTokenManager


class TestKimiTokenManager:
    def test_is_expired_empty_key(self) -> None:
        manager = KimiTokenManager(api_key="")
        assert manager.is_expired() is True

    def test_is_expired_invalid_jwt(self) -> None:
        manager = KimiTokenManager(api_key="not-a-jwt")
        assert manager.is_expired() is True

    def test_is_expired_future_exp(self) -> None:
        future_exp = int(time.time()) + 3600
        payload = json.dumps({"exp": future_exp})
        payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        token = f"header.{payload_b64}.sig"
        manager = KimiTokenManager(api_key=token)
        assert manager.is_expired() is False

    def test_is_expired_past_exp(self) -> None:
        past_exp = int(time.time()) - 3600
        payload = json.dumps({"exp": past_exp})
        payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        token = f"header.{payload_b64}.sig"
        manager = KimiTokenManager(api_key=token)
        assert manager.is_expired() is True

    def test_is_expired_refresh_window(self) -> None:
        # Expires in 4 minutes — should be considered expired (5-min window)
        near_exp = int(time.time()) + 240
        payload = json.dumps({"exp": near_exp})
        payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        token = f"header.{payload_b64}.sig"
        manager = KimiTokenManager(api_key=token)
        assert manager.is_expired() is True

    @pytest.mark.asyncio
    async def test_try_auto_refresh_skips_when_script_missing(self) -> None:
        manager = KimiTokenManager(api_key="old")
        with patch(
            "personagent.infrastructure.llm.kimi.auth.TOKEN_SYNC_SCRIPT"
        ) as mock_path:
            mock_path.exists.return_value = False
            result = await manager.try_auto_refresh()
        assert result is False
        assert manager.api_key == "old"

    @pytest.mark.asyncio
    async def test_try_auto_refresh_updates_token(self) -> None:
        manager = KimiTokenManager(api_key="old-token")
        fake_creds = {"access_token": "new-token"}

        with (
            patch(
                "personagent.infrastructure.llm.kimi.auth.TOKEN_SYNC_SCRIPT"
            ) as mock_script,
            patch("asyncio.create_subprocess_exec") as mock_exec,
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", MagicMock()),
            patch("json.load", return_value=fake_creds),
        ):
            mock_script.exists.return_value = True
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_proc

            result = await manager.try_auto_refresh()

        assert result is True
        assert manager.api_key == "new-token"

    @pytest.mark.asyncio
    async def test_try_auto_refresh_no_change_when_same_token(self) -> None:
        manager = KimiTokenManager(api_key="same-token")
        fake_creds = {"access_token": "same-token"}

        with (
            patch(
                "personagent.infrastructure.llm.kimi.auth.TOKEN_SYNC_SCRIPT"
            ) as mock_script,
            patch("asyncio.create_subprocess_exec") as mock_exec,
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", MagicMock()),
            patch("json.load", return_value=fake_creds),
        ):
            mock_script.exists.return_value = True
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_proc

            result = await manager.try_auto_refresh()

        assert result is False
