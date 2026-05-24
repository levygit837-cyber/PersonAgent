"""Unit tests for ``blackboard_scoring.py`` (Slice 2 of blackboard decomposition).

Pins the observable contract of the 7 extracted scoring/metric utility functions.
"""

from __future__ import annotations

from personagent.application.team_chat.blackboard_scoring import (
    _clamp_float,
    _coherency_score,
    _compact_workspace_memory,
    _is_real_blocker_text,
    _keyword_set,
    _looks_mutating_text,
    _now_iso,
)

# ---------------------------------------------------------------------------
# _clamp_float
# ---------------------------------------------------------------------------

def test_clamp_float_normal_value() -> None:
    assert _clamp_float(0.5, 0, 1) == 0.5


def test_clamp_float_below_minimum() -> None:
    assert _clamp_float(-0.3, 0, 1) == 0.0


def test_clamp_float_above_maximum() -> None:
    assert _clamp_float(1.5, 0, 1) == 1.0


def test_clamp_float_invalid_input_returns_minimum() -> None:
    assert _clamp_float("nope", 0, 1) == 0.0


def test_clamp_float_none_returns_minimum() -> None:
    assert _clamp_float(None, 0, 1) == 0.0


# ---------------------------------------------------------------------------
# _coherency_score
# ---------------------------------------------------------------------------

def test_coherency_score_empty_text_returns_zero() -> None:
    assert _coherency_score("...", "user input", {}) == 0.0


def test_coherency_score_matching_keywords_returns_high_score() -> None:
    score = _coherency_score("database migration plan", "database migration plan", {})
    assert score > 0.6


def test_coherency_score_unrelated_text_returns_low_score() -> None:
    score = _coherency_score("zebra stripes", "database migration", {})
    assert score <= 0.5


def test_coherency_score_with_execution_contract() -> None:
    score = _coherency_score(
        "migrate the users table",
        "original user input",
        {"objective": "migrate users table", "summary": "migration task", "success_criteria": []},
    )
    assert 0 <= score <= 1


# ---------------------------------------------------------------------------
# _is_real_blocker_text
# ---------------------------------------------------------------------------

def test_is_real_blocker_empty_returns_false() -> None:
    assert not _is_real_blocker_text("")


def test_is_real_blocker_false_signal_detected() -> None:
    assert not _is_real_blocker_text("Vote response was not valid JSON")


def test_is_real_blocker_partially_parsed() -> None:
    assert not _is_real_blocker_text("partially parsed response")


def test_is_real_blocker_real_blocker() -> None:
    assert _is_real_blocker_text("Cannot deploy because the database schema conflicts with legacy models")


def test_is_real_blocker_case_insensitive() -> None:
    assert not _is_real_blocker_text("NO BLOCKER")


# ---------------------------------------------------------------------------
# _looks_mutating_text
# ---------------------------------------------------------------------------

def test_looks_mutating_write() -> None:
    assert _looks_mutating_text("write to file")


def test_looks_mutating_edit() -> None:
    assert _looks_mutating_text("edit the document")


def test_looks_mutating_delete() -> None:
    assert _looks_mutating_text("delete old entry")


def test_looks_mutating_non_mutating() -> None:
    assert not _looks_mutating_text("read the file content")


def test_looks_mutating_case_insensitive() -> None:
    assert _looks_mutating_text("REMOVE unused import")


# ---------------------------------------------------------------------------
# _keyword_set
# ---------------------------------------------------------------------------

def test_keyword_set_extracts_words() -> None:
    result = _keyword_set("database migration plan for users")
    assert "database" in result
    assert "migration" in result
    assert "plan" in result
    assert "users" in result


def test_keyword_set_filters_stopwords() -> None:
    result = _keyword_set("the agent team that and this para como com uma que blackboard mode")
    assert len(result) == 0


def test_keyword_set_minimum_length() -> None:
    result = _keyword_set("a b c ab abc abcd")
    assert "abcd" in result
    # 3-char words excluded
    assert "abc" not in result
    assert "ab" not in result


def test_keyword_set_empty_returns_empty() -> None:
    assert _keyword_set("") == set()


# ---------------------------------------------------------------------------
# _compact_workspace_memory
# ---------------------------------------------------------------------------

def test_compact_workspace_memory_empty() -> None:
    assert _compact_workspace_memory({}) == {}


def test_compact_workspace_memory_non_dict() -> None:
    assert _compact_workspace_memory(None) == {}
    assert _compact_workspace_memory("string") == {}


def test_compact_workspace_memory_preserves_keys() -> None:
    snapshot = {
        "workspace_id": "ws1",
        "updated_at": "2024-01-01T00:00:00Z",
        "run_id": "run1",
        "decisions": ["dec1"],
        "evidence": ["ev1"],
        "coverage_matrix": [],
        "claim_graph": {"nodes": []},
    }
    result = _compact_workspace_memory(snapshot)
    assert result["workspace_id"] == "ws1"
    assert "claim_nodes" in result


def test_compact_workspace_memory_truncates_lists() -> None:
    snapshot = {
        "workspace_id": "ws1",
        "updated_at": "t",
        "run_id": "r",
        "decisions": [f"d{i}" for i in range(20)],
        "evidence": [f"e{i}" for i in range(20)],
        "coverage_matrix": [],
        "claim_graph": {"nodes": []},
    }
    result = _compact_workspace_memory(snapshot)
    assert len(result["decisions"]) <= 8
    assert len(result["evidence"]) <= 8


# ---------------------------------------------------------------------------
# _now_iso
# ---------------------------------------------------------------------------

def test_now_iso_returns_string() -> None:
    result = _now_iso()
    assert isinstance(result, str)
    assert "T" in result


def test_now_iso_ends_with_z_or_offset() -> None:
    result = _now_iso()
    assert result.endswith("Z") or "+" in result
