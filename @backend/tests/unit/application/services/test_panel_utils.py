"""Unit tests for panel_utils helpers."""

from __future__ import annotations

from personagent.application.services.session.panel_utils import (
    _add,
    _compact_memory_label,
    _diff_stats,
    _estimate_tokens,
    _file_line_count,
    _first_int,
    _first_int_with_key,
    _memory_entry_add,
    _memory_trace,
    _memory_trace_items,
    _metric,
    _optional_int,
    _safe_int,
    _source_from_record,
    _sources_from_tool_data,
    _tool_data,
)
from personagent.domain.conversation.models import Message, Role


class TestMetric:
    def test_default_values(self):
        m = _metric()
        assert m == {"value": 0, "estimated": False}

    def test_custom_values(self):
        m = _metric(value=42, estimated=True)
        assert m == {"value": 42, "estimated": True}


class TestAdd:
    def test_adds_value(self):
        m = _metric()
        _add(m, 5)
        assert m["value"] == 5

    def test_adds_multiple_times(self):
        m = _metric()
        _add(m, 3)
        _add(m, 2)
        assert m["value"] == 5

    def test_negative_value_clamped_to_zero(self):
        m = _metric(value=10)
        _add(m, -5)
        assert m["value"] == 10

    def test_sets_estimated_flag(self):
        m = _metric()
        _add(m, 1, estimated=True)
        assert m["estimated"] is True

    def test_estimated_flag_persists(self):
        m = _metric()
        _add(m, 1)
        assert m["estimated"] is False
        _add(m, 1, estimated=True)
        assert m["estimated"] is True


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_short_text(self):
        assert _estimate_tokens("hi") == 1

    def test_exact_divisor(self):
        assert _estimate_tokens("abcd") == 1

    def test_over_divisor(self):
        assert _estimate_tokens("abcde") == 2


class TestFirstInt:
    def test_finds_first_key(self):
        assert _first_int({"a": 1, "b": 2}, ("a", "b")) == 1

    def test_skips_none(self):
        assert _first_int({"a": None, "b": 2}, ("a", "b")) == 2

    def test_returns_none_when_missing(self):
        assert _first_int({}, ("a",)) is None


class TestFirstIntWithKey:
    def test_returns_key(self):
        value, key = _first_int_with_key({"a": 1}, ("a",))
        assert value == 1
        assert key == "a"

    def test_returns_none_none_when_missing(self):
        assert _first_int_with_key({}, ("a",)) == (None, None)


class TestOptionalInt:
    def test_valid_int(self):
        assert _optional_int(42) == 42

    def test_none_returns_none(self):
        assert _optional_int(None) is None

    def test_dash_returns_none(self):
        assert _optional_int("-") is None

    def test_invalid_returns_none(self):
        assert _optional_int("foo") is None


class TestSafeInt:
    def test_valid_int(self):
        assert _safe_int(42) == 42

    def test_dash_returns_zero(self):
        assert _safe_int("-") == 0

    def test_none_returns_zero(self):
        assert _safe_int(None) == 0

    def test_invalid_returns_zero(self):
        assert _safe_int("foo") == 0


class TestToolData:
    def test_extracts_metadata_data(self):
        msg = Message(role=Role.TOOL, content="", metadata={"data": {"key": "value"}})
        assert _tool_data(msg) == {"key": "value"}

    def test_parses_json_content(self):
        msg = Message(role=Role.TOOL, content='{"key": "value"}')
        assert _tool_data(msg) == {"key": "value"}

    def test_returns_empty_for_invalid_json(self):
        msg = Message(role=Role.TOOL, content="not json")
        assert _tool_data(msg) == {}

    def test_returns_empty_for_non_dict_json(self):
        msg = Message(role=Role.TOOL, content='["list"]')
        assert _tool_data(msg) == {}

    def test_prefers_metadata_over_content(self):
        msg = Message(role=Role.TOOL, content='{"content": "value"}', metadata={"data": {"meta": "value"}})
        assert _tool_data(msg) == {"meta": "value"}


class TestMemoryTrace:
    def test_extracts_memory_trace(self):
        msg = Message(role=Role.ASSISTANT, content="", metadata={"memory_trace": {"classic": []}})
        assert _memory_trace(msg) == {"classic": []}

    def test_returns_empty_when_missing(self):
        msg = Message(role=Role.ASSISTANT, content="")
        assert _memory_trace(msg) == {}

    def test_returns_empty_when_not_dict(self):
        msg = Message(role=Role.ASSISTANT, content="", metadata={"memory_trace": "not dict"})
        assert _memory_trace(msg) == {}


class TestMemoryTraceItems:
    def test_filters_dicts(self):
        trace = {"classic": [{"path": "a"}, "not dict", {"path": "b"}]}
        items = _memory_trace_items(trace, "classic")
        assert len(items) == 2
        assert items[0]["path"] == "a"

    def test_returns_empty_for_missing_key(self):
        assert _memory_trace_items({}, "classic") == []

    def test_returns_empty_for_non_list(self):
        assert _memory_trace_items({"classic": "not list"}, "classic") == []


class TestMemoryEntryAdd:
    def test_increments_count(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        _memory_entry_add(entry, "path", "evidence", "msg-1")
        assert entry["count"] == 1

    def test_appends_path(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        _memory_entry_add(entry, "path.py", "evidence", "msg-1")
        assert entry["paths"] == ["path.py"]

    def test_dedupes_paths(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        _memory_entry_add(entry, "path.py", "evidence", "msg-1")
        _memory_entry_add(entry, "path.py", "evidence", "msg-2")
        assert entry["paths"] == ["path.py"]

    def test_truncates_evidence(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        long_evidence = "x" * 300
        _memory_entry_add(entry, None, long_evidence, "msg-1")
        assert len(entry["evidence"][0]) == 280

    def test_skips_empty_evidence(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        _memory_entry_add(entry, None, "   ", "msg-1")
        assert entry["evidence"] == []

    def test_dedupes_messages(self):
        entry = {"count": 0, "paths": [], "evidence": [], "messages": []}
        _memory_entry_add(entry, None, "evidence", "msg-1")
        _memory_entry_add(entry, None, "evidence", "msg-1")
        assert entry["messages"] == ["msg-1"]


class TestCompactMemoryLabel:
    def test_empty_returns_memory(self):
        assert _compact_memory_label("") == "memory"

    def test_short_text(self):
        assert _compact_memory_label("hello") == "hello"

    def test_truncates_long_text(self):
        assert len(_compact_memory_label("x" * 200)) == 120

    def test_takes_last_two_path_parts(self):
        assert _compact_memory_label("a/b/c/d.py") == "c/d.py"

    def test_single_part_path(self):
        assert _compact_memory_label("file.py") == "file.py"


class TestDiffStats:
    def test_uses_explicit_fields(self):
        assert _diff_stats({"added_lines": 3, "removed_lines": 1}) == (3, 1)

    def test_parses_diff(self):
        diff = "@@ -1,2 +1,3 @@\n-old\n+new\n+another"
        assert _diff_stats({"diff": diff}) == (2, 1)

    def test_ignores_plus_minus_headers(self):
        diff = "--- a/file\n+++ b/file\n+line\n-line"
        assert _diff_stats({"diff": diff}) == (1, 1)

    def test_returns_zero_when_empty(self):
        assert _diff_stats({}) == (0, 0)


class TestSourcesFromToolData:
    def test_browser_search_results(self):
        data = {
            "results": [
                {"url": "https://example.com", "title": "Example"},
            ]
        }
        sources = _sources_from_tool_data("BrowserSearch", data)
        assert len(sources) == 1
        assert sources[0]["url"] == "https://example.com"

    def test_browser_list_tabs(self):
        data = {
            "tabs": [
                {"url": "https://example.com", "title": "Example"},
            ]
        }
        sources = _sources_from_tool_data("BrowserListTabs", data)
        assert len(sources) == 1

    def test_single_record_tool(self):
        data = {"url": "https://example.com", "title": "Example"}
        sources = _sources_from_tool_data("WebFetch", data)
        assert len(sources) == 1

    def test_empty_results(self):
        assert _sources_from_tool_data("BrowserSearch", {"results": []}) == []


class TestSourceFromRecord:
    def test_valid_url(self):
        result = _source_from_record("WebFetch", {"url": "https://example.com", "title": "Example"}, 1)
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"
        assert result[0]["domain"] == "example.com"

    def test_missing_url_returns_empty(self):
        assert _source_from_record("WebFetch", {}, 1) == []

    def test_invalid_scheme_returns_empty(self):
        assert _source_from_record("WebFetch", {"url": "ftp://example.com"}, 1) == []

    def test_uses_final_url(self):
        result = _source_from_record("WebFetch", {"final_url": "https://example.com/final"}, 1)
        assert result[0]["url"] == "https://example.com/final"

    def test_truncates_description(self):
        result = _source_from_record(
            "WebFetch",
            {"url": "https://example.com", "description": "word " * 150},
            1,
        )
        assert len(result[0]["description"]) <= 220

    def test_truncates_title(self):
        result = _source_from_record(
            "WebFetch",
            {"url": "https://example.com", "title": "x" * 200},
            1,
        )
        assert len(result[0]["title"]) == 140


class TestFileLineCount:
    def test_counts_lines(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("line1\nline2\nline3\n")
        assert _file_line_count(path) == 3

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("")
        assert _file_line_count(path) == 0

    def test_missing_file_returns_zero(self, tmp_path):
        assert _file_line_count(tmp_path / "missing.txt") == 0
