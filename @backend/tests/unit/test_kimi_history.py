"""Tests for Kimi history block handling."""

from personagent.infrastructure.llm.kimi.history import (
    anthropic_history_blocks,
    anthropic_history_blocks_from_tool_calls,
    attach_anthropic_history_blocks,
    parse_tool_arguments,
    tool_call_from_anthropic_block,
)


class TestAnthropicHistoryBlocks:
    def test_text_block(self) -> None:
        blocks = {0: {"type": "text", "text": "hello"}}
        result = anthropic_history_blocks(blocks)
        assert result == [{"type": "text", "text": "hello"}]

    def test_empty_text_ignored(self) -> None:
        blocks = {0: {"type": "text", "text": ""}}
        result = anthropic_history_blocks(blocks)
        assert result == []

    def test_thinking_block(self) -> None:
        blocks = {0: {"type": "thinking", "thinking": "hmm", "signature": "sig"}}
        result = anthropic_history_blocks(blocks)
        assert result == [{"type": "thinking", "thinking": "hmm", "signature": "sig"}]

    def test_tool_use_block(self) -> None:
        blocks = {0: {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "/tmp"}}}
        result = anthropic_history_blocks(blocks)
        assert result == [{"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "/tmp"}}]

    def test_unknown_type_ignored(self) -> None:
        blocks = {0: {"type": "unknown"}}
        result = anthropic_history_blocks(blocks)
        assert result == []

    def test_sorted_by_index(self) -> None:
        blocks = {
            2: {"type": "text", "text": "second"},
            1: {"type": "text", "text": "first"},
        }
        result = anthropic_history_blocks(blocks)
        assert [b["text"] for b in result] == ["first", "second"]


class TestToolCallFromAnthropicBlock:
    def test_basic_tool_use(self) -> None:
        block = {"type": "tool_use", "id": "t1", "name": "read", "input": {"path": "/tmp"}}
        result = tool_call_from_anthropic_block(block)
        assert result["id"] == "t1"
        assert result["type"] == "function"
        assert result["function"]["name"] == "read"
        assert result["function"]["arguments"] == '{"path": "/tmp"}'

    def test_string_input_preserved(self) -> None:
        block = {"type": "tool_use", "id": "t1", "name": "read", "input": "raw"}
        result = tool_call_from_anthropic_block(block)
        assert result["function"]["arguments"] == "raw"


class TestParseToolArguments:
    def test_dict_passthrough(self) -> None:
        assert parse_tool_arguments({"a": 1}) == {"a": 1}

    def test_valid_json_string(self) -> None:
        assert parse_tool_arguments('{"a": 1}') == {"a": 1}

    def test_invalid_json_string(self) -> None:
        assert parse_tool_arguments("not-json") == {"_raw_arguments": "not-json"}

    def test_non_dict_json(self) -> None:
        assert parse_tool_arguments("[1, 2]") == {"_raw_arguments": [1, 2]}

    def test_none(self) -> None:
        assert parse_tool_arguments(None) == {"_raw_arguments": None}


class TestAttachAnthropicHistoryBlocks:
    def test_attaches_blocks(self) -> None:
        tool_calls = [{"id": "t1", "extra_content": {"anthropic": {}}}]
        history = [{"type": "text", "text": "hi"}]
        attach_anthropic_history_blocks(tool_calls, history)
        assert tool_calls[0]["extra_content"]["anthropic"]["content_blocks"] == history

    def test_no_tool_calls_noop(self) -> None:
        attach_anthropic_history_blocks([], [{"type": "text"}])

    def test_no_history_noop(self) -> None:
        attach_anthropic_history_blocks([{"id": "t1"}], [])


class TestAnthropicHistoryBlocksFromToolCalls:
    def test_extracts_from_extra_content(self) -> None:
        tool_calls = [
            {
                "id": "t1",
                "extra_content": {
                    "anthropic": {"content_blocks": [{"type": "text", "text": "hello"}]}
                },
            }
        ]
        result = anthropic_history_blocks_from_tool_calls(tool_calls)
        assert result == [{"type": "text", "text": "hello"}]

    def test_missing_extra_content_returns_none(self) -> None:
        assert anthropic_history_blocks_from_tool_calls([{"id": "t1"}]) is None
