# ADR 0016: Bounded Retry Budget with Exponential Backoff and Delay Tracking

Date: 2025-06-10
Status: Accepted

## Context

LLM providers, local servers, and web tools can fail transiently (rate limits, network blips, process startup delays). Blind retry loops can waste tokens, money, and user patience. We need a bounded, observable retry policy.

## Decision

Implement a `RetryPolicy` + `RetryBudget` pair in `application/retry.py`.

**RetryPolicy**
- `max_attempts`: default 3.
- `base_delay_seconds`: 0.5, doubling each attempt (`exponential backoff`).
- `max_delay_seconds`: 10.0 cap.
- `jitter_seconds`: 0.25 random spread.
- Rate-limit retries are foreground-only (`foreground_only_for_rate_limits=True`).

**RetryBudget**
- Records every attempt with `attempt`, `delay_seconds`, `error.code`, and `retryable` flag.
- Exposed in error metadata so the frontend can show "retried 2 times".

**Retryable errors**
- `LLMBackendConnectionError`, `LLMBackendTimeoutError`, `ProviderOverloadedError`, `ProviderRateLimitError`, `ToolTimeoutError`.
- Non-retryable: emitted output, non-idempotent operations, permission denied.

**Usage**
```python
await retry_async(
    operation=lambda: llm_backend.chat_completion(...),
    policy=RetryPolicy(max_attempts=3),
    foreground=True,
    idempotent=True,
)
```

## Consequences

- **Easier**: resilient to transient failures; budget metadata improves user trust.
- **Harder**: every async call site must decide if it is idempotent; forgetting the flag leads to duplicate side effects.
- **Risk**: a provider that is consistently overloaded will still fail after 3 attempts; the user sees a generic timeout.
- **Out of scope**: circuit breakers; automatic provider fallback on repeated failure (planned).

## Alternatives Considered

- **Tenacity library**: rejected to avoid a runtime dependency and keep retry semantics aligned with our error hierarchy.
- **Infinite retry with backoff**: rejected because it blocks the conversation indefinitely.

## Validation

- Unit tests verify backoff math, jitter bounds, and non-retryable error rejection.
- `DEFAULT_PROVIDER_RETRY_POLICY` is used by all LLM adapters.
