#!/usr/bin/env python3
"""Sync Kimi CLI access token into PersonAgent .env.

Reads the OAuth token from the Kimi CLI credential store, checks expiration,
forces a CLI refresh if expired, and updates KIMI_API_KEY in the project .env.
Can be run manually, via cron, or triggered by the backend on 401 errors.

Usage:
    python scripts/kimi_token_sync.py [--check-only]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
CREDENTIALS_PATH = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
KIMI_CLI_BIN = Path.home() / ".local" / "bin" / "kimi"
REFRESH_MARGIN_SECONDS = 300  # Refresh if token expires in < 5 min
CLI_REFRESH_CMD = [
    str(KIMI_CLI_BIN),
    "--print",
    "--quiet",
    "--prompt",
    "ping",
    "--max-steps-per-turn",
    "1",
]

logger = print


# ── Helpers ─────────────────────────────────────────────────────────────────

def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1]
    # Add padding if needed
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def _read_cli_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(f"Kimi CLI credentials not found: {CREDENTIALS_PATH}")
    with open(CREDENTIALS_PATH, "r") as f:
        return json.load(f)


def _get_token_info(creds: dict) -> tuple[str, float, bool]:
    """Return (access_token, expires_at_timestamp, is_expired)."""
    access_token = creds.get("access_token", "")
    if not access_token:
        raise ValueError("No access_token in credentials")

    # Prefer explicit expires_at, fallback to JWT exp claim
    expires_at = creds.get("expires_at", 0)
    if not expires_at:
        payload = _decode_jwt_payload(access_token)
        expires_at = payload.get("exp", 0)

    is_expired = time.time() > (expires_at - REFRESH_MARGIN_SECONDS)
    return access_token, float(expires_at), is_expired


def _force_cli_refresh() -> None:
    """Run a minimal CLI command to trigger OAuth token refresh."""
    logger("[kimi-sync] Token expired or about to expire. Forcing CLI refresh...")
    try:
        result = subprocess.run(
            CLI_REFRESH_CMD,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI refresh failed: {result.stderr[:500]}")
        logger("[kimi-sync] CLI refresh completed.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("CLI refresh timed out after 30s")


def _update_env_file(new_token: str) -> bool:
    """Update KIMI_API_KEY in the project .env file."""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env file not found: {ENV_PATH}")

    content = ENV_PATH.read_text(encoding="utf-8")

    # Replace existing KIMI_API_KEY line
    pattern = r"^(KIMI_API_KEY=).*"
    if re.search(pattern, content, re.MULTILINE):
        new_content = re.sub(pattern, f"KIMI_API_KEY={new_token}", content, flags=re.MULTILINE)
        ENV_PATH.write_text(new_content, encoding="utf-8")
        logger("[kimi-sync] Updated KIMI_API_KEY in .env")
        return True

    # If not found, append before the first comment block or at the end
    raise ValueError("KIMI_API_KEY not found in .env")


def sync_token(*, check_only: bool = False) -> dict:
    """Main sync routine. Returns token metadata."""
    creds = _read_cli_credentials()
    access_token, expires_at, is_expired = _get_token_info(creds)

    result = {
        "access_token_present": bool(access_token),
        "expires_at": expires_at,
        "expires_human": time.ctime(expires_at),
        "is_expired": is_expired,
        "refreshed": False,
        "env_updated": False,
    }

    if is_expired:
        result["is_expired"] = True
        if check_only:
            logger(f"[kimi-sync] Token expires at {result['expires_human']} — NEEDS REFRESH")
            return result

        _force_cli_refresh()

        # Re-read after refresh
        creds = _read_cli_credentials()
        access_token, expires_at, is_expired = _get_token_info(creds)
        result["refreshed"] = True
        result["expires_at"] = expires_at
        result["expires_human"] = time.ctime(expires_at)
        result["is_expired"] = is_expired

    if not is_expired:
        result["env_updated"] = _update_env_file(access_token)
        logger(
            f"[kimi-sync] Token valid until {result['expires_human']} "
            f"(updated .env: {result['env_updated']})"
        )
    else:
        raise RuntimeError("Token still expired after CLI refresh attempt")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Kimi CLI token to PersonAgent .env")
    parser.add_argument("--check-only", action="store_true", help="Only check, do not refresh")
    args = parser.parse_args()

    try:
        result = sync_token(check_only=args.check_only)
        if args.check_only:
            print(f"expires_at: {result['expires_human']}")
            print(f"needs_refresh: {result['is_expired']}")
            return 1 if result["is_expired"] else 0
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as exc:
        logger(f"[kimi-sync] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
