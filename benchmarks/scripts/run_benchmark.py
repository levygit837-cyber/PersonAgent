#!/usr/bin/env python3
"""Benchmark runner for PersonAgent exploration harness.

Usage:
    # Single goal
    python benchmarks/scripts/run_benchmark.py \\
        --project opencode --goal medium \\
        --provider deepseek --model deepseek-v4-flash

    # Full suite (all goals for all projects)
    python benchmarks/scripts/run_benchmark.py --suite full \\
        --provider deepseek --model deepseek-v4-flash

    # With custom retry policy
    python benchmarks/scripts/run_benchmark.py \\
        --project pydantic --goal hard \\
        --max-retries 3 --max-steps 25

Traces are written to benchmarks/traces/{project}_{goal}_{timestamp}.jsonl
Results are written to benchmarks/results/{run_id}_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any

import httpx
import yaml

# ─── Paths ───────────────────────────────────────────────────────────────────
BENCH_DIR = Path(__file__).parent.parent
GOALS_PATH = BENCH_DIR / "evals" / "project_goals.yaml"
METRICS_PATH = BENCH_DIR / "evals" / "metrics.yaml"
PROMPT_PATH = BENCH_DIR / "prompts" / "benchmark_agent_prompt.md"
RETRY_PROMPTS_PATH = BENCH_DIR / "prompts" / "retry_prompts.md"
TRACES_DIR = BENCH_DIR / "traces"
RESULTS_DIR = BENCH_DIR / "results"

TRACES_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Data models ──────────────────────────────────────────────────────────────
@dataclass
class BenchmarkConfig:
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    max_steps: int = 15
    max_retries: int = 2
    temperature: float = 0.2
    max_tokens: int = 4096


@dataclass
class TraceStep:
    step_number: int
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class BenchmarkTrace:
    run_id: str
    project: str
    goal_id: str
    question: str
    difficulty: str
    started_at: str
    finished_at: str | None = None
    steps: list[TraceStep] = field(default_factory=list)
    retries_injected: int = 0
    final_answer: str = ""
    total_tokens: int = 0
    total_time_s: float = 0.0
    success: bool = False
    stuck_events: list[dict[str, Any]] = field(default_factory=list)


# ─── LLM client ─────────────────────────────────────────────────────────────
class DeepSeekClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def chat(self, messages: list[dict], model: str, temperature: float, max_tokens: int) -> dict:
        t0 = time.monotonic()
        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
        )
        resp.raise_for_status()
        data = resp.json()
        latency = (time.monotonic() - t0) * 1000
        return {"data": data, "latency_ms": latency}


# ─── Prompt rendering ────────────────────────────────────────────────────────
def render_agent_prompt(goal: dict, project: dict, config: BenchmarkConfig, state: dict) -> str:
    template = PROMPT_PATH.read_text()
    return Template(template).substitute(
        workspace_path=project["path"],
        question=goal["question"],
        max_steps=config.max_steps,
        max_retries=config.max_retries,
        steps_used=state.get("steps_used", 0),
        retries_used=state.get("retries_used", 0),
        project_name=project["name"],
        difficulty=goal["difficulty"],
    )


def get_retry_prompt(retry_number: int, related_terms: str) -> str:
    raw = RETRY_PROMPTS_PATH.read_text()
    # Parse markdown sections roughly
    sections = raw.split("---")
    # retry_1 is first code block after first separator, retry_2 second, etc.
    code_blocks = [s.strip() for s in sections if "```" in s]
    if retry_number <= len(code_blocks):
        block = code_blocks[retry_number - 1]
        # Extract content between ``` and ```
        lines = block.splitlines()
        inside = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            if line.strip().startswith("```") and in_block:
                break
            if in_block:
                inside.append(line)
        prompt = "\n".join(inside)
        return prompt.replace("{related_terms}", related_terms)
    return "Please continue exploring the codebase to find more evidence."


# ─── Core benchmark logic ─────────────────────────────────────────────────────
async def run_single_goal(
    project_name: str,
    goal: dict,
    project: dict,
    config: BenchmarkConfig,
    api_key: str,
) -> BenchmarkTrace:
    run_id = f"{project_name}_{goal['id']}_{int(time.time())}"
    trace = BenchmarkTrace(
        run_id=run_id,
        project=project_name,
        goal_id=goal["id"],
        question=goal["question"],
        difficulty=goal["difficulty"],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    client = DeepSeekClient(api_key)
    state = {"steps_used": 0, "retries_used": 0}

    # System prompt (the harness we're evaluating)
    system_content = render_agent_prompt(goal, project, config, state)
    messages: list[dict] = [{"role": "system", "content": system_content}]

    trace.steps.append(TraceStep(step_number=0, role="system", content=system_content[:200] + "..."))

    while state["steps_used"] < config.max_steps:
        state["steps_used"] += 1
        step_num = state["steps_used"]

        t0 = time.monotonic()
        result = await client.chat(messages, config.model, config.temperature, config.max_tokens)
        latency = result["latency_ms"]
        data = result["data"]

        assistant_msg = data["choices"][0]["message"]
        content = assistant_msg.get("content", "")
        tool_calls = assistant_msg.get("tool_calls")

        # Estimate tokens (usage may not always be present)
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        trace.total_tokens += tokens

        trace.steps.append(TraceStep(
            step_number=step_num,
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            tokens_used=tokens,
            latency_ms=latency,
        ))

        messages.append(assistant_msg)

        # Check for substanceless response (stub detection)
        if _is_substanceless(content) and not tool_calls:
            trace.retries_injected += 1
            trace.stuck_events.append({
                "step": step_num,
                "reason": "substanceless_response",
                "content_preview": content[:80],
            })
            if trace.retries_injected <= config.max_retries:
                retry_prompt = get_retry_prompt(
                    min(trace.retries_injected, 4),
                    ", ".join(goal.get("surfaces", [])),
                )
                messages.append({"role": "user", "content": retry_prompt})
                trace.steps.append(TraceStep(step_number=step_num, role="system_retry", content=retry_prompt[:200]))
                continue
            else:
                trace.final_answer = content
                break

        # If no tool calls, the agent is done (or gave up)
        if not tool_calls:
            trace.final_answer = content
            break

        # Execute tools (simulated — in a real run we'd call actual tool functions)
        tool_results = []
        for tc in tool_calls:
            # In the real implementation, this would dispatch to actual Read/Grep/Glob/shell
            # For the benchmark scaffold, we record the tool call but simulate the result
            tool_results.append({
                "tool_call_id": tc.get("id"),
                "name": tc.get("function", {}).get("name"),
                "arguments": tc.get("function", {}).get("arguments"),
                "result": "[simulated tool result — real run would execute file read or search]",
            })

        trace.steps[-1].tool_results = tool_results
        messages.append({
            "role": "tool",
            "content": json.dumps(tool_results),
        })

    trace.finished_at = datetime.now(timezone.utc).isoformat()
    trace.total_time_s = time.monotonic() - t0 + trace.total_time_s
    trace.success = bool(trace.final_answer and len(trace.final_answer) > 50)

    return trace


def _is_substanceless(content: str | None) -> bool:
    """Mirror of PersonAgent's substanceless detection."""
    if not content:
        return True
    stripped = content.strip()
    if not stripped:
        return True
    stub_pattern = r"^(done|ok|fixed|completed|resolved|looks good|finished|confirmed)[.!?]?$"
    import re
    if re.match(stub_pattern, stripped, re.IGNORECASE):
        return True
    if len(stripped) < 30 and not any(c in stripped for c in ["/", "`", "[", "(", "{", "."]):
        return True
    return False


# ─── Persistence ─────────────────────────────────────────────────────────────
def save_trace(trace: BenchmarkTrace) -> Path:
    path = TRACES_DIR / f"{trace.run_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        # Header line with metadata
        f.write(json.dumps({
            "type": "meta",
            **asdict(trace),
            "steps": None,  # omit steps from header, write them after
        }, ensure_ascii=False) + "\n")
        for step in trace.steps:
            f.write(json.dumps({"type": "step", **asdict(step)}, ensure_ascii=False) + "\n")
    return path


def save_result(trace: BenchmarkTrace) -> Path:
    result = {
        "run_id": trace.run_id,
        "project": trace.project,
        "goal_id": trace.goal_id,
        "difficulty": trace.difficulty,
        "started_at": trace.started_at,
        "finished_at": trace.finished_at,
        "total_tokens": trace.total_tokens,
        "total_time_s": trace.total_time_s,
        "retries_injected": trace.retries_injected,
        "stuck_events": trace.stuck_events,
        "success": trace.success,
        "final_answer_preview": trace.final_answer[:500] if trace.final_answer else "",
        "step_count": len([s for s in trace.steps if s.role == "assistant"]),
    }
    path = RESULTS_DIR / f"{trace.run_id}_result.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return path


# ─── CLI ─────────────────────────────────────────────────────────────────────
def load_goals() -> dict:
    return yaml.safe_load(GOALS_PATH.read_text())


def expand_suite(projects: dict, suite: str) -> list[tuple[str, dict, dict]]:
    """Return list of (project_name, project_meta, goal) tuples."""
    items = []
    for pname, pmeta in projects.items():
        for goal in pmeta.get("goals", []):
            items.append((pname, pmeta, goal))
    return items


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run PersonAgent exploration benchmarks")
    parser.add_argument("--project", choices=["opencode", "pydantic", "personagent"], help="Project to benchmark")
    parser.add_argument("--goal", choices=["easy", "medium", "hard"], help="Difficulty level")
    parser.add_argument("--suite", choices=["full"], help="Run all goals for all projects")
    parser.add_argument("--provider", default="deepseek", choices=["deepseek", "openai"])
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: Set DEEPSEEK_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    goals_data = load_goals()
    projects = goals_data["projects"]

    config = BenchmarkConfig(
        provider=args.provider,
        model=args.model,
        max_steps=args.max_steps,
        max_retries=args.max_retries,
        temperature=args.temperature,
    )

    if args.suite == "full":
        to_run = expand_suite(projects, "full")
    else:
        if not args.project or not args.goal:
            print("ERROR: --project and --goal required, or use --suite full", file=sys.stderr)
            sys.exit(1)
        pmeta = projects.get(args.project)
        if not pmeta:
            print(f"ERROR: Unknown project {args.project}", file=sys.stderr)
            sys.exit(1)
        goal = next((g for g in pmeta["goals"] if g["difficulty"] == args.goal), None)
        if not goal:
            print(f"ERROR: No {args.goal} goal for {args.project}", file=sys.stderr)
            sys.exit(1)
        to_run = [(args.project, pmeta, goal)]

    print(f"Running {len(to_run)} benchmark(s) with {args.model}")
    for pname, pmeta, goal in to_run:
        print(f"\n  → {pname} / {goal['id']}")
        trace = await run_single_goal(pname, goal, pmeta, config, api_key)
        trace_path = save_trace(trace)
        result_path = save_result(trace)
        print(f"    Trace: {trace_path}")
        print(f"    Result: {result_path}")
        print(f"    Steps: {len([s for s in trace.steps if s.role == 'assistant'])} | "
              f"Tokens: {trace.total_tokens} | Retries: {trace.retries_injected} | "
              f"Success: {trace.success}")

    print("\nDone. Run evaluate_trace.py on the traces to compute metrics.")


if __name__ == "__main__":
    asyncio.run(main())
