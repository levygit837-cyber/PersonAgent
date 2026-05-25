"""Tests for filesystem_tools helpers."""

from pathlib import Path

from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolPermissionResult,
)
from personagent.infrastructure.tools.filesystem_tools.helpers import (
    _deny,
    _diff,
    _diff_line_counts,
    _display_path,
    _error,
    _file_output_schema,
    _is_ignored,
    _line_count,
    _mutation_output_schema,
    _positive_int,
    _search_output_schema,
)


class TestDeny:
    def test_returns_deny_permission_result(self):
        result = _deny("Access denied")
        assert isinstance(result, ToolPermissionResult)
        assert result.behavior == ToolPermissionBehavior.DENY
        assert result.message == "Access denied"


class TestError:
    def test_returns_error_tool_result(self):
        call = ToolCall(id="call_1", name="Read", arguments={})
        result = _error(call, "Read", "File not found")
        assert result.content == "File not found"
        assert result.status == ToolExecutionStatus.ERROR
        assert result.is_error is True
        assert result.tool_name == "Read"


class TestPositiveInt:
    def test_returns_positive_integer(self):
        assert _positive_int(42, default=1) == 42

    def test_returns_default_for_none(self):
        assert _positive_int(None, default=10) == 10

    def test_returns_default_for_non_int(self):
        assert _positive_int("abc", default=10) == 10

    def test_returns_1_for_zero(self):
        assert _positive_int(0, default=10) == 1

    def test_returns_1_for_negative(self):
        assert _positive_int(-5, default=10) == 1


class TestDisplayPath:
    def test_relativizes_to_root(self):
        path = Path("/workspace/src/main.py")
        root = Path("/workspace")
        assert _display_path(path, root) == "src/main.py"

    def test_returns_full_path_when_not_relative(self):
        path = Path("/other/main.py")
        root = Path("/workspace")
        assert _display_path(path, root) == "/other/main.py"


class TestDiff:
    def test_generates_unified_diff(self):
        old = "line1\nline2\n"
        new = "line1\nmodified\n"
        result = _diff(old, new, "test.txt")
        assert "---" in result
        assert "+++" in result
        assert "-line2" in result
        assert "+modified" in result


class TestDiffLineCounts:
    def test_counts_added_and_removed(self):
        diff = "+line1\n+line2\n-line3\n context\n"
        added, removed = _diff_line_counts(diff)
        assert added == 2
        assert removed == 1


class TestLineCount:
    def test_counts_lines(self):
        assert _line_count("a\nb\nc") == 3

    def test_empty_string_is_zero(self):
        assert _line_count("") == 0


class TestIsIgnored:
    def test_ignores_git_directory(self):
        assert _is_ignored(Path("/project/.git")) is True

    def test_ignores_node_modules(self):
        assert _is_ignored(Path("/project/node_modules")) is True

    def test_does_not_ignore_src(self):
        assert _is_ignored(Path("/project/src")) is False


class TestFileOutputSchema:
    def test_has_expected_properties(self):
        schema = _file_output_schema()
        assert "content" in schema["properties"]
        assert "display_path" in schema["properties"]


class TestMutationOutputSchema:
    def test_has_expected_properties(self):
        schema = _mutation_output_schema("write")
        assert "display_path" in schema["properties"]
        assert "diff" in schema["properties"]


class TestSearchOutputSchema:
    def test_has_expected_properties(self):
        schema = _search_output_schema("grep")
        assert "path" in schema["properties"]
        assert "content" in schema["properties"]
