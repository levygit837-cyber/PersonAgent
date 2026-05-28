"""Micro-benchmarks for tool definition serialization and OpenAI format conversion."""

from __future__ import annotations

import json

import pytest

from personagent.domain.tools import ToolDefinition


def _make_definition(n: int, *, with_examples: bool = False) -> ToolDefinition:
    """Build a ToolDefinition with realistic schema complexity."""
    properties = {}
    required = []
    for i in range(n):
        prop_name = f"param_{i}"
        properties[prop_name] = {
            "type": "string" if i % 2 == 0 else "integer",
            "description": f"Parameter {i} description with detailed explanation of usage",
        }
        if i < n // 2:
            required.append(prop_name)

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

    return ToolDefinition(
        name="complex_tool",
        description="A complex tool with many parameters for benchmarking schema serialization",
        input_schema=schema,
        examples=tuple(f"example_{i}" for i in range(5)) if with_examples else (),
    )


@pytest.mark.stress
class TestToolDefinitionBenchmarks:

    def test_to_openai_tool_5_params(self, benchmark):
        """Convert 5-param definition to OpenAI format."""
        defn = _make_definition(5)
        result = benchmark(lambda: defn.to_openai_tool())
        assert result["type"] == "function"

    def test_to_openai_tool_20_params(self, benchmark):
        """Convert 20-param definition to OpenAI format."""
        defn = _make_definition(20)
        result = benchmark(lambda: defn.to_openai_tool())
        assert result["type"] == "function"

    def test_to_discovery_dict(self, benchmark):
        """Convert definition to discovery dict."""
        defn = _make_definition(10, with_examples=True)
        result = benchmark(lambda: defn.to_discovery_dict())
        assert "name" in result

    def test_json_dump_openai_tool(self, benchmark):
        """Full JSON serialization of OpenAI tool schema."""
        defn = _make_definition(15)
        tool = defn.to_openai_tool()
        result = benchmark(lambda: json.dumps(tool, ensure_ascii=False))
        assert len(result) > 0
