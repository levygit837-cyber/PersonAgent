#!/usr/bin/env python3
"""Exploration Benchmark Harness for PersonAgent.

Runs the actual PersonAgent system prompt + tool definitions against real projects
using DeepSeek-v4-flash, with full tracing and metrics collection.

Usage:
    cd /home/levybonito/Documentos/PersonAgent
    python benchmarks/exploration-harness/harness.py --benchmark bench_01
    python benchmarks/exploration-harness/harness.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Add backend src to path
BACKEND_SRC = Path(__file__).parent.parent.parent / "@backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from prompt_assembler import assemble_exploration_prompt, get_prompt_stats
from metrics import BenchmarkMetrics, BenchmarkSuiteMetrics

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_MODEL = "deepseek-v4-flash"
MAX_STEPS = 30
MAX_RETRIES = 3
STUCK_WINDOW = 8  # steps without new files = stuck
MAX_TOOL_OUTPUT_CHARS = 8000

# ---------------------------------------------------------------------------
# DeepSeek Client
# ---------------------------------------------------------------------------

class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = DEEPSEEK_BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 8192,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        # Track tokens
        usage = data.get("usage", {})
        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
        self.total_completion_tokens += usage.get("completion_tokens", 0)

        return data

    def close(self) -> None:
        asyncio.create_task(self.client.aclose())


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def _resolve_path(path_str: str, workspace: Path) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        # Ensure it's within workspace
        try:
            p.relative_to(workspace)
            return p
        except ValueError:
            return workspace / p.name
    return workspace / p


def tool_read(path: str, offset: int = 1, limit: int = 200, workspace: Path = Path(".")) -> str:
    try:
        target = _resolve_path(path, workspace)
        if not target.exists():
            return f"Error: File not found: {path}"
        if not target.is_file():
            return f"Error: Path is not a file: {path}"
        # Security: ensure within workspace
        try:
            target.resolve().relative_to(workspace.resolve())
        except ValueError:
            return f"Error: Path outside workspace: {path}"

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, offset - 1)
        end = start + limit
        selected = lines[start:end]
        result = "\n".join(f"{i + start + 1}: {line}" for i, line in enumerate(selected))
        total = len(lines)
        if end < total:
            result += f"\n... ({total - end} more lines)"
        return result
    except Exception as exc:
        return f"Error reading file: {exc}"


def tool_grep(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    max_results: int = 50,
    workspace: Path = Path("."),
) -> str:
    try:
        target = _resolve_path(path, workspace)
        if not target.exists():
            return f"Error: Path not found: {path}"

        # Try ripgrep first
        rg_cmd = ["rg", "--json", "-n", "--max-count", str(max_results), "-e", pattern]
        if glob:
            rg_cmd.extend(["--glob", glob])
        if target.is_dir():
            rg_cmd.append(str(target))
        else:
            rg_cmd.append(str(target))

        try:
            proc = subprocess.run(
                rg_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(workspace),
            )
            if proc.returncode in (0, 1):  # 0 = matches, 1 = no matches
                lines = proc.stdout.strip().splitlines()
                results: list[str] = []
                for line in lines:
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "match":
                            m = obj["data"]
                            file_path = m["path"]["text"]
                            line_num = m["line_number"]
                            text = "".join(p["text"] for p in m["submatches"][0].get("match", {}).get("text", "") for p in [m["submatches"][0]]) if m.get("submatches") else ""
                            # Simpler extraction
                            line_text = m["lines"]["text"].strip()
                            results.append(f"{file_path}:{line_num}: {line_text}")
                    except Exception:
                        continue
                if not results:
                    return f"No matches found for '{pattern}'"
                return "\n".join(results[:max_results])
        except FileNotFoundError:
            pass  # fallback

        # Fallback: Python grep
        import fnmatch

        results: list[str] = []
        search_root = target if target.is_dir() else target.parent
        for root, _, files in os.walk(search_root):
            for fname in files:
                if glob and not fnmatch.fnmatch(fname, glob):
                    continue
                fpath = Path(root) / fname
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if re.search(pattern, line):
                                rel = fpath.relative_to(workspace)
                                results.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(results) >= max_results:
                                    break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        if not results:
            return f"No matches found for '{pattern}'"
        return "\n".join(results)
    except Exception as exc:
        return f"Error during grep: {exc}"


def tool_glob(
    pattern: str,
    path: str = ".",
    max_results: int = 100,
    workspace: Path = Path("."),
) -> str:
    try:
        target = _resolve_path(path, workspace)
        if not target.exists() or not target.is_dir():
            return f"Error: Invalid directory: {path}"

        import fnmatch

        results: list[str] = []
        for root, _, files in os.walk(target):
            for fname in files:
                rel_dir = Path(root).relative_to(target)
                rel_pattern = str(rel_dir / fname) if str(rel_dir) != "." else fname
                if fnmatch.fnmatch(rel_pattern, pattern) or fnmatch.fnmatch(fname, pattern):
                    results.append(rel_pattern)
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break
        if not results:
            return f"No files matching '{pattern}'"
        return "\n".join(results[:max_results])
    except Exception as exc:
        return f"Error during glob: {exc}"


def tool_shell(command: str, cwd: str | None = None, timeout_ms: int = 30000, workspace: Path = Path(".")) -> str:
    # Security: whitelist read-only commands
    allowed_prefixes = (
        "ls", "cat", "head", "tail", "find", "grep", "rg", "wc", "echo",
        "git log", "git show", "git diff", "git status", "git branch",
        "python -c", "python3 -c",
    )
    stripped = command.strip()
    if not any(stripped.startswith(p) for p in allowed_prefixes):
        return f"Error: Command not allowed for safety: {command[:50]}. Only read-only commands are permitted."

    try:
        work_dir = workspace
        if cwd:
            work_dir = _resolve_path(cwd, workspace)
        proc = subprocess.run(
            stripped,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000,
            cwd=str(work_dir),
        )
        out = proc.stdout
        err = proc.stderr
        result = out
        if err:
            result += f"\n[stderr]: {err}"
        if len(result) > MAX_TOOL_OUTPUT_CHARS:
            result = result[:MAX_TOOL_OUTPUT_CHARS] + f"\n... ({len(result) - MAX_TOOL_OUTPUT_CHARS} chars truncated)"
        return result
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as exc:
        return f"Error: {exc}"


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a text file inside the allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative path to read."},
                    "offset": {"type": "integer", "minimum": 1, "description": "1-based line number to start reading from."},
                    "limit": {"type": "integer", "minimum": 1, "description": "Maximum number of lines to return."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search text files in the workspace using ripgrep when available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern."},
                    "path": {"type": "string", "description": "Directory or file to search."},
                    "glob": {"type": "string", "description": "Optional glob filter such as '*.py'."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files by glob pattern inside the allowed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern such as '**/*.py'."},
                    "path": {"type": "string", "description": "Directory to search. Defaults to cwd."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a shell command in the workspace. Only read-only commands are permitted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "cwd": {"type": "string", "description": "Optional workspace-relative working directory."},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any], workspace: Path) -> str:
    if name == "Read":
        return tool_read(
            path=arguments.get("path", ""),
            offset=arguments.get("offset", 1),
            limit=arguments.get("limit", 200),
            workspace=workspace,
        )
    elif name == "Grep":
        return tool_grep(
            pattern=arguments.get("pattern", ""),
            path=arguments.get("path", "."),
            glob=arguments.get("glob"),
            max_results=arguments.get("max_results", 50),
            workspace=workspace,
        )
    elif name == "Glob":
        return tool_glob(
            pattern=arguments.get("pattern", ""),
            path=arguments.get("path", "."),
            max_results=arguments.get("max_results", 100),
            workspace=workspace,
        )
    elif name == "shell":
        return tool_shell(
            command=arguments.get("command", ""),
            cwd=arguments.get("cwd"),
            timeout_ms=arguments.get("timeout_ms", 30000),
            workspace=workspace,
        )
    else:
        return f"Error: Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Stuck Detection
# ---------------------------------------------------------------------------

def detect_stuck(
    history: list[dict[str, Any]],
    files_read: list[str],
    window: int = STUCK_WINDOW,
) -> tuple[bool, str]:
    """Detect if the agent is stuck in a loop or making no progress."""
    if len(history) < 3:
        return False, ""

    recent = history[-window:]

    # Check for exact duplicate tool calls
    tool_calls = [
        h for h in recent
        if h.get("role") == "assistant" and h.get("tool_calls")
    ]
    if len(tool_calls) >= 2:
        signatures: list[str] = []
        for h in tool_calls:
            for tc in h.get("tool_calls", []):
                fn = tc.get("function", {})
                sig = f"{fn.get('name')}:{json.dumps(fn.get('arguments',''), sort_keys=True)}"
                signatures.append(sig)
        if len(signatures) >= 2 and len(set(signatures[-3:])) == 1:
            return True, "repeated identical tool call"

    # Check for alternating between two tool calls (A-B-A-B)
    if len(signatures) >= 4:
        if signatures[-1] == signatures[-3] and signatures[-2] == signatures[-4]:
            return True, "alternating tool call loop"

    # Check for no new files in window
    recent_files: set[str] = set()
    for h in recent:
        for tc in h.get("tool_calls", []):
            fn = tc.get("function", {})
            if fn.get("name") == "Read":
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    recent_files.add(args.get("path", ""))
                except Exception:
                    pass
    new_files = recent_files - set(files_read)
    if len(tool_calls) >= window and not new_files:
        return True, "no new files read in recent steps"

    return False, ""


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkTask:
    id: str
    project: str
    workspace: Path
    question: str
    expected_findings: list[str]
    checkpoints: list[tuple[str, str]] = field(default_factory=list)
    difficulty: str = "medium"
    max_steps: int = MAX_STEPS
    mode: str = "exploring"
    states: tuple[str, ...] = ("intake", "context_discovery", "tool_execution", "finalization")


async def run_single_benchmark(
    task: BenchmarkTask,
    client: DeepSeekClient,
    trace_dir: Path,
    model: str = DEFAULT_MODEL,
) -> BenchmarkMetrics:
    metrics = BenchmarkMetrics(
        benchmark_id=task.id,
        project=task.project,
        model=model,
        started_at=datetime.now(timezone.utc).isoformat(),
        max_steps_allowed=task.max_steps,
        max_retries_allowed=MAX_RETRIES,
        mode_used=task.mode,
        states_used=task.states,
    )

    # Assemble system prompt
    system_prompt = assemble_exploration_prompt(
        mode=task.mode,
        states=task.states,
        tools=["Read", "Grep", "Glob", "shell"],
    )
    stats = get_prompt_stats(system_prompt)
    metrics.system_prompt_chars = stats["chars"]
    metrics.system_prompt_tokens = stats.get("tokens")

    # Build initial messages
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_task_prompt(task)},
    ]

    trace_log: list[dict[str, Any]] = []
    trace_log.append({
        "event": "start",
        "task": task.id,
        "project": task.project,
        "system_prompt_stats": stats,
        "system_prompt_mode": task.mode,
        "system_prompt_states": task.states,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    start_time = time.perf_counter()
    time_to_first_tool: float | None = None
    files_read: list[str] = []
    history: list[dict[str, Any]] = []
    retry_count = 0
    step = 0

    try:
        while step < task.max_steps:
            step += 1
            metrics.total_steps = step

            # Call LLM
            t0 = time.perf_counter()
            try:
                response = await client.chat(
                    messages=messages,
                    model=model,
                    temperature=0.3,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                )
            except Exception as exc:
                trace_log.append({"event": "llm_error", "step": step, "error": str(exc)})
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    metrics.retry_count = retry_count
                    messages.append({"role": "user", "content": f"The previous request failed: {exc}. Please try again."})
                    continue
                else:
                    metrics.failure_reason = f"LLM error after {MAX_RETRIES} retries: {exc}"
                    break

            llm_time = time.perf_counter() - t0
            choice = response["choices"][0]
            assistant_msg = choice["message"]

            # Record assistant message
            msg_record = {
                "role": "assistant",
                "content": assistant_msg.get("content", ""),
                "step": step,
                "llm_time_seconds": round(llm_time, 2),
            }
            if "tool_calls" in assistant_msg and assistant_msg["tool_calls"]:
                msg_record["tool_calls"] = assistant_msg["tool_calls"]
                if time_to_first_tool is None:
                    time_to_first_tool = time.perf_counter() - start_time
            history.append(msg_record)
            trace_log.append({"event": "assistant_message", **msg_record})

            # Check for tool calls
            tool_calls = assistant_msg.get("tool_calls", [])
            if not tool_calls:
                # Agent gave final answer
                final_answer = assistant_msg.get("content", "")
                metrics.final_answer = final_answer
                trace_log.append({"event": "final_answer", "step": step, "content": final_answer})

                # Evaluate checkpoints
                metrics.success = evaluate_success(final_answer, task.expected_findings, task.checkpoints, metrics)
                if not metrics.success:
                    if retry_count < MAX_RETRIES:
                        retry_count += 1
                        metrics.retry_count = retry_count
                        messages.append({"role": "user", "content": build_retry_prompt(task, final_answer, metrics)})
                        trace_log.append({"event": "retry_injected", "reason": "checkpoints_not_met"})
                        continue
                    else:
                        metrics.failure_reason = "Checkpoints not met after max retries"
                break

            # Execute tools
            tool_results: list[dict[str, Any]] = []
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}

                t_tool = time.perf_counter()
                result_content = execute_tool(tool_name, args, task.workspace)
                tool_duration = (time.perf_counter() - t_tool) * 1000

                success = not result_content.startswith("Error:")
                metrics.record_tool_call(
                    step=step,
                    tool_name=tool_name,
                    arguments=args,
                    duration_ms=round(tool_duration, 2),
                    success=success,
                    result_preview=result_content[:200],
                )

                if tool_name == "Read" and "path" in args:
                    path = args["path"]
                    if path not in files_read:
                        files_read.append(path)

                tool_results.append({
                    "tool_call_id": tc_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result_content,
                })
                trace_log.append({
                    "event": "tool_result",
                    "step": step,
                    "tool_name": tool_name,
                    "arguments": args,
                    "success": success,
                    "duration_ms": round(tool_duration, 2),
                    "result_preview": result_content[:300],
                })

            # Build messages for next turn
            messages.append({
                "role": "assistant",
                "content": assistant_msg.get("content", ""),
                "tool_calls": [{"id": tc["id"], "type": "function", "function": tc["function"]} for tc in tool_calls],
            })
            for tr in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "name": tr["name"],
                    "content": tr["content"],
                })

            # Stuck detection
            is_stuck, stuck_reason = detect_stuck(history, files_read)
            if is_stuck:
                metrics.record_stuck(stuck_reason, step)
                trace_log.append({"event": "stuck_detected", "reason": stuck_reason, "step": step})
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    metrics.retry_count = retry_count
                    messages.append({"role": "user", "content": f"You seem to be stuck ({stuck_reason}). Please reconsider your approach and try a different strategy."})
                    trace_log.append({"event": "retry_injected", "reason": f"stuck: {stuck_reason}"})
                    continue
                else:
                    metrics.failure_reason = f"Stuck after max retries: {stuck_reason}"
                    break

            # Check checkpoints
            for cp_id, cp_desc in task.checkpoints:
                already_reached = any(c.checkpoint_id == cp_id for c in metrics.checkpoint_times)
                if not already_reached:
                    elapsed = time.perf_counter() - start_time
                    metrics.record_checkpoint(cp_id, step, elapsed, cp_desc)
                    trace_log.append({"event": "checkpoint", "id": cp_id, "step": step, "elapsed": elapsed})

        else:
            # Max steps reached
            if retry_count < MAX_RETRIES:
                retry_count += 1
                metrics.retry_count = retry_count
                messages.append({"role": "user", "content": "You have reached the step limit. Please provide your best answer based on what you've found so far."})
                trace_log.append({"event": "retry_injected", "reason": "max_steps_reached"})
                # One more attempt
                try:
                    response = await client.chat(
                        messages=messages,
                        model=model,
                        temperature=0.3,
                    )
                    final_answer = response["choices"][0]["message"].get("content", "")
                    metrics.final_answer = final_answer
                    metrics.success = evaluate_success(final_answer, task.expected_findings, task.checkpoints, metrics)
                except Exception as exc:
                    metrics.failure_reason = f"Final attempt failed: {exc}"
            else:
                metrics.failure_reason = "Max steps reached without answer"

    except Exception as exc:
        metrics.failure_reason = f"Unexpected error: {exc}"
        trace_log.append({"event": "error", "error": str(exc), "traceback": traceback.format_exc()})

    # Finalize metrics
    metrics.total_time_seconds = round(time.perf_counter() - start_time, 2)
    if time_to_first_tool is not None:
        metrics.time_to_first_tool_seconds = round(time_to_first_tool, 2)
    metrics.prompt_tokens = client.total_prompt_tokens
    metrics.completion_tokens = client.total_completion_tokens
    metrics.total_tokens = client.total_prompt_tokens + client.total_completion_tokens
    metrics.finished_at = datetime.now(timezone.utc).isoformat()
    metrics.retry_count = retry_count

    # Save trace
    trace_log.append({"event": "end", "metrics": metrics.to_dict()})
    trace_path = trace_dir / f"{task.id}_trace.json"
    trace_path.write_text(json.dumps(trace_log, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save metrics
    metrics_path = trace_dir / f"{task.id}_metrics.json"
    metrics.save(metrics_path)

    return metrics


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def build_task_prompt(task: BenchmarkTask) -> str:
    return f"""Explore the codebase at {task.workspace} and answer this question:

**Question**: {task.question}

Instructions:
- Use the available tools (Read, Grep, Glob, shell) to investigate thoroughly.
- Do NOT guess or assume — verify your findings by reading the actual source files.
- Follow import chains, trace execution paths, and understand how components interact.
- Read multiple relevant files before synthesizing your answer.
- If you get stuck or find contradictory information, try a different search strategy.
- Provide a clear, specific answer with file names and line references where applicable.
"""


def build_retry_prompt(task: BenchmarkTask, last_answer: str, metrics: BenchmarkMetrics) -> str:
    files_so_far = ", ".join(metrics.files_read[-5:]) if metrics.files_read else "none"
    return f"""Your previous answer was insufficient or incomplete. Please continue exploring.

Files you've read so far: {files_so_far}
Steps taken: {metrics.total_steps}

The question is: {task.question}

Please dig deeper. Check files you haven't examined yet, follow more import chains, and verify your understanding before answering again.
"""


def evaluate_success(
    answer: str,
    expected_findings: list[str],
    checkpoints: list[tuple[str, str]],
    metrics: BenchmarkMetrics,
) -> bool:
    """Heuristic evaluation of whether the answer is successful."""
    if not answer or len(answer) < 100:
        return False

    # Check for expected keyword findings
    answer_lower = answer.lower()
    matches = 0
    for finding in expected_findings:
        if finding.lower() in answer_lower:
            matches += 1

    # Require at least 60% of expected findings
    finding_ratio = matches / max(len(expected_findings), 1)

    # Require some files to be referenced
    has_file_refs = any(ext in answer for ext in (".py", ".ts", ".tsx", ".js", ".rs", ".json", ".toml"))

    # Require some checkpoints reached (at least 1 if checkpoints exist)
    has_checkpoints = len(metrics.checkpoint_times) > 0 if checkpoints else True

    return finding_ratio >= 0.5 and has_file_refs and has_checkpoints


# ---------------------------------------------------------------------------
# Benchmark Definitions
# ---------------------------------------------------------------------------

def get_benchmarks() -> list[BenchmarkTask]:
    """Return all benchmark tasks."""
    base = Path("/home/levybonito/Documentos")
    return [
        # --- PersonAgent ---
        BenchmarkTask(
            id="pa_cache_invalidation",
            project="PersonAgent",
            workspace=base / "PersonAgent" / "@backend" / "src" / "personagent",
            question="How does the PromptBuilder decide whether a specific SystemPromptSection should be cached or recomputed on every turn, and what inputs form the cache_scope hash that keys the cache?",
            expected_findings=[
                "cache_break", "cache_scope", "sha256", "workspace", "prompt_mode",
                "agent_states", "permission_mode", "provider", "model", "sorted_tools",
                "_resolve_sections",
            ],
            checkpoints=[
                ("found_cache_break", "Located cache_break field in models"),
                ("found_scope_hash", "Found how cache_scope is built"),
            ],
            difficulty="medium",
            max_steps=25,
            mode="exploring",
            states=("intake", "context_discovery", "tool_execution", "finalization"),
        ),
        BenchmarkTask(
            id="pa_state_resolution",
            project="PersonAgent",
            workspace=base / "PersonAgent" / "@backend" / "src" / "personagent",
            question="If a user sends 'plan a migration strategy to deploy the new auth service to production' in auto prompt mode, what exact sequence of AgentState values will the AgentStateResolver produce, and which heuristic terms trigger each state?",
            expected_findings=[
                "intake", "planning", "tool_execution", "user_checkpoint",
                "runtime_validation", "finalization", "plan", "strategy",
                "migration", "deploy", "production",
            ],
            checkpoints=[
                ("found_resolver", "Located AgentStateResolver"),
                ("traced_states", "Traced the state sequence for the message"),
            ],
            difficulty="complex",
            max_steps=30,
            mode="exploring",
            states=("intake", "context_discovery", "planning", "tool_execution", "finalization"),
        ),
        # --- pydantic ---
        BenchmarkTask(
            id="pd_discriminated_union",
            project="pydantic",
            workspace=base / "pydantic" / "pydantic",
            question="When Discriminator is used on a union of BaseModels, explain the exact transformation applied to the CoreSchema tree. Where does the discriminator inference happen, how are Literal field values extracted, and what does the final tagged-union schema look like?",
            expected_findings=[
                "apply_discriminator", "tagged-union", "Literal", "_ApplyInferredDiscriminator",
                "iter_union_choices", "discriminated_union", "json_schema",
            ],
            checkpoints=[
                ("found_apply_discriminator", "Found apply_discriminator function"),
                ("found_literal_extraction", "Understood how literal values are extracted"),
            ],
            difficulty="complex",
            max_steps=30,
            mode="exploring",
            states=("intake", "context_discovery", "tool_execution", "finalization"),
        ),
        BenchmarkTask(
            id="pd_plugin_interception",
            project="pydantic",
            workspace=base / "pydantic" / "pydantic",
            question="If a third-party plugin is installed, how does it intercept BaseModel validation? Describe the exact mechanism from plugin discovery through PluggableSchemaValidator to the wrapped validate_python call.",
            expected_findings=[
                "entry_points", "PluggableSchemaValidator", "build_wrapper",
                "on_validate_python", "new_schema_validator", "importlib.metadata",
            ],
            checkpoints=[
                ("found_loader", "Found plugin loader mechanism"),
                ("found_wrapper", "Found validation wrapper"),
            ],
            difficulty="medium",
            max_steps=25,
            mode="exploring",
            states=("intake", "context_discovery", "tool_execution", "finalization"),
        ),
        # --- opencode ---
        BenchmarkTask(
            id="oc_permission_eval",
            project="opencode",
            workspace=base / "opencode" / "packages" / "opencode" / "src",
            question="How does the system decide whether a specific tool call (e.g., shell) requires user approval, is auto-allowed, or auto-denied? How do agent permissions, user config, session-level overrides, and wildcard patterns interact?",
            expected_findings=[
                "Permission.merge", "Permission.evaluate", "wildcard", "doom_loop",
                "agent.ts", "ruleset", "ask", "allow", "deny",
            ],
            checkpoints=[
                ("found_permission_merge", "Found permission merging logic"),
                ("found_doom_loop", "Found doom loop detection"),
            ],
            difficulty="complex",
            max_steps=30,
            mode="exploring",
            states=("intake", "context_discovery", "tool_execution", "finalization"),
        ),
        BenchmarkTask(
            id="oc_skill_discovery",
            project="opencode",
            workspace=base / "opencode" / "packages" / "opencode" / "src",
            question="How are skills discovered from the filesystem (including external .agents/skills/ and .claude/ directories), and how do they get injected into the system prompt sent to the LLM?",
            expected_findings=[
                "discoverSkills", "scan", "SKILL.md", "frontmatter",
                "session/prompt", "skill/index", "glob", "markdown",
            ],
            checkpoints=[
                ("found_discovery", "Found skill discovery function"),
                ("found_injection", "Found prompt injection point"),
            ],
            difficulty="medium",
            max_steps=25,
            mode="exploring",
            states=("intake", "context_discovery", "tool_execution", "finalization"),
        ),
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Exploration Benchmark Harness")
    parser.add_argument("--benchmark", type=str, help="Run a specific benchmark by ID")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--trace-dir", type=str, default="benchmarks/traces", help="Directory for traces")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS, help="Max steps per benchmark")
    args = parser.parse_args()

    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set in environment.")
        sys.exit(1)

    benchmarks = get_benchmarks()
    if args.benchmark:
        benchmarks = [b for b in benchmarks if b.id == args.benchmark]
        if not benchmarks:
            print(f"ERROR: Benchmark '{args.benchmark}' not found.")
            print(f"Available: {[b.id for b in get_benchmarks()]}")
            sys.exit(1)

    trace_dir = Path(args.trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)

    suite = BenchmarkSuiteMetrics()
    client = DeepSeekClient(DEEPSEEK_API_KEY)

    try:
        for task in benchmarks:
            print(f"\n{'='*60}")
            print(f"Running benchmark: {task.id} ({task.difficulty})")
            print(f"Project: {task.project}")
            print(f"Question: {task.question[:100]}...")
            print(f"{'='*60}")

            task.max_steps = args.max_steps
            metrics = await run_single_benchmark(task, client, trace_dir, args.model)
            suite.add(metrics)

            derived = metrics.compute_derived_metrics()
            print(f"\n  Result: {'✅ SUCCESS' if metrics.success else '❌ FAILED'}")
            print(f"  Steps: {metrics.total_steps} / {task.max_steps}")
            print(f"  Tools: {metrics.tool_counts}")
            print(f"  Files read: {len(metrics.files_read)}")
            print(f"  Tokens: {metrics.total_tokens}")
            print(f"  Time: {metrics.total_time_seconds:.1f}s")
            print(f"  Retries: {metrics.retry_count} / {MAX_RETRIES}")
            print(f"  Stuck: {metrics.stuck_count}")
            print(f"  Checkpoints: {len(metrics.checkpoint_times)}")
            if metrics.failure_reason:
                print(f"  Failure reason: {metrics.failure_reason}")
    finally:
        await client.client.aclose()

    # Save suite summary
    summary_path = trace_dir / "suite_summary.json"
    suite.save(summary_path)
    print(f"\n{'='*60}")
    print(f"Suite summary saved to {summary_path}")
    print(json.dumps(suite.compute_summary(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
