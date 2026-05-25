"""Unit tests for ``blackboard_claim_graph.py`` (Slice 3 of blackboard decomposition).

Pins the observable contract of ClaimGraphAnalyzer and the 3 module-level helpers.
"""

from __future__ import annotations

from personagent.application.team_chat.blackboard_claim_graph import (
    ClaimGraphAnalyzer,
    _claim_signature,
    _novelty_score,
    _string_list,
)

# ---------------------------------------------------------------------------
# _string_list
# ---------------------------------------------------------------------------


def test_string_list_single_value() -> None:
    assert _string_list("hello") == ["hello"]


def test_string_list_comma_separated() -> None:
    assert _string_list("a, b, c") == ["a", "b", "c"]


def test_string_list_semicolon_separated() -> None:
    assert _string_list("x; y; z") == ["x", "y", "z"]


def test_string_list_nested_lists() -> None:
    assert _string_list(["a", "b"]) == ["a", "b"]


def test_string_list_deeply_nested() -> None:
    assert _string_list([["a", "b"], "c"]) == ["a", "b", "c"]


def test_string_list_empty_returns_empty() -> None:
    assert _string_list("") == []
    assert _string_list(None) == []


# ---------------------------------------------------------------------------
# _claim_signature
# ---------------------------------------------------------------------------


def test_claim_signature_returns_space_separated() -> None:
    sig = _claim_signature("database migration plan for users table")
    assert isinstance(sig, str)
    assert "database" in sig.split()


def test_claim_signature_truncates_at_18_terms() -> None:
    long_text = " ".join(f"word{idx}" for idx in range(50))
    sig = _claim_signature(long_text)
    assert len(sig.split()) <= 18


# ---------------------------------------------------------------------------
# _novelty_score
# ---------------------------------------------------------------------------


def test_novelty_score_empty_text_returns_zero() -> None:
    assert _novelty_score("...", [{"text": "something"}]) == 0.0


def test_novelty_score_identical_text_returns_low() -> None:
    score = _novelty_score("database migration", [
        {"text": "database migration", "status": "active"},
    ])
    assert score < 0.5


def test_novelty_score_unique_text_returns_high() -> None:
    score = _novelty_score("zebra stripes pattern", [
        {"text": "database migration", "status": "active"},
    ])
    assert score > 0.5


def test_novelty_score_skips_duplicates() -> None:
    score = _novelty_score("database migration", [
        {"text": "database migration", "status": "duplicate"},
    ])
    assert score > 0.5


# ---------------------------------------------------------------------------
# ClaimGraphAnalyzer
# ---------------------------------------------------------------------------


def _make_analyzer(**overrides: object) -> ClaimGraphAnalyzer:
    defaults: dict[str, object] = {
        "user_input": "test input",
        "execution_contract": {},
        "claim_nodes": [],
        "claim_signatures": set(),
        "duplicates": [],
        "coverage_matrix": [],
        "agent_novelty_scores": {},
    }
    defaults.update(overrides)
    return ClaimGraphAnalyzer(**defaults)  # type: ignore[arg-type]


def _make_turn(
    *,
    content: str = "plain text",
    digest: str = "summary",
    blocker: str = "",
    round_index: int = 0,
    phase: str = "independent_round",
    coherency_score: float = 0.8,
) -> object:
    from personagent.application.team_chat.contracts import TeamAgentConfig
    from personagent.application.team_chat.types import TurnResult

    return TurnResult(
        agent=TeamAgentConfig(id="a1", name="Agent", role="developer", system_prompt=""),
        round_index=round_index,
        phase=phase,
        content=content,
        reasoning="",
        digest=digest,
        usage=None,
        duration_ms=100,
        first_token_ms=None,
        tool_context={},
        coherency_score=coherency_score,
        tool_calls=[],
        tool_results=[],
        tool_proposals=[],
        blocker=blocker,
    )


def _make_entry(sequence: int = 1) -> object:
    from personagent.application.team_chat.contracts import TeamAgentConfig
    from personagent.application.team_chat.types import BlackboardEntry

    return BlackboardEntry(
        sequence=sequence,
        phase="independent_round",
        round_index=0,
        agent=TeamAgentConfig(id="a1", name="Agent", role="developer", system_prompt=""),
        event_type="agent_observation",
        payload={},
        created_at="2024-01-01T00:00:00Z",
    )


def test_analyzer_construction() -> None:
    analyzer = _make_analyzer(user_input="test", claim_nodes=[])
    assert analyzer._user_input == "test"
    assert analyzer._claim_nodes == []


def test_claim_nodes_from_turn_empty_when_no_digest_or_blocker() -> None:
    analyzer = _make_analyzer()
    turn = _make_turn(content="no json content here", digest="", blocker="")
    entry = _make_entry()
    result = analyzer.claim_nodes_from_turn(entry, turn)
    assert result == []


def test_claim_nodes_from_turn_with_blocker_creates_fallback() -> None:
    analyzer = _make_analyzer()
    turn = _make_turn(content="nothing", blocker="Cannot proceed", digest="blocker summary")
    entry = _make_entry()
    result = analyzer.claim_nodes_from_turn(entry, turn)
    assert len(result) == 1
    assert result[0]["type"] == "blocker"


def test_claim_nodes_from_turn_with_json_claims() -> None:
    analyzer = _make_analyzer(
        coverage_matrix=[{"id": "c1", "question": "What?", "expected_output": "", "owner_agent_id": "", "status": "open"}],
    )
    turn = _make_turn(content='{"claims": [{"text": "Use Python for the API"}]}')
    entry = _make_entry()
    result = analyzer.claim_nodes_from_turn(entry, turn)
    assert len(result) >= 1
    assert any(node["type"] == "claim" for node in result)


def test_claim_nodes_tracks_novelty_scores() -> None:
    analyzer = _make_analyzer(agent_novelty_scores={})
    turn = _make_turn(content='{"claims": [{"text": "Use Python for the API"}]}')
    entry = _make_entry()
    analyzer.claim_nodes_from_turn(entry, turn)
    assert "a1" in analyzer._agent_novelty_scores
    assert len(analyzer._agent_novelty_scores["a1"]) > 0


def test_update_coverage_no_matrix_does_nothing() -> None:
    analyzer = _make_analyzer(coverage_matrix=[])
    analyzer.update_coverage([{"type": "claim", "text": "test"}])
    # Should not raise


def test_update_coverage_marks_item_covered() -> None:
    matrix = [{"id": "requirements", "question": "What?", "expected_output": "", "agent_id": "", "status": "open"}]
    analyzer = _make_analyzer(coverage_matrix=matrix)
    analyzer.update_coverage([{"type": "claim", "text": "requirements analysis done", "coverage": ["requirements"]}])
    assert matrix[0]["status"] == "covered"


def test_infer_coverage_empty_matrix() -> None:
    analyzer = _make_analyzer(coverage_matrix=[])
    assert analyzer._infer_coverage_for_claim("some text", "a1") == []


def test_deduplication_via_signature() -> None:
    analyzer = _make_analyzer(
        claim_signatures={"use python for the api"},
        claim_nodes=[{"text": "Use Python for the API", "status": "active", "type": "claim"}],
    )
    turn = _make_turn(content='{"claims": [{"text": "Use Python for the API"}]}')
    entry = _make_entry()
    result = analyzer.claim_nodes_from_turn(entry, turn)
    duplicates = [n for n in result if n.get("status") == "duplicate"]
    assert len(duplicates) > 0
