"""Kimi Code token management and authentication helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

TOKEN_SYNC_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    / "scripts"
    / "kimi_token_sync.py"
)


class KimiTokenManager:
    """Handles Kimi API token refresh and JWT expiration checks."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key.strip()

    async def try_auto_refresh(self) -> bool:
        """Run the external sync script to refresh the Kimi CLI token."""
        if not TOKEN_SYNC_SCRIPT.exists():
            logger.debug("kimi_token_sync.py not found, skipping auto-refresh")
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(TOKEN_SYNC_SCRIPT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
            if proc.returncode != 0:
                logger.warning("kimi_token_sync failed", stderr=stderr.decode()[:200])
                return False
            # Re-read token from credentials file
            creds_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
            if creds_path.exists():
                with open(creds_path) as f:
                    creds = json.load(f)
                new_token = creds.get("access_token", "").strip()
                if new_token and new_token != self.api_key:
                    self.api_key = new_token
                    logger.info("kimi_token_sync refreshed access token")
                    return True
            return False
        except Exception as exc:
            logger.warning("kimi_token_sync exception", exc=exc)
            return False

    def is_expired(self) -> bool:
        """Decode JWT exp claim without verification."""
        if not self.api_key:
            return True
        try:
            payload_b64 = self.api_key.split(".")[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp", 0)
            return time.time() > (exp - 300)  # Refresh if expires in < 5 min
        except Exception:
            return True
