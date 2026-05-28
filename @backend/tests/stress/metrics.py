"""Latency distribution metrics and report generation."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LatencyDistribution:
    """A named set of latency measurements."""

    name: str
    samples: list[float] = field(default_factory=list)

    def record(self, duration_ms: float) -> None:
        self.samples.append(duration_ms)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def p50(self) -> float:
        return _percentile(self.samples, 50)

    @property
    def p95(self) -> float:
        return _percentile(self.samples, 95)

    @property
    def p99(self) -> float:
        return _percentile(self.samples, 99)

    @property
    def mean(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def min(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": self.count,
            "p50_ms": round(self.p50, 2),
            "p95_ms": round(self.p95, 2),
            "p99_ms": round(self.p99, 2),
            "mean_ms": round(self.mean, 2),
            "min_ms": round(self.min, 2),
            "max_ms": round(self.max, 2),
        }


@dataclass
class StressReport:
    """Aggregated stress test report."""

    label: str
    distributions: list[LatencyDistribution] = field(default_factory=list)
    custom_metrics: dict[str, Any] = field(default_factory=dict)

    def add_distribution(self, dist: LatencyDistribution) -> None:
        self.distributions.append(dist)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "distributions": [d.to_dict() for d in self.distributions],
            "custom_metrics": self.custom_metrics,
        }

    def to_markdown(self) -> str:
        lines = [f"## {self.label}", ""]
        for dist in self.distributions:
            lines.append(f"### {dist.name}")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Samples | {dist.count} |")
            lines.append(f"| P50 | {dist.p50:.1f}ms |")
            lines.append(f"| P95 | {dist.p95:.1f}ms |")
            lines.append(f"| P99 | {dist.p99:.1f}ms |")
            lines.append(f"| Mean | {dist.mean:.1f}ms |")
            lines.append(f"| Min | {dist.min:.1f}ms |")
            lines.append(f"| Max | {dist.max:.1f}ms |")
            lines.append("")
        if self.custom_metrics:
            lines.append("### Custom Metrics")
            for key, value in self.custom_metrics.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
        return "\n".join(lines)

    def save(self, output_dir: str | Path) -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        json_path = out / f"{self.label.replace(' ', '_').lower()}.json"
        json_path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        md_path = out / f"{self.label.replace(' ', '_').lower()}.md"
        md_path.write_text(self.to_markdown())
        return json_path


@asynccontextmanager
async def measure(name: str, dist: LatencyDistribution) -> AsyncIterator[dict[str, Any]]:
    """Context manager that records the duration of a block into a distribution.

    Usage:
        async with measure("tool_execution", dist) as ctx:
            result = await run_tool()
            ctx["tool_count"] = len(result)
    """
    ctx: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        yield ctx
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        dist.record(elapsed)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
