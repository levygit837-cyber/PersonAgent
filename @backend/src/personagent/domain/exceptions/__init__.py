"""PersonAgent domain exceptions."""

from personagent.domain.exceptions.base import (
    ErrorCategory,
    ErrorSeverity,
    PersonAgentError,
)
from personagent.domain.exceptions.browser import (
    BrowserError,
    BrowserNavigationTimeoutError,
    BrowserUnavailableError,
)
from personagent.domain.exceptions.helpers import (
    ensure_personagent_error,
    provider_http_error,
)
from personagent.domain.exceptions.llm import (
    LLMBackendConnectionError,
    LLMBackendError,
    LLMBackendTimeoutError,
    ProviderAuthError,
    ProviderContextOverflowError,
    ProviderHTTPError,
    ProviderOverloadedError,
    ProviderProtocolError,
    ProviderQuotaError,
    ProviderRateLimitError,
)
from personagent.domain.exceptions.mcp import (
    McpAuthRequiredError,
    McpError,
    McpRequestTimeoutError,
    McpSessionExpiredError,
)
from personagent.domain.exceptions.request import (
    ConfigurationError,
    ConflictStateError,
    ConversationNotFoundError,
    FileSystemError,
    InvalidMessageError,
    InvalidRequestError,
    WorkspaceScopeError,
)
from personagent.domain.exceptions.shell import (
    ShellCommandDeniedError,
    ShellCommandFailedError,
    ShellTimeoutError,
)
from personagent.domain.exceptions.system import (
    BackgroundJobError,
    DatabaseError,
    InternalSystemError,
    MemoryError,
    TeamError,
    TeamValidationSystemError,
)
from personagent.domain.exceptions.tool import (
    ToolError,
    ToolInputValidationError,
    ToolInterruptedError,
    ToolLoopLimitExceededError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolPermissionRequiredError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)
from personagent.domain.exceptions.web import (
    WebDomainBlockedError,
    WebError,
    WebFetchTimeoutError,
    WebURLInvalidError,
)

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
    "MemoryError",
    "McpAuthRequiredError",
    "McpError",
    "McpRequestTimeoutError",
    "McpSessionExpiredError",
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
