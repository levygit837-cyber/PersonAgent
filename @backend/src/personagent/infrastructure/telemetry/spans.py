"""Span helpers for instrumenting critical code paths."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace


@asynccontextmanager
async def traced_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[trace.Span]:
    """Create a traced span with automatic duration_ms recording.

    Usage:
        async with traced_span("memory.recall", {"project": slug}) as span:
            result = await do_recall()
            span.set_attribute("result_count", len(result))
    """
    tracer = trace.get_tracer("personagent")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        start = time.perf_counter()
        try:
            yield span
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("duration_ms", round(duration_ms, 3))


def record_duration(span: trace.Span, key: str, duration_ms: float) -> None:
    """Record a measured duration as a span attribute."""
    span.set_attribute(key, round(duration_ms, 3))
