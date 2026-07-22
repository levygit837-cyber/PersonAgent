#!/usr/bin/env python3
"""Trace evaluator — computes benchmark metrics from a run trace.

Usage:
    python benchmarks/scripts/evaluate_trace.py \\
        --trace benchmarks/traces/opencode_medium_*.jsonl \\
        --output benchmarks/results/opencode_medium_eval.json

    # Evaluate all traces in a directory
    python benchmarks/scripts/evaluate_trace.py \\
        --trace benchmarks/traces/*.jsonl \\
        --output benchmarks/results/full_eval.json

Produces a scored result with all metrics, grade, and improvement suggestions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BENCH_DIR = Path(__file__).parent.parent
GOALS_PATH = BENCH_DIR / "evals" / "project_goals.yaml"
METRICS_PATH = BENCH_DIR / "evals" / "metrics.yaml"


# ─── Data models ─────────────────────────────────────────────────────────────
@dataclass
class ScoredTrace:
    run_id: str
    project: str
    goal_id: str
    difficulty: str
    question: str = ""

    exploration_score: float = 0.0  # 0-100
    tool_efficiency: float = 0.0  # 0-100
    synthesis_quality: float = 0.0  # 0-100
    success_rate: float = 0.0  # 0-100 (0, 50, or 100)
    token_efficiency: float = 0.0  # tokens per step (lower is better)
    time_to_first_evidence: float = 0.0  # seconds
    stuck_count: int = 0
    retry_success_rate: float = 0.0  # 0-100
    hallucination_detected: bool = False

    final_score: float = 0.0
    grade: str = "F"
    improvement_suggestions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


# ─── Loading ─────────────────────────────────────────────────────────────────
def load_goals() -> dict:
    return yaml.safe_load(GOALS_PATH.read_text())


def load_metrics() -> dict:
    return yaml.safe_load(METRICS_PATH.read_text())


def load_trace(path: Path) -> dict:
    """Load a JSONL trace file. First line is meta, rest are steps."""
    lines = path.read_text().strip().splitlines()
    meta = json.loads(lines[0])
    steps = [json.loads(line) for line in lines[1:]]
    return {"meta": meta, "steps": steps}


# ─── Scoring functions ───────────────────────────────────────────────────────
def score_exploration(trace: dict, goal: dict) -> tuple[float, dict]:
    """Compute exploration depth: what % of required surfaces were covered?"""
    required = set(goal.get("surfaces", []))
    if not required:
        return 100.0, {"required": [], "covered": [], "uncovered": []}

    covered = set()
    # Infer surfaces from tool calls and file reads in steps
    for step in trace["steps"]:
        if step.get("role") != "assistant":
            continue
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "").lower()
            args = tc.get("function", {}).get("arguments", "")
            if "read" in name or "grep" in name:
                # Infer surface from file path in arguments
                if "entrypoint" in args or "cmd" in args or "main" in args:
                    covered.add("entrypoint")
                if "domain" in args or "internal" in args or "model" in args:
                    covered.add("domain")
                if "adapter" in args or "api" in args or "route" in args:
                    covered.add("adapters")
                if "test" in args:
                    covered.add("tests")
                if "config" in args or "pyproject" in args or "package" in args or ".toml" in args or ".json" in args:
                    covered.add("config")

    # Also check the final answer for surface mentions
    final_answer = trace["meta"].get("final_answer_preview", "")
    for surface in required:
        if surface in final_answer.lower():
            covered.add(surface)

    uncovered = required - covered
    score = (len(covered) / len(required)) * 100 if required else 100.0
    return score, {"required": list(required), "covered": list(covered), "uncovered": list(uncovered)}


def score_tool_efficiency(trace: dict) -> tuple[float, dict]:
    """Compute tool efficiency: useful calls / total calls."""
    total_calls = 0
    useful_calls = 0
    call_types: dict[str, int] = {}

    for step in trace["steps"]:
        if step.get("role") != "assistant":
            continue
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            total_calls += 1
            name = tc.get("function", {}).get("name", "unknown")
            call_types[name] = call_types.get(name, 0) + 1
            # Useful = not a repeated search on same pattern (simple heuristic)
            args = tc.get("function", {}).get("arguments", "")
            # Assume all Read/Grep calls are useful for now; shell is riskier
            if "read" in name.lower() or "grep" in name.lower() or "glob" in name.lower():
                useful_calls += 1
            elif "shell" in name.lower():
                useful_calls += 0.5
            else:
                useful_calls += 0.8

    score = (useful_calls / total_calls) * 100 if total_calls else 0.0
    return score, {"total": total_calls, "useful": useful_calls, "breakdown": call_types}


def score_synthesis(trace: dict) -> tuple[float, dict]:
    """Score final answer quality: evidence, file refs, reasoning."""
    final = trace["meta"].get("final_answer_preview", "")
    if not final:
        return 0.0, {"has_answer": False, "has_evidence": False, "has_lines": False, "has_reasoning": False}

    score = 0.0
    checks = {
        "has_answer": len(final) > 50,
        "has_evidence": "## Evidence" in final or "file" in final.lower(),
        "has_lines": bool(re.search(r"line \d+|`[^`]+`|\.\w+:\d+", final)),
        "has_reasoning": "## Uncertainty" in final or "because" in final.lower() or "however" in final.lower(),
    }

    if checks["has_answer"]:
        score = 25
    if checks["has_evidence"]:
        score += 25
    if checks["has_lines"]:
        score += 25
    if checks["has_reasoning"]:
        score += 25

    return score, checks


def score_success(trace: dict, goal: dict) -> tuple[float, dict]:
    """Binary/partial success based on answer vs expected."""
    final = trace["meta"].get("final_answer_preview", "")
    expected = goal.get("expected_answer_brief", "")

    if not final:
        return 0.0, {"has_answer": False, "matches_expected": False}

    # Simple keyword overlap heuristic (a real eval would use an LLM judge)
    expected_keywords = set(re.findall(r"[a-zA-Z_]{4,}", expected.lower()))
    final_keywords = set(re.findall(r"[a-zA-Z_]{4,}", final.lower()))

    overlap = expected_keywords & final_keywords
    union = expected_keywords | final_keywords
    jaccard = len(overlap) / len(union) if union else 0.0

    # Map jaccard to score: 0.0-0.3 = 0, 0.3-0.6 = 50, 0.6+ = 100
    if jaccard >= 0.6:
        score = 100.0
    elif jaccard >= 0.3:
        score = 50.0
    else:
        score = 0.0

    return score, {"jaccard": round(jaccard, 2), "overlap_terms": list(overlap)[:10]}


def detect_hallucination(trace: dict, goal: dict) -> tuple[bool, dict]:
    """Check if agent cited files that don't exist in the codebase."""
    final = trace["meta"].get("final_answer_preview", "")
    if not final:
        return False, {"checked": False}

    # Extract file paths from answer
    path_patterns = re.findall(r"`([^`]*(?:/|\\)[^`]+)`", final)
    project_path = goal.get("project_path", "/")

    hallucinations = []
    checked = 0
    for p in path_patterns:
        # Only check relative-looking paths
        if "/" in p or "\\" in p:
            checked += 1
            full = Path(project_path) / p.lstrip("/")
            if not full.exists():
                hallucinations.append(p)

    return bool(hallucinations), {"checked": checked, "hallucinated_paths": hallucinations[:5]}


def compute_final_score(scored: ScoredTrace) -> tuple[float, str]:
    """Compute weighted final score and grade."""
    # Token efficiency bonus: inverse of tokens per step (target < 800)
    token_bonus = max(0, 100 - (scored.token_efficiency / 800) * 100)

    # Time bonus: inverse of time to first evidence (target < 30s)
    time_bonus = max(0, 100 - (scored.time_to_first_evidence / 30) * 100)

    # Resilience: fewer stuck events = higher score
    resilience = max(0, 100 - scored.stuck_count * 25)

    score = (
        scored.exploration_score * 0.25 +
        scored.tool_efficiency * 0.15 +
        scored.synthesis_quality * 0.20 +
        scored.success_rate * 0.25 +
        token_bonus * 0.05 +
        time_bonus * 0.05 +
        resilience * 0.05
    )

    if scored.hallucination_detected:
        score -= 10.0

    # Clamp
    score = max(0.0, min(100.0, score))

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return score, grade


def generate_suggestions(scored: ScoredTrace) -> list[str]:
    """Generate improvement suggestions based on metric scores."""
    suggestions = []
    if scored.exploration_score < 70:
        suggestions.append(
            f"Exploration depth low ({scored.exploration_score:.0f}%). "
            "Agent should read more files from required surfaces before answering."
        )
    if scored.tool_efficiency < 60:
        suggestions.append(
            f"Tool efficiency low ({scored.tool_efficiency:.0f}%). "
            "Agent is making redundant or irrelevant tool calls. "
            "Use targeted Grep before Read, and avoid re-reading the same file."
        )
    if scored.synthesis_quality < 75:
        suggestions.append(
            f"Synthesis quality low ({scored.synthesis_quality:.0f}%). "
            "Final answer should cite specific files with line numbers and explain reasoning."
        )
    if scored.success_rate < 80:
        suggestions.append(
            f"Answer correctness low ({scored.success_rate:.0f}%). "
            "The answer does not match the expected understanding of the codebase."
        )
    if scored.stuck_count > 0:
        suggestions.append(
            f"Agent got stuck {scored.stuck_count} time(s). "
            "Consider adjusting prompt to encourage broader exploration when searches fail."
        )
    if scored.hallucination_detected:
        suggestions.append(
            "Hallucination detected. Agent fabricated file paths or behavior. "
            "Strengthen the prompt rule: 'Do NOT guess file paths — verify with Glob first.'"
        )
    if not suggestions:
        suggestions.append("No major issues detected. Agent performed well on this task.")
    return suggestions


# ─── Main evaluator ──────────────────────────────────────────────────────────
def evaluate_trace(trace_path: Path, goals: dict) -> ScoredTrace:
    trace = load_trace(trace_path)
    meta = trace["meta"]

    project_name = meta.get("project", "")
    goal_id = meta.get("goal_id", "")
    difficulty = meta.get("difficulty", "")

    # Find the goal definition
    goal = None
    for pname, pmeta in goals["projects"].items():
        if pname == project_name:
            for g in pmeta.get("goals", []):
                if g["id"] == goal_id:
                    goal = g
                    break

    if not goal:
        raise ValueError(f"Goal {goal_id} not found for project {project_name}")

    scored = ScoredTrace(
        run_id=meta.get("run_id", ""),
        project=project_name,
        goal_id=goal_id,
        difficulty=difficulty,
        question=goal["question"],
    )

    # Score each metric
    scored.exploration_score, scored.evidence["exploration"] = score_exploration(trace, goal)
    scored.tool_efficiency, scored.evidence["tool_efficiency"] = score_tool_efficiency(trace)
    scored.synthesis_quality, scored.evidence["synthesis"] = score_synthesis(trace)
    scored.success_rate, scored.evidence["success"] = score_success(trace, goal)
    scored.hallucination_detected, scored.evidence["hallucination"] = detect_hallucination(trace, goal)

    # Derive efficiency metrics from trace
    scored.token_efficiency = meta.get("total_tokens", 0) / max(len([s for s in trace["steps"] if s.get("role") == "assistant"]), 1)
    scored.time_to_first_evidence = 0.0  # Would need timing data in trace
    scored.stuck_count = meta.get("retries_injected", 0) + len(meta.get("stuck_events", []))

    # Retry success (simplified: if final success after retries)
    if scored.stuck_count > 0 and meta.get("success", False):
        scored.retry_success_rate = 100.0
    elif scored.stuck_count > 0:
        scored.retry_success_rate = 0.0
    else:
        scored.retry_success_rate = 100.0  # no retries needed

    scored.final_score, scored.grade = compute_final_score(scored)
    scored.improvement_suggestions = generate_suggestions(scored)

    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate benchmark traces")
    parser.add_argument("--trace", required=True, help="Trace JSONL file or glob pattern")
    parser.add_argument("--output", required=True, help="Output JSON file for results")
    args = parser.parse_args()

    goals = load_goals()
    trace_paths = list(Path.cwd().glob(args.trace)) if "*" in args.trace else [Path(args.trace)]

    if not trace_paths:
        print(f"ERROR: No traces matched {args.trace}", file=sys.stderr)
        sys.exit(1)

    results: list[dict] = []
    for tp in trace_paths:
        print(f"Evaluating {tp.name} ...")
        try:
            scored = evaluate_trace(tp, goals)
            results.append(scored.__dict__)
        except Exception as exc:
            print(f"  FAILED: {exc}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(results)} evaluation(s) to {output_path}")


if __name__ == "__main__":
    main()
