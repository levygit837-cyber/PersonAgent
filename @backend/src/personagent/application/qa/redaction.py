"""Redaction helpers for QA traces and persisted artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "session",
    "private_key",
    "client_secret",
)


def redact_mapping(value: Mapping[str, Any] | None, *, max_string: int = 2_000) -> dict[str, Any]:
    """Return a JSON-safe redacted copy of a mapping."""
    return {
        str(key): _redact_value(str(key), item, max_string=max_string)
        for key, item in dict(value or {}).items()
    }


def redact_value(value: Any, *, max_string: int = 2_000) -> Any:
    """Return a JSON-safe redacted value when no key context is available."""
    return _redact_value("", value, max_string=max_string)


def _redact_value(key: str, value: Any, *, max_string: int) -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return redact_mapping(value, max_string=max_string)
    if isinstance(value, list | tuple):
        return [_redact_value("", item, max_string=max_string) for item in value[:100]]
    if isinstance(value, bytes):
        text = value[:max_string].decode("utf-8", errors="replace")
        return text + ("...[truncated]" if len(value) > max_string else "")
    if isinstance(value, str):
        if len(value) > max_string:
            return value[:max_string] + "...[truncated]"
        return value
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)


__all__ = ["redact_mapping", "redact_value"]
