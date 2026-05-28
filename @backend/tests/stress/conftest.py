"""Shared fixtures for stress tests."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.domain.memory.models.operational import RecallFinding

from tests.stress.mock_embedding import MockEmbeddingAdapter
from tests.stress.mock_llm import MockLLMAdapter


# --- Mock tool factories ---


def make_mock_tool(
    name: str,
    *,
    concurrency_safe: bool = False,
    read_only: bool = False,
    latency_ms: float = 0,
    response: str = "ok",
) -> Any:
    """Create a simple mock tool for stress testing."""

    async def handler(args: dict, ctx: ToolUseContext, call: ToolCall) -> ToolResult:
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=name,
            content=response,
            data={"result": response, "tool": name},
        )

    return build_tool(
        definition=ToolDefinition(
            name=name,
            description=f"Mock {name} tool",
            input_schema={"type": "object", "properties": {}},
            is_concurrency_safe=concurrency_safe,
            is_read_only=read_only,
        ),
        handler=handler,
        is_concurrency_safe=lambda args: concurrency_safe,
        is_read_only=lambda args: read_only,
    )


# --- Fixtures ---


@pytest.fixture
def mock_llm() -> MockLLMAdapter:
    """Default mock LLM: 10ms latency, no tool calls."""
    return MockLLMAdapter(latency_ms=10)


@pytest.fixture
def mock_embedding() -> MockEmbeddingAdapter:
    """Default mock embedding: 50ms latency, 1024 dimensions."""
    return MockEmbeddingAdapter(latency_ms=50, dimensions=1024)


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Registry with 5 mock tools (2 concurrency-safe, 3 serial)."""
    registry = ToolRegistry()
    registry.register(make_mock_tool("read_file", concurrency_safe=True, read_only=True))
    registry.register(make_mock_tool("glob", concurrency_safe=True, read_only=True))
    registry.register(make_mock_tool("write_file", concurrency_safe=False))
    registry.register(make_mock_tool("shell", concurrency_safe=False))
    registry.register(make_mock_tool("edit_file", concurrency_safe=False))
    return registry


@pytest.fixture
def tool_config(tmp_path: Path) -> ToolRuntimeConfig:
    """Tool runtime config for stress tests."""
    return ToolRuntimeConfig.from_values(
        workspace_root=str(tmp_path),
        max_concurrency=4,
        max_tool_iterations=10,
    )


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolUseContext:
    """Tool execution context for stress tests."""
    return ToolUseContext(
        conversation_id="stress-test-conv",
        workspace_root=tmp_path,
        cwd=tmp_path,
        allowed_roots=(tmp_path,),
    )


def make_tool_call(name: str, call_id: str | None = None, arguments: dict | None = None) -> ToolCall:
    """Build a ToolCall for testing."""
    return ToolCall(
        id=call_id or f"call_{name}_{id(object())}",
        name=name,
        arguments=arguments or {},
    )


@pytest.fixture
def hot_cache() -> dict[str, deque[RecallFinding]]:
    """Empty hot cache for memory tests."""
    from collections import defaultdict
    return defaultdict(deque)
