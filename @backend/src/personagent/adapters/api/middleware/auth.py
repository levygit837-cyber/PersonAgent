"""Local API security helpers for the desktop/backend boundary."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

_PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}

CLIENT_HEADER = "X-PersonAgent-Client"
CLIENT_HEADER_VALUES = {"desktop-electron", "tui"}
_WEAK_POSTGRES_PASSWORDS = {"", "personagent", "personagent_secret", "postgres", "password"}
logger = structlog.get_logger(__name__)


def validate_startup_security(settings: Any) -> None:
    """Reject unsafe production-like startup defaults."""

    env = str(settings.app_env or "").strip().lower()
    if env != "development" and str(settings.secret_key or "") == "change-me":
        raise RuntimeError("SECRET_KEY must be set outside development.")
    postgres_password = str(getattr(settings, "postgres_password", "") or "")
    if postgres_password in _WEAK_POSTGRES_PASSWORDS:
        message = "POSTGRES_PASSWORD must be set to a unique local password."
        if env != "development":
            raise RuntimeError(message)
        logger.warning("weak_postgres_password_configured", detail=message)


def install_local_auth(app: FastAPI, settings: Any) -> None:
    """Install token auth for all non-public local API routes."""

    if not bool(getattr(settings, "personagent_local_auth_enabled", True)):
        return

    token_path = Path(str(settings.personagent_local_auth_token_path)).expanduser()
    configured_token = _configured_local_auth_token(settings)
    if configured_token:
        persist_local_token(token_path, configured_token)
    else:
        read_or_create_local_token(token_path)

    @app.middleware("http")
    async def require_local_auth(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if request.method == "OPTIONS" or path in _PUBLIC_PATHS:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin and origin not in cors_allowed_origins(settings):
            return JSONResponse(
                {"detail": "Origin is not allowed."},
                status_code=403,
            )

        if request.headers.get(CLIENT_HEADER) not in CLIENT_HEADER_VALUES:
            return JSONResponse(
                {"detail": "Missing PersonAgent client header."},
                status_code=401,
            )

        expected = configured_token or read_or_create_local_token(token_path)
        auth_header = request.headers.get("authorization") or ""
        prefix = "Bearer "
        supplied = auth_header[len(prefix) :].strip() if auth_header.startswith(prefix) else ""
        if not supplied or not secrets.compare_digest(supplied, expected):
            return JSONResponse(
                {"detail": "Invalid or missing local API token."},
                status_code=401,
            )
        return await call_next(request)


def persist_local_token(path: Path, token: str) -> str:
    """Persist a configured local auth token for Electron/preload consumers."""

    normalized = _normalize_local_token(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private(path.parent, file_mode=0o700)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing != normalized:
        path.write_text(f"{normalized}\n", encoding="utf-8")
    _chmod_private(path, file_mode=0o600)
    return normalized


def read_or_create_local_token(path: Path) -> str:
    """Read a local auth token, creating it with private permissions if absent."""

    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            _chmod_private(path, file_mode=0o600)
            return token
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private(path.parent, file_mode=0o700)
    token = secrets.token_urlsafe(48)
    path.write_text(f"{token}\n", encoding="utf-8")
    _chmod_private(path, file_mode=0o600)
    return token


def _configured_local_auth_token(settings: Any) -> str:
    return _normalize_local_token(getattr(settings, "personagent_local_auth_token", ""))


def _normalize_local_token(value: str) -> str:
    return str(value or "").strip()


def cors_allowed_origins(settings: Any) -> list[str]:
    """Return the configured local origins accepted by browser/Electron dev surfaces."""

    configured = getattr(settings, "personagent_cors_allowed_origins", None)
    if configured:
        return [item.strip() for item in str(configured).split(",") if item.strip()]
    ports = ("3000", "5173", "5174", "5175", "5176", "4176")
    origins: list[str] = []
    for host in ("localhost", "127.0.0.1"):
        origins.extend(f"http://{host}:{port}" for port in ports)
    return origins


def _chmod_private(path: Path, *, file_mode: int) -> None:
    try:
        path.chmod(file_mode)
    except OSError:
        # Some filesystems ignore chmod; auth still relies on token entropy.
        return
