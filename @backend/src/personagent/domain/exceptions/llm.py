from personagent.domain.exceptions.base import ErrorCategory, PersonAgentError


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


