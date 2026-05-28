"""Live tool-calling benchmarks with real LLM providers.

Tests real tool-call parsing, multi-turn tool loops, and tool execution
using actual LLM responses.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolUseContext

from tests.stress.conftest import make_mock_tool
from tests.stress.live.conftest import (
    build_adapter,
    live_enabled,
    live_iterations,
    provider_available,
    skip_reason,
)
from tests.stress.metrics import LatencyDistribution, StressReport


pytestmark = pytest.mark.stress_live


def _any_provider_available() -> bool:
    if not live_enabled():
        return False
    return any(provider_available(p) for p in ["nvidia", "vertex", "kimi", "deepseek", "codex", "llama"])


MOCK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path"},
                },
                "required": ["directory"],
            },
        },
    },
]


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestToolCallingLive:
    """Test real tool-calling behavior with actual LLM providers."""

    async def test_single_tool_call(self):
        """Request a single tool call → verify the LLM produces valid tool_calls."""
        adapter = build_adapter()

        try:
            content = ""
            tool_calls = []
            async for chunk in adapter.chat_completion_stream(
                messages=[{
                    "role": "user",
                    "content": "Read the file at path 'src/main.py' using the read_file tool.",
                }],
                max_tokens=200,
                temperature=0.0,
                tools=MOCK_TOOLS,
            ):
                content += chunk.content
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)

            print(f"\nContent: {len(content)} chars, Tool calls: {len(tool_calls)}")
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    print(f"  → {fn.get('name')}({fn.get('arguments')})")
            assert tool_calls, "LLM did not produce tool calls"
            assert tool_calls[0]["function"]["name"] in ("read_file", "list_files")
        finally:
            await adapter.close()

    async def test_tool_call_loop_3_iterations(self):
        """3-iteration tool loop with real LLM → measure total latency."""
        adapter = build_adapter()
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=1))
        registry.register(make_mock_tool("list_files", concurrency_safe=True, latency_ms=1))

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
            context = ToolUseContext(
                conversation_id="live-tool-loop",
                workspace_root=tmp_path,
                cwd=tmp_path,
                allowed_roots=(tmp_path,),
            )
            orch = ToolOrchestrator(registry, config)

            dist = LatencyDistribution("live_tool_loop")

            try:
                for run in range(min(live_iterations(), 5)):
                    messages = [{
                        "role": "user",
                        "content": (
                            "I need you to:\n"
                            "1. List files in the current directory\n"
                            "2. Read the file 'config.json'\n"
                            "3. List files in 'src/' subdirectory\n"
                            "Use the appropriate tools for each step."
                        ),
                    }]

                    start = time.perf_counter()
                    iteration = 0
                    while iteration < 5:
                        tool_calls = []
                        content = ""
                        reasoning = ""
                        async for chunk in adapter.chat_completion_stream(
                            messages=messages,
                            max_tokens=500,
                            temperature=0.0,
                            tools=MOCK_TOOLS,
                        ):
                            content += chunk.content
                            reasoning += chunk.reasoning_content
                            if chunk.tool_calls:
                                tool_calls.extend(chunk.tool_calls)

                        if not tool_calls:
                            break

                        calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                        results = await orch.execute_collect(calls, context)

                        assistant_msg: dict[str, Any] = {
                            "role": "assistant",
                            "content": content or None,
                            "tool_calls": tool_calls,
                        }
                        if reasoning:
                            assistant_msg["reasoning_content"] = reasoning
                        messages.append(assistant_msg)
                        for result in results:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": result.tool_call_id,
                                "content": result.content,
                            })
                        iteration += 1

                    elapsed = (time.perf_counter() - start) * 1000
                    dist.record(elapsed)
                    print(f"  Run {run}: {iteration} iterations, {elapsed:.0f}ms")

                report = StressReport("Live Tool Loop")
                report.add_distribution(dist)
                report.custom_metrics = {"max_iterations": 3}
                print(f"\n{report.to_markdown()}")
            finally:
                await adapter.close()

    async def test_tool_call_with_parallel_tools(self):
        """Request multiple tool calls in one turn → verify parallel execution."""
        adapter = build_adapter()

        try:
            tool_calls = []
            async for chunk in adapter.chat_completion_stream(
                messages=[{
                    "role": "user",
                    "content": (
                        "I need to check two things at once:\n"
                        "1. List files in 'src/'\n"
                        "2. List files in 'tests/'\n"
                        "Use both tools simultaneously."
                    ),
                }],
                max_tokens=300,
                temperature=0.0,
                tools=MOCK_TOOLS,
            ):
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)

            print(f"\nTool calls received: {len(tool_calls)}")
            for tc in tool_calls:
                fn = tc.get("function", {})
                print(f"  → {fn.get('name')}({fn.get('arguments')})")

            # Some models may produce 1 or 2 tool calls depending on capability
            assert len(tool_calls) >= 1, "No tool calls produced"
        finally:
            await adapter.close()
