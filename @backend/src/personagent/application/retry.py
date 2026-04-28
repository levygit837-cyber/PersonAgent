"""Central bounded retry policy used by providers and tool-side adapters."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from personagent.domain.exceptions import (
    LLMBackendConnectionError,
    LLMBackendTimeoutError,
    PersonAgentError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    ToolTimeoutError,
)

T = TypeVar("T")


@dataclass(slots=True)
class RetryAttempt:
    """Recorded retry attempt for error metadata and diagnostics."""

    attempt: int
    delay_seconds: float
    code: str
    retryable: bool


@dataclass(slots=True)
class RetryBudget:
    """Per-operation retry budget."""

    max_attempts: int = 3
    attempts: list[RetryAttempt] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.max_attempts - len(self.attempts) - 1)

    def record(self, *, attempt: int, delay_seconds: float, error: PersonAgentError) -> None:
        self.attempts.append(
            RetryAttempt(
                attempt=attempt,
                delay_seconds=delay_seconds,
                code=error.code,
                retryable=error.retryable,
            )
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "attempts": [
                {
                    "attempt": item.attempt,
                    "delay_seconds": item.delay_seconds,
                    "code": item.code,
                    "retryable": item.retryable,
                }
                for item in self.attempts
            ],
        }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy with foreground/background controls."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 10.0
    jitter_seconds: float = 0.25
    foreground_only_for_rate_limits: bool = True

    def should_retry(
        self,
        error: BaseException,
        *,
        attempt: int,
        foreground: bool = True,
        emitted_output: bool = False,
        idempotent: bool = True,
    ) -> bool:
        """Return whether another attempt is allowed for this failure."""
        if attempt >= self.max_attempts:
            return False
        if emitted_output or not idempotent:
            return False
        if not _is_retryable_error(error):
            return False
        return not (
            self.foreground_only_for_rate_limits
            and not foreground
            and isinstance(error, ProviderRateLimitError | ProviderOverloadedError)
        )

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """Compute retry delay for a 1-based attempt number."""
        if retry_after is not None and retry_after >= 0:
            return min(float(retry_after), self.max_delay_seconds)
        exponential = self.base_delay_seconds * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0, self.jitter_seconds) if self.jitter_seconds > 0 else 0.0
        return float(min(exponential + jitter, self.max_delay_seconds))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    budget: RetryBudget | None = None,
    foreground: bool = True,
    emitted_output: Callable[[], bool] | bool = False,
    idempotent: bool = True,
) -> T:
    """Run an async operation with a bounded retry budget."""
    policy = policy or RetryPolicy()
    budget = budget or RetryBudget(max_attempts=policy.max_attempts)
    attempt = 1
    while True:
        try:
            return await operation()
        except Exception as exc:
            has_emitted = emitted_output() if callable(emitted_output) else bool(emitted_output)
            if not policy.should_retry(
                exc,
                attempt=attempt,
                foreground=foreground,
                emitted_output=has_emitted,
                idempotent=idempotent,
            ):
                if isinstance(exc, PersonAgentError) and budget.attempts:
                    exc.metadata.setdefault("retry", budget.to_metadata())
                raise
            error = exc if isinstance(exc, PersonAgentError) else PersonAgentError(str(exc))
            delay = policy.delay_for(attempt, retry_after=_retry_after(error))
            budget.record(attempt=attempt, delay_seconds=delay, error=error)
            await asyncio.sleep(delay)
            attempt += 1


def _is_retryable_error(error: BaseException) -> bool:
    if isinstance(error, PersonAgentError):
        return bool(error.retryable)
    return isinstance(error, TimeoutError | ConnectionError)


def _retry_after(error: PersonAgentError) -> float | None:
    value = error.metadata.get("retry_after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


DEFAULT_PROVIDER_RETRY_POLICY = RetryPolicy(max_attempts=3)
TRANSIENT_RETRYABLE_ERRORS = (
    LLMBackendConnectionError,
    LLMBackendTimeoutError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    ToolTimeoutError,
)


__all__ = [
    "DEFAULT_PROVIDER_RETRY_POLICY",
    "RetryAttempt",
    "RetryBudget",
    "RetryPolicy",
    "TRANSIENT_RETRYABLE_ERRORS",
    "retry_async",
]
