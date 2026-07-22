#!/usr/bin/env python3
"""Trace analyzer for exploration benchmarks.

Reads benchmark traces and produces structured analysis using
heuristic scoring and prompt composition inspection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_trace(trace_path: Path) -> list[dict[str, Any]]:
    return json.loads(trace_path.read_text(encoding="utf-8"))


def load_metrics(metrics_path: Path) -> dict[str, Any]:
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def analyze_trace(trace: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    """Produce a structured analysis of a single benchmark trace."""
    # Extract key events
    assistant_msgs = [e for e in trace if e.get("event") == "assistant_message"]
    tool_results = [e for e in trace if e.get("event") == "tool_result"]
    stuck_events = [e for e in trace if e.get("event") == "stuck_detected"]
    retry_events = [e for e in trace if e.get("event") == "retry_injected"]
    checkpoint_events = [e for e in trace if e.get("event") == "checkpoint"]

    # Tool usage patterns
    tool_sequence: list[str] = []
    for e in assistant_msgs:
        for tc in e.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_sequence.append(fn.get("name", "unknown"))

    # File exploration depth
    files_read: set[str] = set()
    for e in tool_results:
        if e.get("tool_name") == "Read":
            args = e.get("arguments", {})
            if "path" in args:
                files_read.add(args["path"])

    # Search breadth
    searches: set[str] = set()
    for e in tool_results:
        if e.get("tool_name") in ("Grep", "Glob"):
            args = e.get("arguments", {})
            if "pattern" in args:
                searches.add(args["pattern"])

    # Response quality indicators
    final_answer = ""
    for e in reversed(trace):
        if e.get("event") == "final_answer":
            final_answer = e.get("content", "")
            break

    # Heuristic scoring
    scores: dict[str, Any] = {}

    # 1. Exploration Breadth Score (0-100)
    # Based on unique files read and searches made
    unique_files = len(files_read)
    unique_searches = len(searches)
    breadth_score = min(100, (unique_files * 10) + (unique_searches * 5))
    scores["exploration_breadth"] = round(breadth_score, 1)

    # 2. Tool Efficiency Score (0-100)
    # Ratio of unique files to total tool calls
    total_tools = len(tool_results)
    if total_tools > 0:
        efficiency = (unique_files / total_tools) * 100
    else:
        efficiency = 0
    scores["tool_efficiency"] = round(min(100, efficiency), 1)

    # 3. Persistence Score (0-100)
    # How well did the agent handle retries and stuck detection
    retries = len(retry_events)
    stuck = len(stuck_events)
    if retries == 0 and stuck == 0:
        persistence = 100
    else:
        # Penalize for getting stuck, reward for recovering
        persistence = max(0, 100 - (stuck * 20) + (retries * 10))
    scores["persistence"] = round(min(100, persistence), 1)

    # 4. Answer Quality Score (0-100)
    # Based on length, file references, and expected findings
    answer_lower = final_answer.lower()
    file_refs = sum(1 for ext in (".py", ".ts", ".tsx", ".js", ".rs") if ext in final_answer)
    expected_findings = metrics.get("expected_findings", [])
    found_terms = sum(1 for term in expected_findings if term.lower() in answer_lower)
    finding_coverage = (found_terms / max(len(expected_findings), 1)) * 100 if expected_findings else 50

    answer_score = min(100, (len(final_answer) / 50) + (file_refs * 10) + finding_coverage)
    scores["answer_quality"] = round(min(100, answer_score), 1)

    # 5. Prompt Harness Effectiveness (0-100)
    # Did the prompt guide the agent to explore properly?
    # Look for signs of good exploration: multiple file types, cross-directory reads, synthesis
    has_multi_dir = len(set(Path(f).parent for f in files_read)) > 2 if files_read else False
    has_synthesis = any(word in answer_lower for word in ["therefore", "conclusion", "summary", "in summary"])
    harness_score = 40
    if has_multi_dir:
        harness_score += 20
    if has_synthesis:
        harness_score += 20
    if unique_files >= 5:
        harness_score += 20
    scores["prompt_harness_effectiveness"] = round(min(100, harness_score), 1)

    # Overall Score (weighted average)
    overall = (
        scores["exploration_breadth"] * 0.25 +
        scores["tool_efficiency"] * 0.20 +
        scores["persistence"] * 0.15 +
        scores["answer_quality"] * 0.25 +
        scores["prompt_harness_effectiveness"] * 0.15
    )
    scores["overall"] = round(overall, 1)

    # Analysis text
    analysis = {
        "benchmark_id": metrics.get("benchmark_id", "unknown"),
        "project": metrics.get("project", ""),
        "success": metrics.get("success", False),
        "scores": scores,
        "statistics": {
            "total_steps": metrics.get("total_steps", 0),
            "total_tool_calls": total_tools,
            "unique_files_read": unique_files,
            "unique_searches": unique_searches,
            "stuck_events": stuck,
            "retry_events": retries,
            "checkpoints_reached": len(checkpoint_events),
            "total_tokens": metrics.get("total_tokens", 0),
            "total_time_seconds": metrics.get("total_time_seconds", 0),
        },
        "tool_sequence": tool_sequence,
        "files_read": sorted(files_read),
        "searches_made": sorted(searches),
        "stuck_reasons": [e.get("reason", "") for e in stuck_events],
        "key_observations": [],
        "recommendations": [],
    }

    # Generate observations
    observations: list[str] = []
    if stuck > 2:
        observations.append(f"Agent got stuck {stuck} times, suggesting the prompt may not provide sufficient guidance for navigating complex codebases.")
    if unique_files < 3 and total_tools > 5:
        observations.append("Agent made many tool calls but explored few unique files, indicating potential redundant or ineffective searches.")
    if not final_answer or len(final_answer) < 200:
        observations.append("Final answer was very short or absent, suggesting the agent may not have synthesized findings effectively.")
    if unique_searches < 2 and unique_files > 5:
        observations.append("Agent found files without using search tools, possibly due to prior knowledge or lucky guesses.")
    if metrics.get("success"):
        observations.append("Benchmark was successful, indicating the prompt harness provided adequate exploration guidance.")
    else:
        observations.append("Benchmark failed. The agent may need stronger direction to explore deeply or synthesize properly.")

    analysis["key_observations"] = observations

    # Generate recommendations
    recommendations: list[str] = []
    if stuck > 1:
        recommendations.append("Consider adding explicit 'if stuck, try X' guidance to the system prompt for exploration tasks.")
    if unique_files < 5:
        recommendations.append("The prompt could encourage broader initial exploration (e.g., 'read at least 3-5 files before answering').")
    if not has_synthesis:
        recommendations.append("Add synthesis instructions to the prompt: 'After gathering evidence, write a structured answer with file references.'")
    if total_tools > 20:
        recommendations.append("High tool call count suggests inefficiency. The prompt could guide more targeted searches.")

    analysis["recommendations"] = recommendations

    return analysis


def analyze_suite(trace_dir: Path) -> dict[str, Any]:
    """Analyze all benchmark traces in a directory."""
    all_analyses: list[dict[str, Any]] = []
    metrics_files = sorted(trace_dir.glob("*_metrics.json"))

    for metrics_path in metrics_files:
        trace_path = metrics_path.with_name(metrics_path.name.replace("_metrics.json", "_trace.json"))
        if not trace_path.exists():
            continue

        trace = load_trace(trace_path)
        metrics = load_metrics(metrics_path)
        analysis = analyze_trace(trace, metrics)
        all_analyses.append(analysis)

    # Compute aggregate scores
    if not all_analyses:
        return {"analyses": [], "summary": {}}

    agg_scores: dict[str, list[float]] = {
        "exploration_breadth": [],
        "tool_efficiency": [],
        "persistence": [],
        "answer_quality": [],
        "prompt_harness_effectiveness": [],
        "overall": [],
    }
    success_count = 0
    total_time = 0
    total_tokens = 0

    for a in all_analyses:
        for key in agg_scores:
            agg_scores[key].append(a["scores"][key])
        if a["success"]:
            success_count += 1
        total_time += a["statistics"]["total_time_seconds"]
        total_tokens += a["statistics"]["total_tokens"]

    summary = {
        "total_benchmarks": len(all_analyses),
        "successes": success_count,
        "success_rate_pct": round((success_count / len(all_analyses)) * 100, 1),
        "avg_scores": {
            key: round(sum(vals) / len(vals), 1) if vals else 0
            for key, vals in agg_scores.items()
        },
        "total_time_seconds": round(total_time, 1),
        "total_tokens": total_tokens,
    }

    return {
        "analyses": all_analyses,
        "summary": summary,
    }


def main() -> None:
    trace_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmarks/traces")
    if not trace_dir.exists():
        print(f"Trace directory not found: {trace_dir}")
        sys.exit(1)

    result = analyze_suite(trace_dir)
    output_path = trace_dir / "analysis_report.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Analysis saved to {output_path}")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
