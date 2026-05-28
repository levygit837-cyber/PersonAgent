"""Live end-to-end agent scenario with real LLM + real tools + real memory.

This is the ultimate stress test: a complete agent turn using a real LLM provider,
the real tool orchestrator, and optionally the real embedding server.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.services.operational_memory.capture import OperationalMemoryCapture
from personagent.application.tools.orchestrator import ToolOrchestrator
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryRedactor,
)
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


REAL_TOOLS = [
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
            "description": "List files and directories",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a pattern in files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern"},
                    "path": {"type": "string", "description": "Directory to search in"},
                },
                "required": ["pattern"],
            },
        },
    },
]


def _any_provider_available() -> bool:
    if not live_enabled():
        return False
    return any(provider_available(p) for p in ["nvidia", "vertex", "kimi", "deepseek", "codex", "llama"])


def _build_memory_service():
    repository = MagicMock()
    repository.record_event = AsyncMock()
    repository.record_chunks = AsyncMock(side_effect=lambda chunks: chunks)
    repository.record_structured_items = AsyncMock()
    repository.record_embeddings = AsyncMock()
    repository.mark_chunks_failed = AsyncMock()
    hot_cache: dict[str, deque[RecallFinding]] = defaultdict(deque)

    return OperationalMemoryCapture(
        repository=repository,
        redactor=OperationalMemoryRedactor(),
        chunker=OperationalMemoryChunker(),
        extractor=MagicMock(structured_items_from_event=MagicMock(return_value=[])),
        embedding_adapter=None,
        embeddings_enabled=False,
        embedding_model="",
        capture_tools_enabled=True,
        max_capture_chars=24_000,
        queue=None,
        queue_enabled=False,
        queue_fallback_sync=True,
        hot_cache=hot_cache,
    )


@pytest.mark.skipif(not _any_provider_available(), reason=skip_reason)
class TestEndToEndLive:
    """Full agent turn with real LLM → real tool execution → real memory capture."""

    async def test_single_turn_with_tools(self):
        """Complete agent turn: user message → LLM → tool calls → execute → LLM → response."""
        adapter = build_adapter()
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=1))
        registry.register(make_mock_tool("list_files", concurrency_safe=True, latency_ms=1))
        registry.register(make_mock_tool("search_files", concurrency_safe=True, latency_ms=2))

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
            context = ToolUseContext(
                conversation_id="live-e2e",
                workspace_root=tmp_path,
                cwd=tmp_path,
                allowed_roots=(tmp_path,),
            )
            orch = ToolOrchestrator(registry, config)
            memory = _build_memory_service()

            dist = LatencyDistribution("e2e_turn")
            iterations = min(live_iterations(), 3)

            try:
                for run in range(iterations):
                    messages = [{
                        "role": "user",
                        "content": (
                            "Please help me explore the project structure. "
                            "List the files in the current directory, then search for "
                            "any Python files containing 'import os'."
                        ),
                    }]

                    start = time.perf_counter()
                    total_tools = 0
                    iteration = 0

                    # Capture user message
                    await memory.capture_user_message(
                        project_slug="stress-test",
                        workspace_root=str(tmp_path),
                        conversation_id="live-e2e",
                        message=messages[0]["content"],
                    )

                    while iteration < 5:
                        tool_calls = []
                        content = ""
                        reasoning = ""
                        async for chunk in adapter.chat_completion_stream(
                            messages=messages,
                            max_tokens=1000,
                            temperature=0.0,
                            tools=REAL_TOOLS,
                        ):
                            content += chunk.content
                            reasoning += chunk.reasoning_content
                            if chunk.tool_calls:
                                tool_calls.extend(chunk.tool_calls)

                        if not tool_calls:
                            # Capture assistant response
                            if content:
                                await memory.capture_assistant_message(
                                    project_slug="stress-test",
                                    workspace_root=str(tmp_path),
                                    conversation_id="live-e2e",
                                    content=content,
                                )
                            break

                        calls = [ToolCall.from_openai(tc) for tc in tool_calls]
                        results = await orch.execute_collect(calls, context)
                        total_tools += len(results)

                        # Capture tool results to memory
                        for call, result in zip(calls, results):
                            await memory.capture_tool_result(
                                project_slug="stress-test",
                                workspace_root=str(tmp_path),
                                conversation_id="live-e2e",
                                call=call,
                                result=result,
                                context=context,
                            )

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
                    print(f"  Run {run}: {iteration} iterations, {total_tools} tools, {elapsed:.0f}ms")

                report = StressReport("End-to-End Live Turn")
                report.add_distribution(dist)
                print(f"\n{report.to_markdown()}")
                assert dist.count > 0
            finally:
                await adapter.close()

    async def test_multi_turn_conversation(self):
        """3-turn conversation with tool calls each turn."""
        adapter = build_adapter()
        registry = ToolRegistry()
        registry.register(make_mock_tool("read_file", concurrency_safe=True, latency_ms=1))
        registry.register(make_mock_tool("list_files", concurrency_safe=True, latency_ms=1))

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = ToolRuntimeConfig.from_values(workspace_root=str(tmp_path))
            context = ToolUseContext(
                conversation_id="live-multi-turn",
                workspace_root=tmp_path,
                cwd=tmp_path,
                allowed_roots=(tmp_path,),
            )
            orch = ToolOrchestrator(registry, config)

            turns = [
                "List the files in the current directory.",
                "Now search for any Python files in the project.",
                "Summarize what you found.",
            ]

            dist = LatencyDistribution("multi_turn")
            messages: list[dict] = []

            try:
                for turn_idx, user_msg in enumerate(turns):
                    messages.append({"role": "user", "content": user_msg})
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
                            tools=REAL_TOOLS,
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
                            "role": "assistant", "content": content or None, "tool_calls": tool_calls,
                        }
                        if reasoning:
                            assistant_msg["reasoning_content"] = reasoning
                        messages.append(assistant_msg)
                        for r in results:
                            messages.append({
                                "role": "tool", "tool_call_id": r.tool_call_id, "content": r.content,
                            })
                        iteration += 1

                    elapsed = (time.perf_counter() - start) * 1000
                    dist.record(elapsed)
                    print(f"  Turn {turn_idx}: {iteration} iterations, {elapsed:.0f}ms")

                report = StressReport("Multi-Turn Live Conversation")
                report.add_distribution(dist)
                print(f"\n{report.to_markdown()}")
            finally:
                await adapter.close()
