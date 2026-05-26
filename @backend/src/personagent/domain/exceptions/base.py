"""Structured domain errors for PersonAgent.

The domain error layer is intentionally transport-agnostic. FastAPI, SSE,
WebSocket, tool results, and telemetry all serialize these exceptions through
small boundary adapters instead of inventing their own error shapes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4


class ErrorCategory(StrEnum):
    """Stable high-level error categories used across transports."""

    REQUEST = "request"
    AUTH = "auth"
    CONVERSATION = "conversation"
    PROVIDER = "provider"
    TOOL = "tool"
    WORKSPACE = "workspace"
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    BROWSER = "browser"
    WEB = "web"
    MCP = "mcp"
    MEMORY = "memory"
    TEAM = "team"
    BACKGROUND = "background"
    CONFIG = "config"
    DATABASE = "database"
    SYSTEM = "system"


class ErrorSeverity(StrEnum):
    """Operational severity used for logging and UI treatment."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class PersonAgentError(Exception):
    """Base exception with a stable, serializable error envelope."""

    code = "system.internal_error"
    category = ErrorCategory.SYSTEM
    severity = ErrorSeverity.ERROR
    http_status = 500
    retryable = False
    safe_for_model = True
    safe_for_telemetry = True

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        category: ErrorCategory | str | None = None,
        severity: ErrorSeverity | str | None = None,
        http_status: int | None = None,
        retryable: bool | None = None,
        user_message: str | None = None,
        internal_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        correlation_id: str | None = None,
        safe_for_model: bool | None = None,
        safe_for_telemetry: bool | None = None,
    ) -> None:
        self.code = code or self.code
        self.category = ErrorCategory(category or self.category)
        self.severity = ErrorSeverity(severity or self.severity)
        self.http_status = int(http_status or self.http_status)
        self.retryable = self.retryable if retryable is None else bool(retryable)
        self.user_message = user_message or message or self.default_message()
        self.internal_message = internal_message or self.user_message
        self.metadata = dict(metadata or {})
        self.cause = cause
        self.correlation_id = correlation_id or uuid4().hex
        self.safe_for_model = self.safe_for_model if safe_for_model is None else safe_for_model
        self.safe_for_telemetry = (
            self.safe_for_telemetry if safe_for_telemetry is None else safe_for_telemetry
        )
        super().__init__(self.user_message)

    @classmethod
    def default_message(cls) -> str:
        """Return a generic message for subclasses instantiated without text."""
        return cls.__doc__.strip() if cls.__doc__ else "PersonAgent error."

    def to_envelope(self, *, include_internal: bool = False) -> dict[str, Any]:
        """Serialize the error for API, SSE, WebSocket, or tool metadata."""
        envelope: dict[str, Any] = {
            "code": self.code,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.user_message,
            "status": self.http_status,
            "retryable": self.retryable,
            "correlation_id": self.correlation_id,
            "safe_for_model": self.safe_for_model,
            "safe_for_telemetry": self.safe_for_telemetry,
        }
        if self.metadata:
            envelope["metadata"] = _json_safe(self.metadata)
        if include_internal and self.internal_message != self.user_message:
            envelope["internal_message"] = self.internal_message
        if include_internal and self.cause is not None:
            envelope["cause"] = type(self.cause).__name__
        return envelope



def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item, depth=depth + 1) for item in value]
    return str(value)
