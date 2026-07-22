#!/usr/bin/env python3
"""Token Trace Harness — logs real token usage per turn for 1 agent.

Usage:
    cd /home/levybonito/Documentos/PersonAgent
    python benchmarks/exploration-harness/token_trace_harness.py

This runs a single agent with full logging of:
- Token usage from API responses (input/output/total)
- Estimated context size before each API call
- Every tool call (name + args)
- Thinking events (name only, no content)
- Full conversation history size growth
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Add backend src to path
BACKEND_SRC = Path(__file__).parent.parent.parent / "@backend" / "src"
sys.path.insert(0, str(BACKEND_SRC))

from prompt_assembler import assemble_exploration_prompt, get_prompt_stats

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_MODEL = "deepseek-chat"  # Use cheaper model for trace
MAX_STEPS = 15

# ---------------------------------------------------------------------------
# Trace Logger
# ---------------------------------------------------------------------------

@dataclass
class TurnTrace:
    turn: int
    timestamp: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_context_tokens: int = 0
    message_count: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    thinking_events: list[str] = field(default_factory=list)
    notes: str = ""


class TraceLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.turns: list[TurnTrace] = []
        self.start_time = time.time()
        self._file = open(log_path, "w", encoding="utf-8")
        self._write_header()

    def _write_header(self):
        self._file.write("=" * 80 + "\n")
        self._file.write("TOKEN TRACE HARNESS\n")
        self._file.write(f"Started: {datetime.now(timezone.utc).isoformat()}\n")
        self._file.write(f"Model: {DEFAULT_MODEL}\n")
        self._file.write(f"API: {DEEPSEEK_BASE_URL}\n")
        self._file.write("=" * 80 + "\n\n")
        self._file.flush()

    def log_system_prompt(self, prompt: str, stats: dict):
        self._file.write("-" * 80 + "\n")
        self._file.write("SYSTEM PROMPT STATS\n")
        self._file.write("-" * 80 + "\n")
        self._file.write(f"Characters: {stats.get('chars', 'N/A')}\n")
        self._file.write(f"Estimated tokens: {stats.get('estimated_tokens', 'N/A')}\n")
        self._file.write(f"Lines: {stats.get('lines', 'N/A')}\n")
        self._file.write(f"Sections: {stats.get('section_count', 'N/A')}\n")
        self._file.write("\n")
        self._file.flush()

    def log_turn_start(self, turn: int, messages: list[dict], estimated_tokens: int):
        self._file.write("=" * 80 + "\n")
        self._file.write(f"TURN {turn}\n")
        self._file.write("=" * 80 + "\n")
        self._file.write(f"Timestamp: {datetime.now(timezone.utc).isoformat()}\n")
        self._file.write(f"Message count in history: {len(messages)}\n")
        self._file.write(f"Estimated context tokens: {estimated_tokens:,}\n")

        # Show breakdown
        system_msgs = [m for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        tool_msgs = [m for m in messages if m.get("role") == "tool"]

        self._file.write(f"  - System messages: {len(system_msgs)}\n")
        self._file.write(f"  - User messages: {len(user_msgs)}\n")
        self._file.write(f"  - Assistant messages: {len(assistant_msgs)}\n")
        self._file.write(f"  - Tool messages: {len(tool_msgs)}\n")

        # Show token growth
        if self.turns:
            prev = self.turns[-1].estimated_context_tokens
            growth = estimated_tokens - prev
            self._file.write(f"  - Growth from previous turn: +{growth:,} tokens\n")

        self._file.write("\n")
        self._file.flush()

    def log_api_response(self, turn: int, usage: dict, model: str):
        prompt_tok = usage.get("prompt_tokens", 0)
        comp_tok = usage.get("completion_tokens", 0)
        total_tok = usage.get("total_tokens", 0)

        self._file.write(f"API RESPONSE (model={model})\n")
        self._file.write(f"  - Prompt tokens:     {prompt_tok:>10,}\n")
        self._file.write(f"  - Completion tokens: {comp_tok:>10,}\n")
        self._file.write(f"  - Total tokens:      {total_tok:>10,}\n")
        self._file.write("\n")
        self._file.flush()

        # Create or update turn trace
        if self.turns and self.turns[-1].turn == turn:
            trace = self.turns[-1]
        else:
            trace = TurnTrace(turn=turn, timestamp=datetime.now(timezone.utc).isoformat())
            self.turns.append(trace)

        trace.prompt_tokens = prompt_tok
        trace.completion_tokens = comp_tok
        trace.total_tokens = total_tok

    def log_tool_call(self, turn: int, name: str, arguments: dict):
        self._file.write(f"TOOL CALL: {name}\n")
        self._file.write(f"  Args: {json.dumps(arguments, ensure_ascii=False, indent=4)}\n\n")
        self._file.flush()

        if self.turns and self.turns[-1].turn == turn:
            self.turns[-1].tool_calls.append({"name": name, "args": arguments})

    def log_thinking_event(self, turn: int, event_name: str):
        self._file.write(f"THINKING EVENT: {event_name}\n\n")
        self._file.flush()

        if self.turns and self.turns[-1].turn == turn:
            self.turns[-1].thinking_events.append(event_name)

    def log_tool_result(self, turn: int, name: str, result_length: int):
        self._file.write(f"TOOL RESULT: {name}\n")
        self._file.write(f"  Result length: {result_length:,} chars\n")
        self._file.write(f"  Estimated tokens: {result_length // 4:,}\n\n")
        self._file.flush()

    def log_final_summary(self):
        elapsed = time.time() - self.start_time
        total_prompt = sum(t.prompt_tokens for t in self.turns)
        total_completion = sum(t.completion_tokens for t in self.turns)
        total_all = sum(t.total_tokens for t in self.turns)
        max_context = max((t.prompt_tokens for t in self.turns), default=0)

        self._file.write("\n")
        self._file.write("=" * 80 + "\n")
        self._file.write("FINAL SUMMARY\n")
        self._file.write("=" * 80 + "\n")
        self._file.write(f"Total turns: {len(self.turns)}\n")
        self._file.write(f"Total time: {elapsed:.1f}s\n")
        self._file.write(f"\n")
        self._file.write(f"TOTAL PROMPT TOKENS:     {total_prompt:>12,}\n")
        self._file.write(f"TOTAL COMPLETION TOKENS: {total_completion:>12,}\n")
        self._file.write(f"TOTAL ALL TOKENS:        {total_all:>12,}\n")
        self._file.write(f"MAX CONTEXT SIZE:        {max_context:>12,}\n")
        self._file.write(f"\n")

        # Per-turn breakdown
        self._file.write("PER-TURN BREAKDOWN:\n")
        self._file.write(f"{'Turn':>6} {'Prompt':>10} {'Complete':>10} {'Total':>10} {'Tools':>6} {'Growth':>10}\n")
        prev_prompt = 0
        for t in self.turns:
            growth = t.prompt_tokens - prev_prompt if prev_prompt > 0 else 0
            self._file.write(
                f"{t.turn:>6} {t.prompt_tokens:>10,} {t.completion_tokens:>10,} "
                f"{t.total_tokens:>10,} {len(t.tool_calls):>6} {growth:>10,}\n"
            )
            prev_prompt = t.prompt_tokens

        self._file.write("\n")
        self._file.write("=" * 80 + "\n")
        self._file.flush()

    def close(self):
        self.log_final_summary()
        self._file.close()


# ---------------------------------------------------------------------------
# DeepSeek Client with Tracing
# ---------------------------------------------------------------------------

class TracedDeepSeekClient:
    def __init__(self, api_key: str, base_url: str, tracer: TraceLogger):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)
        self.tracer = tracer
        self.cumulative_prompt = 0
        self.cumulative_completion = 0

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
            "max_tokens": 4096,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

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

        usage = data.get("usage", {})
        self.cumulative_prompt += usage.get("prompt_tokens", 0)
        self.cumulative_completion += usage.get("completion_tokens", 0)

        return data

    def close(self) -> None:
        asyncio.create_task(self.client.aclose())


# ---------------------------------------------------------------------------
# Token Estimation
# ---------------------------------------------------------------------------

def estimate_message_tokens(message: dict) -> int:
    """Rough token estimate for a single message."""
    total = 0
    content = message.get("content", "")
    if content:
        total += len(str(content)) // 4
    if message.get("tool_calls"):
        total += len(json.dumps(message["tool_calls"])) // 4
    if message.get("tool_call_id"):
        total += len(str(message.get("content", ""))) // 4
    # Role overhead
    total += 4
    return total


def estimate_context_tokens(messages: list[dict]) -> int:
    """Estimate total tokens for all messages."""
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Tool Implementations (simplified)
# ---------------------------------------------------------------------------

def tool_read(path: str, offset: int = 1, limit: int = 50) -> str:
    target = Path(path)
    if not target.exists():
        return f"Error: File not found: {path}"
    if not target.is_file():
        return f"Error: Not a file: {path}"
    try:
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
        return f"Error: {exc}"


def tool_grep(pattern: str, path: str = ".", max_results: int = 20) -> str:
    import re as regex
    target = Path(path)
    if not target.exists():
        return f"Error: Path not found: {path}"

    results: list[str] = []
    search_root = target if target.is_dir() else target.parent
    for root, _, files in os.walk(search_root):
        for fname in files:
            fpath = Path(root) / fname
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(pattern, line):
                            rel = fpath.relative_to(search_root) if search_root != Path(".") else fpath
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= max_results:
                                break
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        if len(results) >= max_results:
            break

    if not results:
        return f"No matches for '{pattern}'"
    return "\n".join(results)


def tool_glob(pattern: str, path: str = ".", max_results: int = 30) -> str:
    import fnmatch
    target = Path(path)
    if not target.exists() or not target.is_dir():
        return f"Error: Invalid directory: {path}"

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


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "Read":
        return tool_read(
            path=arguments.get("path", ""),
            offset=arguments.get("offset", 1),
            limit=arguments.get("limit", 50),
        )
    elif name == "Grep":
        return tool_grep(
            pattern=arguments.get("pattern", ""),
            path=arguments.get("path", "."),
            max_results=arguments.get("max_results", 20),
        )
    elif name == "Glob":
        return tool_glob(
            pattern=arguments.get("pattern", ""),
            path=arguments.get("path", "."),
            max_results=arguments.get("max_results", 30),
        )
    else:
        return f"Error: Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Tool Schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a text file. Use offset/limit to read specific sections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search files for a pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files by glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["pattern"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Main Agent Loop
# ---------------------------------------------------------------------------

async def run_traced_agent(
    task: str,
    workspace: Path,
    tracer: TraceLogger,
) -> None:
    """Run one agent with full token tracing."""

    # Build system prompt
    system_prompt = assemble_exploration_prompt(
        mode="exploring",
        states=("intake", "context_discovery", "tool_execution", "finalization"),
        tools=["Read", "Grep", "Glob"],
        permission_mode="manual",
    )
    prompt_stats = get_prompt_stats(system_prompt)
    tracer.log_system_prompt(system_prompt, prompt_stats)

    # Initialize client
    client = TracedDeepSeekClient(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        tracer=tracer,
    )

    # Conversation history
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    for turn in range(1, MAX_STEPS + 1):
        # 1. Estimate context before API call
        est_tokens = estimate_context_tokens(messages)
        tracer.log_turn_start(turn, messages, est_tokens)

        # 2. API call
        try:
            data = await client.chat(
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except Exception as exc:
            tracer._file.write(f"API ERROR: {exc}\n")
            break

        # 3. Log API response
        usage = data.get("usage", {})
        model_used = data.get("model", DEFAULT_MODEL)
        tracer.log_api_response(turn, usage, model_used)

        # 4. Process response
        choice = data["choices"][0]
        assistant_msg = choice["message"]
        messages.append(assistant_msg)

        # 5. Log thinking (if any)
        if assistant_msg.get("reasoning_content"):
            tracer.log_thinking_event(turn, "reasoning_content")

        # 6. Check for tool calls
        tool_calls = assistant_msg.get("tool_calls", [])
        if not tool_calls:
            # No tool calls — agent is done
            content = assistant_msg.get("content", "")
            tracer._file.write(f"FINAL RESPONSE (turn {turn}):\n{content[:500]}...\n\n")
            break

        # 7. Execute tools and log
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            tracer.log_tool_call(turn, name, args)

            # Execute
            result = execute_tool(name, args)
            tracer.log_tool_result(turn, name, len(result))

            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    client.close()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Token Trace Harness")
    parser.add_argument(
        "--task",
        default="Explore the @backend/src/personagent/application/use_cases/chat directory and tell me how the chat completion use case works. Read at most 5 files.",
        help="Task for the agent",
    )
    parser.add_argument(
        "--workspace",
        default="/home/levybonito/Documentos/PersonAgent",
        help="Workspace directory",
    )
    parser.add_argument(
        "--output",
        default="benchmarks/exploration-harness/token_trace.log",
        help="Output log file",
    )
    args = parser.parse_args()

    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set")
        sys.exit(1)

    workspace = Path(args.workspace)
    log_path = Path(args.output)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    tracer = TraceLogger(log_path)

    print(f"Starting token trace harness...")
    print(f"Task: {args.task}")
    print(f"Workspace: {workspace}")
    print(f"Log file: {log_path}")
    print()

    await run_traced_agent(
        task=args.task,
        workspace=workspace,
        tracer=tracer,
    )

    tracer.close()

    print(f"Done! Log saved to: {log_path}")
    print()

    # Print summary from log
    with open(log_path, "r") as f:
        content = f.read()
        # Find final summary section
        if "FINAL SUMMARY" in content:
            idx = content.index("FINAL SUMMARY")
            print(content[idx:idx + 800])


if __name__ == "__main__":
    asyncio.run(main())
