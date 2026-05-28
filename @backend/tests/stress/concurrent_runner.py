"""Async concurrent request runner with latency collection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConcurrentResult:
    """Aggregated results from a concurrent test run."""

    total_requests: int
    successful: int
    failed: int
    latencies_ms: list[float] = field(default_factory=list)
    wall_time_ms: float = 0.0
    errors: list[Exception] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return percentile(self.latencies_ms, 50)

    @property
    def p95(self) -> float:
        return percentile(self.latencies_ms, 95)

    @property
    def p99(self) -> float:
        return percentile(self.latencies_ms, 99)

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def mean_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return sum(self.latencies_ms) / len(self.latencies_ms)

    @property
    def throughput_rps(self) -> float:
        if self.wall_time_ms <= 0:
            return 0.0
        return self.total_requests / (self.wall_time_ms / 1000)

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful / self.total_requests

    def summary(self, label: str = "") -> str:
        header = f"=== {label} ===" if label else "== Results =="
        lines = [
            header,
            f"Requests:   {self.total_requests} ({self.successful} ok, {self.failed} failed)",
            f"Wall time:  {self.wall_time_ms:.1f}ms",
            f"Throughput: {self.throughput_rps:.1f} req/s",
            f"Success:    {self.success_rate:.1%}",
            "Latency:",
            f"  P50:  {self.p50:.1f}ms",
            f"  P95:  {self.p95:.1f}ms",
            f"  P99:  {self.p99:.1f}ms",
            f"  Mean: {self.mean_ms:.1f}ms",
            f"  Min:  {self.min_ms:.1f}ms",
            f"  Max:  {self.max_ms:.1f}ms",
        ]
        return "\n".join(lines)


async def run_concurrent(
    n: int,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    semaphore: int | None = None,
) -> ConcurrentResult:
    """Run coro_factory() n times concurrently, collect latency metrics.

    Args:
        n: Number of concurrent invocations.
        coro_factory: Callable that returns a new coroutine each time.
        semaphore: Optional concurrency limit (caps parallel executions).

    Returns:
        ConcurrentResult with aggregated latency stats.
    """
    sem = asyncio.Semaphore(semaphore) if semaphore else None
    latencies: list[float] = []
    errors: list[Exception] = []

    async def _one() -> None:
        ctx = sem if sem else _noop_ctx()
        async with ctx:
            start = time.perf_counter()
            try:
                await coro_factory()
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
                errors.append(exc)

    wall_start = time.perf_counter()
    await asyncio.gather(*[_one() for _ in range(n)])
    wall_ms = (time.perf_counter() - wall_start) * 1000

    return ConcurrentResult(
        total_requests=n,
        successful=n - len(errors),
        failed=len(errors),
        latencies_ms=latencies,
        wall_time_ms=wall_ms,
        errors=errors,
    )


@asynccontextmanager
async def _noop_ctx():
    yield


def percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
