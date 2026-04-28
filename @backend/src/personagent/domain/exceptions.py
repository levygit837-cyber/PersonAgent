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


class InvalidRequestError(PersonAgentError):
    """The request is invalid."""

    code = "request.invalid"
    category = ErrorCategory.REQUEST
    http_status = 400


class InvalidMessageError(InvalidRequestError):
    """Invalid message supplied."""

    code = "request.invalid_message"


class ConflictStateError(PersonAgentError):
    """The requested operation conflicts with current state."""

    code = "request.conflict_state"
    category = ErrorCategory.REQUEST
    http_status = 409


class ConversationNotFoundError(PersonAgentError):
    """Conversation not found."""

    code = "conversation.not_found"
    category = ErrorCategory.CONVERSATION
    http_status = 404


class ConfigurationError(PersonAgentError):
    """System configuration is invalid."""

    code = "config.invalid"
    category = ErrorCategory.CONFIG
    http_status = 500


class WorkspaceScopeError(PersonAgentError):
    """Path is outside the configured workspace scope."""

    code = "workspace.scope_denied"
    category = ErrorCategory.WORKSPACE
    http_status = 403


class FileSystemError(PersonAgentError):
    """Filesystem operation failed."""

    code = "filesystem.error"
    category = ErrorCategory.FILESYSTEM
    http_status = 500


class LLMBackendError(PersonAgentError):
    """LLM provider request failed."""

    code = "provider.error"
    category = ErrorCategory.PROVIDER
    http_status = 500


class LLMBackendConnectionError(LLMBackendError):
    """Could not connect to the LLM provider."""

    code = "provider.connection"
    http_status = 503
    retryable = True


class LLMBackendTimeoutError(LLMBackendError):
    """LLM provider request timed out."""

    code = "provider.timeout"
    http_status = 504
    retryable = True


class ProviderAuthError(LLMBackendError):
    """LLM provider authentication failed."""

    code = "provider.auth"
    http_status = 401


class ProviderRateLimitError(LLMBackendError):
    """LLM provider rate limit exceeded."""

    code = "provider.rate_limited"
    http_status = 429
    retryable = True


class ProviderQuotaError(LLMBackendError):
    """LLM provider quota was exhausted."""

    code = "provider.quota"
    http_status = 429


class ProviderOverloadedError(LLMBackendError):
    """LLM provider is temporarily overloaded."""

    code = "provider.overloaded"
    http_status = 503
    retryable = True


class ProviderContextOverflowError(LLMBackendError):
    """Prompt or requested output exceeds the provider context window."""

    code = "provider.context_overflow"
    http_status = 413


class ProviderProtocolError(LLMBackendError):
    """LLM provider returned malformed or unsupported protocol data."""

    code = "provider.protocol"
    http_status = 502


class ProviderHTTPError(LLMBackendError):
    """LLM provider returned an HTTP error."""

    code = "provider.http_error"


class ToolError(PersonAgentError):
    """Tool execution failed."""

    code = "tool.error"
    category = ErrorCategory.TOOL
    http_status = 500


class ToolNotFoundError(ToolError):
    """Requested tool is not registered."""

    code = "tool.not_found"
    http_status = 404


class ToolInputValidationError(ToolError):
    """Tool input validation failed."""

    code = "tool.input_invalid"
    http_status = 400


class ToolPermissionRequiredError(ToolError):
    """Tool call requires user permission."""

    code = "tool.permission_required"
    http_status = 409


class ToolPermissionDeniedError(ToolError):
    """Tool call was denied."""

    code = "tool.permission_denied"
    http_status = 403


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""

    code = "tool.timeout"
    http_status = 504
    retryable = True


class ToolInterruptedError(ToolError):
    """Tool execution was interrupted."""

    code = "tool.interrupted"
    http_status = 499


class ToolResultTooLargeError(ToolError):
    """Tool result exceeded configured limits."""

    code = "tool.result_too_large"
    http_status = 413


class ToolLoopLimitExceededError(ToolError):
    """Maximum tool iteration count was reached."""

    code = "tool.loop_limit_exceeded"
    http_status = 409


class ShellCommandDeniedError(ToolPermissionDeniedError):
    """Shell command was denied by policy."""

    code = "shell.command_denied"
    category = ErrorCategory.SHELL


class ShellTimeoutError(ToolTimeoutError):
    """Shell command timed out."""

    code = "shell.timeout"
    category = ErrorCategory.SHELL


class ShellCommandFailedError(ToolError):
    """Shell command exited with a non-zero code."""

    code = "shell.non_zero_exit"
    category = ErrorCategory.SHELL


class WebError(ToolError):
    """Web tool failed."""

    code = "web.error"
    category = ErrorCategory.WEB


class WebURLInvalidError(WebError):
    """URL is invalid for web access."""

    code = "web.url_invalid"
    http_status = 400


class WebDomainBlockedError(WebError):
    """URL host is blocked by policy."""

    code = "web.domain_blocked"
    http_status = 403


class WebFetchTimeoutError(WebError):
    """Web fetch timed out."""

    code = "web.fetch_timeout"
    http_status = 504
    retryable = True


class BrowserError(ToolError):
    """Browser tool failed."""

    code = "browser.error"
    category = ErrorCategory.BROWSER


class BrowserUnavailableError(BrowserError):
    """Browser backend is unavailable."""

    code = "browser.unavailable"
    http_status = 503
    retryable = True


class BrowserNavigationTimeoutError(BrowserError):
    """Browser navigation timed out."""

    code = "browser.navigation_timeout"
    http_status = 504
    retryable = True


class McpError(ToolError):
    """MCP operation failed."""

    code = "mcp.error"
    category = ErrorCategory.MCP


class McpAuthRequiredError(McpError):
    """MCP server requires authentication."""

    code = "mcp.auth_required"
    http_status = 401


class McpSessionExpiredError(McpError):
    """MCP session expired."""

    code = "mcp.session_expired"
    http_status = 401
    retryable = True


class McpRequestTimeoutError(McpError):
    """MCP request timed out."""

    code = "mcp.request_timeout"
    http_status = 504
    retryable = True


class MemoryError(PersonAgentError):
    """Memory subsystem failed."""

    code = "memory.error"
    category = ErrorCategory.MEMORY
    http_status = 500


class TeamError(PersonAgentError):
    """Team mode failed."""

    code = "team.error"
    category = ErrorCategory.TEAM
    http_status = 500


class TeamValidationSystemError(TeamError):
    """Team mode validation failed."""

    code = "team.validation"
    http_status = 400


class BackgroundJobError(PersonAgentError):
    """Background job failed."""

    code = "background.job_failed"
    category = ErrorCategory.BACKGROUND
    http_status = 500


class DatabaseError(PersonAgentError):
    """Database operation failed."""

    code = "database.error"
    category = ErrorCategory.DATABASE
    http_status = 500
    retryable = True


class InternalSystemError(PersonAgentError):
    """Unexpected internal system error."""

    code = "system.internal_error"
    category = ErrorCategory.SYSTEM
    http_status = 500
    safe_for_model = False


def ensure_personagent_error(
    exc: BaseException,
    *,
    default_message: str = "Unexpected internal error.",
    correlation_id: str | None = None,
) -> PersonAgentError:
    """Convert arbitrary exceptions into a structured PersonAgentError."""
    if isinstance(exc, PersonAgentError):
        return exc
    if isinstance(exc, TimeoutError):
        return PersonAgentError(
            "Operation timed out.",
            code="system.timeout",
            category=ErrorCategory.SYSTEM,
            http_status=504,
            retryable=True,
            cause=exc,
            correlation_id=correlation_id,
        )
    if isinstance(exc, ValueError):
        return InvalidRequestError(str(exc), cause=exc, correlation_id=correlation_id)
    return InternalSystemError(
        default_message,
        internal_message=str(exc) or type(exc).__name__,
        cause=exc,
        correlation_id=correlation_id,
    )


def provider_http_error(
    *,
    provider: str,
    status_code: int,
    detail: str,
    retry_after: str | None = None,
) -> LLMBackendError:
    """Classify an HTTP provider failure into a provider-specific error."""
    metadata = {
        "provider": provider,
        "status_code": status_code,
    }
    if retry_after:
        metadata["retry_after"] = retry_after
    message = f"{provider} HTTP {status_code}: {detail}"
    if status_code in {401, 403}:
        return ProviderAuthError(message, http_status=status_code, metadata=metadata)
    if status_code == 429:
        lowered = detail.lower()
        if "quota" in lowered or "insufficient_quota" in lowered:
            return ProviderQuotaError(message, metadata=metadata)
        return ProviderRateLimitError(message, metadata=metadata)
    if status_code == 413 or "context" in detail.lower() and "limit" in detail.lower():
        return ProviderContextOverflowError(message, metadata=metadata)
    if status_code in {408, 409, 500, 502, 503, 504, 529}:
        return ProviderOverloadedError(message, metadata=metadata, http_status=503)
    return ProviderHTTPError(
        message,
        http_status=status_code if 400 <= status_code <= 599 else 502,
        retryable=500 <= status_code <= 599,
        metadata=metadata,
    )


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


__all__ = [
    "BackgroundJobError",
    "BrowserError",
    "BrowserNavigationTimeoutError",
    "BrowserUnavailableError",
    "ConfigurationError",
    "ConflictStateError",
    "ConversationNotFoundError",
    "DatabaseError",
    "ErrorCategory",
    "ErrorSeverity",
    "FileSystemError",
    "InternalSystemError",
    "InvalidMessageError",
    "InvalidRequestError",
    "LLMBackendConnectionError",
    "LLMBackendError",
    "LLMBackendTimeoutError",
    "McpAuthRequiredError",
    "McpError",
    "McpRequestTimeoutError",
    "McpSessionExpiredError",
    "MemoryError",
    "PersonAgentError",
    "ProviderAuthError",
    "ProviderContextOverflowError",
    "ProviderHTTPError",
    "ProviderOverloadedError",
    "ProviderProtocolError",
    "ProviderQuotaError",
    "ProviderRateLimitError",
    "ShellCommandDeniedError",
    "ShellCommandFailedError",
    "ShellTimeoutError",
    "TeamError",
    "TeamValidationSystemError",
    "ToolError",
    "ToolInputValidationError",
    "ToolInterruptedError",
    "ToolLoopLimitExceededError",
    "ToolNotFoundError",
    "ToolPermissionDeniedError",
    "ToolPermissionRequiredError",
    "ToolResultTooLargeError",
    "ToolTimeoutError",
    "WebDomainBlockedError",
    "WebError",
    "WebFetchTimeoutError",
    "WebURLInvalidError",
    "WorkspaceScopeError",
    "ensure_personagent_error",
    "provider_http_error",
]
