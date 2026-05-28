"""Micro-benchmarks for tool result capping and structured truncation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personagent.application.tools.orchestrator._result_capping import (
    _ToolResultCappingMixin,
    DEFAULT_TOOL_RESULT_MAX_CHARS,
)
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import ToolResult, ToolExecutionStatus, ToolUseContext


class _CappingHarness(_ToolResultCappingMixin):
    """Expose capping mixin for direct testing."""

    def __init__(self, tmp_path: Path) -> None:
        self._config = ToolRuntimeConfig.from_values(
            workspace_root=str(tmp_path),
            result_max_chars=DEFAULT_TOOL_RESULT_MAX_CHARS,
        )
        from personagent.infrastructure.persistence.artifacts import LocalArtifactStorage
        self._artifact_storage = LocalArtifactStorage()


def _make_result(content: str, data: dict | None = None) -> ToolResult:
    return ToolResult(
        tool_call_id="test_call",
        tool_name="test_tool",
        content=content,
        status=ToolExecutionStatus.COMPLETED,
        data=data or {},
    )


def _make_context(tmp_path: Path) -> ToolUseContext:
    return ToolUseContext(
        conversation_id="cap-test",
        workspace_root=tmp_path,
        cwd=tmp_path,
        allowed_roots=(tmp_path,),
    )


def _build_nested_dict(depth: int, string_size: int) -> dict:
    """Build a deeply nested dict with large strings at the leaves."""
    result: dict = {"large_string": "x" * string_size}
    for _ in range(depth - 1):
        result = {"nested": result, "another_string": "y" * (string_size // 2)}
    return result


def _build_dict_with_n_strings(n: int, string_len: int = 500) -> dict:
    """Build a dict with n string values."""
    return {f"key_{i}": "v" * string_len for i in range(n)}


@pytest.mark.stress
class TestResultCappingBenchmarks:

    def test_small_result_no_op(self, benchmark, tmp_path):
        """Result under limit → should be a no-op."""
        harness = _CappingHarness(tmp_path)
        result = _make_result("small content" * 10)
        context = _make_context(tmp_path)

        capped = benchmark(lambda: harness._cap_result(result, context))
        assert capped.content == result.content

    def test_large_flat_string_truncation(self, benchmark, tmp_path):
        """Large flat string → simple truncation path."""
        harness = _CappingHarness(tmp_path)
        content = "x" * 100_000
        result = _make_result(content)
        context = _make_context(tmp_path)

        capped = benchmark(lambda: harness._cap_result(result, context))
        assert len(capped.content) <= DEFAULT_TOOL_RESULT_MAX_CHARS + 500  # allow for marker overhead
        assert "truncated" in capped.content.lower() or len(capped.content) < len(content)

    def test_structured_result_shallow(self, benchmark, tmp_path):
        """Shallow JSON with large strings → structured truncation."""
        harness = _CappingHarness(tmp_path)
        data = {"key1": "a" * 40_000, "key2": "b" * 40_000}
        result = _make_result("x" * 100_000, data=data)
        context = _make_context(tmp_path)

        capped = benchmark(lambda: harness._cap_result(result, context))
        assert len(capped.content) <= DEFAULT_TOOL_RESULT_MAX_CHARS + 500

    def test_structured_result_deep_nested(self, benchmark, tmp_path):
        """Deeply nested JSON → 20-iteration truncation loop stress."""
        harness = _CappingHarness(tmp_path)
        nested = _build_nested_dict(depth=10, string_size=10_000)
        result = _make_result(json.dumps(nested), data=nested)
        context = _make_context(tmp_path)

        capped = benchmark(lambda: harness._cap_result(result, context))
        assert len(capped.content) <= DEFAULT_TOOL_RESULT_MAX_CHARS + 500

    def test_largest_string_slot_10_items(self, benchmark, tmp_path):
        """_largest_string_slot on 10-key dict."""
        harness = _CappingHarness(tmp_path)
        data = _build_dict_with_n_strings(10, string_len=1000)

        result = benchmark(lambda: harness._largest_string_slot(data))
        assert result is not None

    def test_largest_string_slot_100_items(self, benchmark, tmp_path):
        """_largest_string_slot on 100-key dict."""
        harness = _CappingHarness(tmp_path)
        data = _build_dict_with_n_strings(100, string_len=500)

        result = benchmark(lambda: harness._largest_string_slot(data))
        assert result is not None

    def test_largest_string_slot_1000_items(self, benchmark, tmp_path):
        """_largest_string_slot on 1000-key dict."""
        harness = _CappingHarness(tmp_path)
        data = _build_dict_with_n_strings(1000, string_len=200)

        result = benchmark(lambda: harness._largest_string_slot(data))
        assert result is not None
