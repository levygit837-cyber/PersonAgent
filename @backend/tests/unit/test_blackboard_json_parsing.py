"""Unit tests for ``blackboard_json_parsing.py`` (Slice 1 of blackboard decomposition).

Pins the observable contract of the 7 extracted JSON parsing / payload helper
functions so future slices can rely on stable behavior.
"""

from __future__ import annotations

from personagent.application.team_chat.blackboard_json_parsing import (
    _digest,
    _extract_complete_json_objects_from_array,
    _normalize_coverage_matrix,
    _parse_json_object,
    _parse_partial_claim_graph,
    _strip_json_fence,
    _turn_blackboard_payload,
)
from personagent.application.team_chat.types import TurnResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_turn(
    *,
    content: str = "plain text",
    digest: str = "summary text",
    blocker: str = "",
    reasoning: str = "",
    phase: str = "independent_round",
    round_index: int = 0,
    coherency_score: float = 0.8,
    duration_ms: int = 100,
    first_token_ms: int | None = None,
    tool_context: dict | None = None,
    tool_calls: list | None = None,
    tool_results: list | None = None,
    tool_proposals: list | None = None,
) -> TurnResult:
    from personagent.application.team_chat.contracts import TeamAgentConfig

    return TurnResult(
        agent=TeamAgentConfig(id="a1", name="Agent", role="developer", system_prompt=""),
        round_index=round_index,
        phase=phase,
        content=content,
        reasoning=reasoning,
        digest=digest,
        usage=None,
        duration_ms=duration_ms,
        first_token_ms=first_token_ms,
        tool_context=tool_context or {},
        coherency_score=coherency_score,
        tool_calls=tool_calls or [],
        tool_results=tool_results or [],
        tool_proposals=tool_proposals or [],
        blocker=blocker,
    )


# ---------------------------------------------------------------------------
# _strip_json_fence
# ---------------------------------------------------------------------------

def test_strip_json_fence_no_fence_returns_unchanged() -> None:
    assert _strip_json_fence('{"key": "value"}') == '{"key": "value"}'


def test_strip_json_fence_removes_bare_backticks() -> None:
    result = _strip_json_fence("```\n{\"a\":1}\n```")
    assert '"a":1' in result
    assert "```" not in result


def test_strip_json_fence_removes_json_tagged_backticks() -> None:
    result = _strip_json_fence("```json\n{\"b\":2}\n```")
    assert '"b":2' in result
    assert "```" not in result


def test_strip_json_fence_whitespace_around_fence() -> None:
    result = _strip_json_fence("  ```json\n{\"x\": 1}\n```  ")
    assert '"x": 1' in result


# ---------------------------------------------------------------------------
# _digest
# ---------------------------------------------------------------------------

def test_digest_short_text_unchanged() -> None:
    assert _digest("hello world") == "hello world"


def test_digest_preserves_text_under_limit() -> None:
    text = "a" * 500
    assert _digest(text) == text


def test_digest_truncates_at_word_boundary() -> None:
    text = "hello world " * 200
    result = _digest(text, limit=100)
    assert len(result) <= 103  # "..." suffix
    assert result.endswith("...")


def test_digest_normalizes_whitespace() -> None:
    assert _digest("hello   world") == "hello world"


# ---------------------------------------------------------------------------
# _parse_json_object
# ---------------------------------------------------------------------------

def test_parse_json_object_valid_json() -> None:
    result = _parse_json_object('{"claims": [{"text": "a"}]}')
    assert result == {"claims": [{"text": "a"}]}


def test_parse_json_object_inside_markdown_fence() -> None:
    content = '```json\n{"claims": [{"text": "b"}]}\n```'
    result = _parse_json_object(content)
    assert result == {"claims": [{"text": "b"}]}


def test_parse_json_object_non_dict_returns_empty() -> None:
    assert _parse_json_object("[1, 2, 3]") == {}


def test_parse_json_object_malformed_falls_back_to_partial() -> None:
    content = 'something {"claims": [{"text": "c"}]} trailing'
    result = _parse_json_object(content)
    assert result == {"claims": [{"text": "c"}]}


# ---------------------------------------------------------------------------
# _parse_partial_claim_graph
# ---------------------------------------------------------------------------

def test_parse_partial_claim_graph_extracts_claims() -> None:
    text = '"claims": [{"text": "claim1", "confidence": 0.9}]'
    result = _parse_partial_claim_graph(text)
    assert "claims" in result
    assert len(result["claims"]) == 1
    assert result["claims"][0]["text"] == "claim1"


def test_parse_partial_claim_graph_extracts_coherency_score() -> None:
    text = '"coherency_score": 0.75'
    result = _parse_partial_claim_graph(text)
    assert result["coherency_score"] == 0.75


def test_parse_partial_claim_graph_extracts_evidence_with_alias() -> None:
    text = '"evidences": [{"text": "evidence1", "confidence": 0.8}]'
    result = _parse_partial_claim_graph(text)
    assert "evidence" in result
    assert len(result["evidence"]) == 1


# ---------------------------------------------------------------------------
# _extract_complete_json_objects_from_array
# ---------------------------------------------------------------------------

def test_extract_json_objects_complete_array() -> None:
    text = '"items": [{"id": 1}, {"id": 2}]'
    result = _extract_complete_json_objects_from_array(text, "items")
    assert len(result) == 2
    assert result[0] == {"id": 1}
    assert result[1] == {"id": 2}


def test_extract_json_objects_empty_array() -> None:
    text = '"items": []'
    result = _extract_complete_json_objects_from_array(text, "items")
    assert result == []


def test_extract_json_objects_key_not_present() -> None:
    text = '"other": [{"id": 1}]'
    result = _extract_complete_json_objects_from_array(text, "items")
    assert result == []


def test_extract_json_objects_with_escaped_chars() -> None:
    text = '"items": [{"text": "hello \\"world\\""}]'
    result = _extract_complete_json_objects_from_array(text, "items")
    assert len(result) == 1
    assert result[0]["text"] == 'hello "world"'


# ---------------------------------------------------------------------------
# _normalize_coverage_matrix
# ---------------------------------------------------------------------------

def test_normalize_coverage_matrix_empty() -> None:
    assert _normalize_coverage_matrix([]) == []


def test_normalize_coverage_matrix_non_list() -> None:
    assert _normalize_coverage_matrix(None) == []
    assert _normalize_coverage_matrix("string") == []


def test_normalize_coverage_matrix_string_items() -> None:
    result = _normalize_coverage_matrix(["requirements", "risks"])
    assert len(result) == 2
    assert result[0]["id"] == "c1"
    assert result[0]["question"] == "requirements"
    assert result[0]["status"] == "open"
    assert result[0]["owner_agent_id"] == ""


def test_normalize_coverage_matrix_dict_items() -> None:
    raw = [
        {"id": "req", "question": "What?", "expected_output": "Answer",
         "owner_agent_id": "a1", "status": "covered", "agents": ["a1"],
         "evidence_node_ids": ["n1"]},
    ]
    result = _normalize_coverage_matrix(raw)
    assert len(result) == 1
    assert result[0]["id"] == "req"
    assert result[0]["status"] == "covered"
    assert result[0]["agents"] == ["a1"]


def test_normalize_coverage_matrix_default_status() -> None:
    result = _normalize_coverage_matrix([{"id": "x"}])
    assert result[0]["status"] == "open"


def test_normalize_coverage_matrix_mixed_items() -> None:
    raw = ["simple string", {"id": "typed", "question": "Q"}]
    result = _normalize_coverage_matrix(raw)
    assert len(result) == 2
    assert result[0]["id"] == "c1"
    assert result[1]["id"] == "typed"


# ---------------------------------------------------------------------------
# _turn_blackboard_payload
# ---------------------------------------------------------------------------

def test_turn_payload_basic_turn() -> None:
    turn = _make_turn(content="no json here", digest="summary text")
    payload = _turn_blackboard_payload(turn)
    assert payload["summary"] == "summary text"
    assert payload["phase"] == "independent_round"
    assert payload["duration_ms"] == 100
    assert payload["coherency_score"] == 0.8


def test_turn_payload_with_blocker() -> None:
    turn = _make_turn(content="blocked", blocker="Cannot proceed without auth")
    payload = _turn_blackboard_payload(turn)
    assert payload["blocker"] == "Cannot proceed without auth"


def test_turn_payload_with_json_content() -> None:
    turn = _make_turn(content='{"claims": [{"text": "c1", "confidence": 0.9}]}')
    payload = _turn_blackboard_payload(turn)
    assert "claims" in payload
    assert len(payload["claims"]) == 1


def test_turn_payload_reasoning_fallback() -> None:
    turn = _make_turn(content="no json here", digest="", reasoning="Internal analysis done")
    payload = _turn_blackboard_payload(turn)
    assert payload["summary"] == "Reasoning-only contribution."


def test_turn_payload_no_output() -> None:
    turn = _make_turn(content="no json here", digest="", reasoning="")
    payload = _turn_blackboard_payload(turn)
    assert payload["summary"] == "No visible output."
