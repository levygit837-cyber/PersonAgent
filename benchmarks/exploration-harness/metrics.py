"""Metrics tracking for exploration benchmarks.

Tracks per-run and per-step metrics, computes scores, and serializes results.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""

    step: int
    tool_name: str
    arguments: dict[str, Any]
    duration_ms: float
    success: bool
    result_preview: str = ""


@dataclass
class CheckpointRecord:
    """Record of reaching a checkpoint."""

    checkpoint_id: str
    step_reached: int
    time_seconds: float
    description: str


@dataclass
class BenchmarkMetrics:
    """Complete metrics for a single benchmark run."""

    benchmark_id: str
    project: str
    model: str
    started_at: str = ""
    finished_at: str = ""

    # Outcome
    success: bool = False
    final_answer: str = ""
    failure_reason: str = ""

    # Steps and tools
    total_steps: int = 0
    max_steps_allowed: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    tool_counts: dict[str, int] = field(default_factory=dict)

    # Retry and stuck tracking
    retry_count: int = 0
    max_retries_allowed: int = 0
    stuck_count: int = 0
    stuck_events: list[dict[str, Any]] = field(default_factory=list)

    # Timing
    total_time_seconds: float = 0.0
    time_to_first_tool_seconds: float = 0.0
    checkpoint_times: list[CheckpointRecord] = field(default_factory=list)

    # Tokens
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Prompt composition (captured at runtime)
    system_prompt_chars: int = 0
    system_prompt_tokens: int | None = None
    mode_used: str = ""
    states_used: tuple[str, ...] = ()

    # Files accessed
    files_read: list[str] = field(default_factory=list)
    searches_made: list[str] = field(default_factory=list)

    def record_tool_call(
        self,
        step: int,
        tool_name: str,
        arguments: dict[str, Any],
        duration_ms: float,
        success: bool,
        result_preview: str = "",
    ) -> None:
        self.tool_calls.append(
            ToolCallRecord(
                step=step,
                tool_name=tool_name,
                arguments=arguments,
                duration_ms=duration_ms,
                success=success,
                result_preview=result_preview,
            )
        )
        self.tool_counts[tool_name] = self.tool_counts.get(tool_name, 0) + 1

        if tool_name == "Read" and "path" in arguments:
            path = arguments["path"]
            if path not in self.files_read:
                self.files_read.append(path)
        elif tool_name in ("Grep", "Glob") and "pattern" in arguments:
            pattern = arguments["pattern"]
            if pattern not in self.searches_made:
                self.searches_made.append(pattern)

    def record_checkpoint(
        self, checkpoint_id: str, step: int, elapsed: float, description: str
    ) -> None:
        self.checkpoint_times.append(
            CheckpointRecord(
                checkpoint_id=checkpoint_id,
                step_reached=step,
                time_seconds=elapsed,
                description=description,
            )
        )

    def record_stuck(self, reason: str, step: int) -> None:
        self.stuck_count += 1
        self.stuck_events.append({"reason": reason, "step": step})

    def compute_derived_metrics(self) -> dict[str, Any]:
        """Compute derived scoring metrics."""
        # Tool efficiency: ratio of unique files to total tool calls
        unique_files = len(self.files_read)
        total_tools = len(self.tool_calls)
        tool_efficiency = unique_files / max(total_tools, 1)

        # Success rate (binary)
        success_rate = 1.0 if self.success else 0.0

        # Checkpoint completion rate
        total_checkpoints = len(self.checkpoint_times)

        # Retry utilization
        retry_utilization = self.retry_count / max(self.max_retries_allowed, 1)

        # Stuck rate: stuck per step
        stuck_rate = self.stuck_count / max(self.total_steps, 1)

        return {
            "success_rate": round(success_rate, 2),
            "tool_efficiency": round(tool_efficiency, 2),
            "total_tool_calls": total_tools,
            "unique_files_read": unique_files,
            "unique_searches": len(self.searches_made),
            "checkpoints_reached": total_checkpoints,
            "retry_utilization": round(retry_utilization, 2),
            "stuck_rate": round(stuck_rate, 2),
            "avg_time_per_step_ms": round(
                (self.total_time_seconds * 1000) / max(self.total_steps, 1), 2
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        d = asdict(self)
        d["derived"] = self.compute_derived_metrics()
        return d

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


class BenchmarkSuiteMetrics:
    """Aggregate metrics across multiple benchmark runs."""

    def __init__(self) -> None:
        self.runs: list[BenchmarkMetrics] = []

    def add(self, metrics: BenchmarkMetrics) -> None:
        self.runs.append(metrics)

    def compute_summary(self) -> dict[str, Any]:
        if not self.runs:
            return {}

        total = len(self.runs)
        successes = sum(1 for r in self.runs if r.success)
        total_tools = sum(len(r.tool_calls) for r in self.runs)
        total_tokens = sum(r.total_tokens for r in self.runs)
        total_time = sum(r.total_time_seconds for r in self.runs)

        # Per-benchmark stats
        per_benchmark = {}
        for r in self.runs:
            per_benchmark[r.benchmark_id] = {
                "success": r.success,
                "steps": r.total_steps,
                "tools": len(r.tool_calls),
                "tokens": r.total_tokens,
                "time_seconds": round(r.total_time_seconds, 2),
                "mode": r.mode_used,
                "states": list(r.states_used),
            }

        return {
            "total_benchmarks": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate_pct": round((successes / total) * 100, 1),
            "avg_tools_per_run": round(total_tools / total, 2),
            "avg_tokens_per_run": round(total_tokens / total, 2),
            "avg_time_seconds": round(total_time / total, 2),
            "per_benchmark": per_benchmark,
        }

    def save(self, path: Path) -> None:
        summary = self.compute_summary()
        summary["runs"] = [r.to_dict() for r in self.runs]
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
