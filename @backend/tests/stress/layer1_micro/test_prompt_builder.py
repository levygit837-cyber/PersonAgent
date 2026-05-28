"""Micro-benchmarks for prompt building and message preparation.

Tests the PromptPackageBuilder and MessagePreparer components that run
before every LLM call. These are on the critical path for pre-streaming latency.
"""

from __future__ import annotations

import pytest

from personagent.application.tools.schema_cache import ToolSchemaCache
from personagent.application.tools.registry import ToolRegistry
from personagent.domain.tools import ToolDefinition, build_tool

from tests.stress.conftest import make_mock_tool


def _make_messages(n: int) -> list[dict]:
    """Build n mock conversation messages."""
    messages = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({
            "role": role,
            "content": f"{'User' if role == 'user' else 'Assistant'} message {i}: "
                       + "x " * 50,
        })
    return messages


@pytest.mark.stress
class TestPromptBuildingBenchmarks:

    def test_schema_generation_10_tools(self, benchmark):
        """Generate OpenAI schemas for 10 tools — baseline."""
        registry = ToolRegistry()
        for i in range(10):
            registry.register(make_mock_tool(f"tool_{i}"))

        result = benchmark(lambda: registry.openai_schemas(cache_scope="bench"))
        assert len(result) == 10

    def test_schema_generation_30_tools(self, benchmark):
        """Generate OpenAI schemas for 30 tools — realistic load."""
        registry = ToolRegistry()
        for i in range(30):
            registry.register(make_mock_tool(f"tool_{i}"))

        result = benchmark(lambda: registry.openai_schemas(cache_scope="bench"))
        assert len(result) == 30

    def test_registry_list_enabled_50_tools(self, benchmark):
        """List enabled tools from a 50-tool registry."""
        registry = ToolRegistry()
        for i in range(50):
            registry.register(make_mock_tool(f"tool_{i}"))

        result = benchmark(lambda: registry.list_enabled())
        assert len(result) == 50

    def test_registry_search(self, benchmark):
        """Search across 50 tools by keyword."""
        registry = ToolRegistry()
        for i in range(50):
            registry.register(make_mock_tool(f"tool_{i}"))

        result = benchmark(lambda: registry.search("tool_2", limit=5))
        assert len(result) >= 1


@pytest.mark.stress
class TestMessageSerializationBenchmarks:

    def test_serialize_10_messages(self, benchmark):
        """Serialize 10 messages to JSON — baseline."""
        import json

        messages = _make_messages(10)
        result = benchmark(lambda: json.dumps(messages, ensure_ascii=False))
        assert len(result) > 0

    def test_serialize_200_messages(self, benchmark):
        """Serialize 200 messages — approaching context limit."""
        import json

        messages = _make_messages(200)
        result = benchmark(lambda: json.dumps(messages, ensure_ascii=False))
        assert len(result) > 0

    def test_serialize_500_messages_with_tool_calls(self, benchmark):
        """Serialize 500 messages including tool call/result pairs."""
        import json

        messages = []
        for i in range(250):
            messages.append({"role": "user", "content": f"User message {i}: " + "x " * 20})
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "src/main.py"}'},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": "File content here. " * 20,
            })

        result = benchmark(lambda: json.dumps(messages, ensure_ascii=False))
        assert len(result) > 0
