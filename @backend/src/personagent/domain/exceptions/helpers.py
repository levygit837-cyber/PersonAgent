"""Exception helper functions."""

from __future__ import annotations

import re
from typing import Any

from personagent.domain.exceptions.base import ErrorCategory, PersonAgentError
from personagent.domain.exceptions.llm import (
    LLMBackendError,
    ProviderAuthError,
    ProviderContextOverflowError,
    ProviderHTTPError,
    ProviderOverloadedError,
    ProviderQuotaError,
    ProviderRateLimitError,
)
from personagent.domain.exceptions.request import InvalidRequestError
from personagent.domain.exceptions.system import InternalSystemError


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
    safe_detail = _redact_provider_error_detail(detail)
    metadata: dict[str, Any] = {"provider": provider, "status_code": status_code}
    if retry_after is not None:
        metadata["retry_after"] = retry_after
    message = f"{provider} HTTP {status_code}: {safe_detail}"
    if status_code in {401, 403}:
        return ProviderAuthError(
            message,
            http_status=status_code,
            metadata=metadata,
            safe_for_model=False,
        )
    if status_code == 429:
        lowered = safe_detail.lower()
        if "quota" in lowered or "insufficient_quota" in lowered:
            return ProviderQuotaError(message, metadata=metadata, safe_for_model=False)
        return ProviderRateLimitError(message, metadata=metadata, safe_for_model=False)
    if status_code == 413 or "context" in safe_detail.lower() and "limit" in safe_detail.lower():
        return ProviderContextOverflowError(message, metadata=metadata, safe_for_model=False)
    if status_code in {408, 409, 500, 502, 503, 504, 529}:
        return ProviderOverloadedError(
            message,
            metadata=metadata,
            safe_for_model=False,
        )
    return ProviderHTTPError(
        message,
        http_status=status_code if 400 <= status_code <= 599 else 502,
        metadata=metadata,
        safe_for_model=False,
    )


def _redact_provider_error_detail(detail: str) -> str:
    text = str(detail or "")
    text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{12,}\b", "[redacted]", text)
    text = re.sub(r"\bnvapi-[A-Za-z0-9_-]{12,}\b", "[redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^'\"\s,}]+",
        lambda match: f"{match.group(1)}=[redacted]",
        text,
    )
    return text
