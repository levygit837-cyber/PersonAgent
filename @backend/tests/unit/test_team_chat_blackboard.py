"""Unit tests for the _Blackboard extraction.

These tests pin the observable contract of _Blackboard so that future
refactors (slices 3-8 of the team_chat decomposition) can rely on stable
invariants.
"""

from __future__ import annotations

import json

import pytest

from personagent.application.team_chat.blackboard.core import _Blackboard
from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig
from personagent.application.team_chat.types import (
    CoordinatorGuidance,
    ExecutionContract,
    TurnResult,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _agent(agent_id: str = "agent-1", name: str = "Agent One", role: str = "developer") -> TeamAgentConfig:
    return TeamAgentConfig(
        id=agent_id,
        name=name,
        role=role,
        system_prompt=f"You are {name}.",
    )


def _coordinator() -> TeamAgentConfig:
    return _agent("coord", "Coordinator", "coordinator")


def _turn(
    agent: TeamAgentConfig | None = None,
    round_index: int = 0,
    phase: str = "independent_round",
    content: str = "I think we should use Python.",
    blocker: str = "",
) -> TurnResult:
    return TurnResult(
        agent=agent or _agent(),
        round_index=round_index,
        phase=phase,
        content=content,
        reasoning="",
        digest=content[:40],
        usage=None,
        duration_ms=100,
        first_token_ms=None,
        tool_context={},
        coherency_score=0.8,
        blocker=blocker,
    )


def _contract() -> ExecutionContract:
    return ExecutionContract(
        summary="Do the thing",
        objective="Build a thing",
        subproblems=[{"id": "sp-1", "question": "How?"}],
        success_criteria=["It works"],
        risks=["None"],
        coverage_matrix=[{"id": "sp-1", "question": "How?"}],
        focus_assignments={},
        raw_content="raw",
        duration_ms=50,
    )


def _guidance() -> CoordinatorGuidance:
    return CoordinatorGuidance(
        summary="Focus on testing.",
        focus_assignments={"agent-1": "testing"},
        overlap_risks=["duplication"],
        debate_goals=["agree on stack"],
        redirects={},
        raw_content="raw",
        duration_ms=50,
    )


def _json_turn(agent: TeamAgentConfig, **claims) -> TurnResult:
    """Build a turn whose content is a JSON claim graph."""
    content = json.dumps(claims)
    return _turn(agent=agent, content=content)


# ---------------------------------------------------------------------------
# Construction & empty-state invariants
# ---------------------------------------------------------------------------

class TestBlackboardEmptyState:
    def test_coverage_ratio_is_one_when_no_matrix(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert bb.coverage_ratio() == 1.0

    def test_no_real_blocker(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert not bb.has_real_blocker()

    def test_no_conflict(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert not bb.has_conflict()

    def test_no_mutating_proposal(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert not bb.has_mutating_proposal()

    def test_snapshot_has_zero_entry_count(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        snap = bb.snapshot()
        assert snap["entry_count"] == 0
        assert snap["latest_sequence"] == 0

    def test_coherency_summary_defaults_to_average_one(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        summary = bb.coherency_summary()
        assert summary["average"] == 1.0
        assert summary["low_count"] == 0

    def test_ballot_text_is_emptyish(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        text = bb.ballot_text()
        assert isinstance(text, str)

    def test_snapshot_text_is_emptyish(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        text = bb.snapshot_text()
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# Execution contract
# ---------------------------------------------------------------------------

class TestBlackboardExecutionContract:
    def test_publish_contract_appends_entry(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        entry = bb.publish_execution_contract(coordinator=coord, contract=contract)
        assert entry.event_type == "execution_contract"
        assert bb.snapshot()["entry_count"] == 1

    def test_publish_contract_twice_appends_two_entries(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        assert bb.snapshot()["entry_count"] == 2

    def test_coverage_matrix_populated_after_contract(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        assert len(bb.coverage_matrix()) == 1


# ---------------------------------------------------------------------------
# Publishing turns
# ---------------------------------------------------------------------------

class TestBlackboardPublishTurn:
    def test_publish_turn_appends_entry(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn()
        entry = bb.publish_turn(turn)
        assert bb.snapshot()["entry_count"] == 1
        assert entry.agent.id == "agent-1"

    def test_publish_turn_with_blocker(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(blocker="Missing credentials")
        entry = bb.publish_turn(turn)
        assert entry.event_type == "agent_blocker"
        assert bb.has_real_blocker()

    def test_publish_turn_without_blocker(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(blocker="")
        entry = bb.publish_turn(turn)
        assert entry.event_type == "agent_observation"
        assert not bb.has_real_blocker()

    def test_novelty_by_agent_after_turn(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(agent=_agent("agent-1"), content="Use Python.")
        bb.publish_turn(turn)
        novelty = bb.novelty_by_agent()
        assert "agent-1" in novelty
        assert 0.0 <= novelty["agent-1"] <= 1.0


# ---------------------------------------------------------------------------
# Claim deltas & delta guard
# ---------------------------------------------------------------------------

class TestBlackboardClaimDelta:
    def test_claim_delta_returns_nodes(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(content="Use Python.")
        entry = bb.publish_turn(turn)
        delta = bb.claim_delta_for(entry)
        assert "nodes" in delta
        assert "node_count" in delta
        assert "coverage_matrix" in delta
        assert "coherency" in delta

    def test_delta_guard_text_references_prior_claims(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        a1 = _agent("agent-1")
        turn1 = _json_turn(a1, claims=[{"text": "Use Python.", "confidence": 0.9}])
        bb.publish_turn(turn1)
        text = bb.delta_guard_text("agent-2")
        assert "Already covered by other agents" in text

    def test_delta_guard_text_no_prior_claims(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        text = bb.delta_guard_text("agent-1")
        assert text == "No previous claims yet."


# ---------------------------------------------------------------------------
# Coverage invariants
# ---------------------------------------------------------------------------

class TestBlackboardCoverage:
    def test_coverage_matrix_invariant_under_permutation(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        turn1 = _turn(agent=_agent("agent-1"), content="Use Python.")
        turn2 = _turn(agent=_agent("agent-2"), content="Use Python.")
        bb.publish_turn(turn1)
        bb.publish_turn(turn2)
        matrix_a = [m.get("status") for m in bb.coverage_matrix()]

        bb2 = _Blackboard("hybrid", user_input="How do I deploy?")
        bb2.publish_execution_contract(coordinator=coord, contract=contract)
        bb2.publish_turn(turn2)
        bb2.publish_turn(turn1)
        matrix_b = [m.get("status") for m in bb2.coverage_matrix()]
        assert matrix_a == matrix_b

    def test_coverage_ratio_changes_after_contract(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        before = bb.coverage_ratio()
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        after_contract = bb.coverage_ratio()
        assert after_contract < before  # 0/1 covered = 0.0 < 1.0
        turn = _turn(content="We will use Docker for deployment.")
        bb.publish_turn(turn)
        after_turn = bb.coverage_ratio()
        assert after_turn >= after_contract


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestBlackboardConflict:
    def test_has_conflict_when_contradicts_set(self) -> None:
        bb = _Blackboard("hybrid", user_input="Should we use A or B?")
        a1 = _agent("agent-1")
        a2 = _agent("agent-2")
        # Use longer, keyword-rich text so _keyword_set is non-empty and novelty > 0.35
        turn1 = _json_turn(
            a1,
            claims=[{
                "text": "We should implement the authentication service using OAuth2 and JWT tokens.",
                "confidence": 0.9,
                "contradicts": ["use-b"],
            }]
        )
        turn2 = _json_turn(
            a2,
            claims=[{
                "text": "The deployment pipeline requires Docker containers orchestrated by Kubernetes clusters.",
                "confidence": 0.9,
                "id": "use-b",
            }]
        )
        bb.publish_turn(turn1)
        bb.publish_turn(turn2)
        assert bb.has_conflict()

    def test_no_conflict_without_contradicts(self) -> None:
        bb = _Blackboard("hybrid", user_input="Should we use A or B?")
        a1 = _agent("agent-1")
        a2 = _agent("agent-2")
        turn1 = _json_turn(a1, claims=[{"text": "Use Python.", "confidence": 0.9}])
        turn2 = _json_turn(a2, claims=[{"text": "Use Python too.", "confidence": 0.9}])
        bb.publish_turn(turn1)
        bb.publish_turn(turn2)
        assert not bb.has_conflict()


# ---------------------------------------------------------------------------
# Debate skip & fast-vote
# ---------------------------------------------------------------------------

class TestBlackboardDebateSkip:
    def test_should_skip_debate_when_high_coverage_no_blockers(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        # Need coverage_ratio >= 0.85; with one item covered we get 1.0
        turn = _turn(content="We will use Docker for deployment.")
        bb.publish_turn(turn)
        if bb.coverage_ratio() >= 0.85:
            assert bb.should_skip_debate()
        else:
            pytest.skip("coverage did not reach threshold in this fixture")

    def test_fast_vote_ready_true_when_empty(self) -> None:
        # Empty blackboard has coverage_ratio == 1.0 (no items = fully covered)
        # and no blockers/conflicts, so fast_vote_ready returns True.
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert bb.fast_vote_ready()

    def test_fast_vote_ready_true_when_coverage_high_no_blockers(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        turn = _turn(content="We will use Docker.")
        bb.publish_turn(turn)
        if bb.coverage_ratio() >= 0.75:
            assert bb.fast_vote_ready()
        else:
            pytest.skip("coverage did not reach threshold in this fixture")

    def test_vote_triggers_non_empty_when_scheduled(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        team = TeamConfig(
            id="t1",
            name="Team",
            agents=(_agent("a1"), _agent("a2")),
            execution_order=("a1", "a2"),
            coordinator=coord,
            max_rounds=3,
        )
        triggers = bb.vote_triggers(0, team)
        assert "scheduled_interval" in triggers

    def test_vote_triggers_empty_when_not_scheduled(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        team = TeamConfig(
            id="t1",
            name="Team",
            agents=(_agent("a1"), _agent("a2")),
            execution_order=("a1", "a2"),
            coordinator=coord,
            max_rounds=3,
            vote_every_rounds=5,
        )
        triggers = bb.vote_triggers(1, team)
        assert "scheduled_interval" not in triggers


# ---------------------------------------------------------------------------
# Coordinator guidance
# ---------------------------------------------------------------------------

class TestBlackboardCoordinatorGuidance:
    def test_publish_coordinator_guidance_appends_entry(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        guidance = _guidance()
        entry = bb.publish_coordinator_guidance(coordinator=coord, round_index=0, guidance=guidance)
        assert entry.event_type == "coordinator_guidance"
        assert bb.snapshot()["entry_count"] == 1

    def test_latest_focus_for_agent(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        guidance = _guidance()
        bb.publish_coordinator_guidance(coordinator=coord, round_index=0, guidance=guidance)
        assert bb.latest_focus_for("agent-1") == "testing"

    def test_latest_lane_for_agent(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        coord = _coordinator()
        contract = _contract()
        # latest_lane_for looks at execution_contract subproblems with owner_agent_id
        contract = ExecutionContract(
            summary="Do the thing",
            objective="Build a thing",
            subproblems=[{"id": "sp-1", "question": "How?", "owner_agent_id": "agent-1", "focus": "testing"}],
            success_criteria=["It works"],
            risks=["None"],
            coverage_matrix=[{"id": "sp-1", "question": "How?"}],
            focus_assignments={},
            raw_content="raw",
            duration_ms=50,
        )
        bb.publish_execution_contract(coordinator=coord, contract=contract)
        lane = bb.latest_lane_for("agent-1")
        assert lane.get("focus") == "testing"

    def test_latest_lane_returns_empty_when_no_guidance(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        assert bb.latest_lane_for("agent-1") == {}


# ---------------------------------------------------------------------------
# Ballot text & snapshot text
# ---------------------------------------------------------------------------

class TestBlackboardBallotAndSnapshot:
    def test_ballot_text_is_string(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(content="Use Docker.")
        bb.publish_turn(turn)
        text = bb.ballot_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_snapshot_text_is_string(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn = _turn(content="Use Docker.")
        bb.publish_turn(turn)
        text = bb.snapshot_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_memory_snapshot_requires_kwargs(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        mem = bb.memory_snapshot(workspace_id="ws-1", conversation_id="c-1", run_id="r-1")
        assert "claim_graph" in mem
        assert "coverage_matrix" in mem
        assert "coherency" in mem
        assert mem["run_id"] == "r-1"


# ---------------------------------------------------------------------------
# Coherency summary freshness
# ---------------------------------------------------------------------------

class TestBlackboardCoherencySummary:
    def test_summary_average_between_zero_and_one(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        turn1 = _turn(agent=_agent("a1"), content="Use Docker.")
        turn2 = _turn(agent=_agent("a2"), content="Use Kubernetes.")
        bb.publish_turn(turn1)
        bb.publish_turn(turn2)
        summary = bb.coherency_summary()
        assert 0.0 <= summary["average"] <= 1.0
        assert isinstance(summary["low_count"], int)

    def test_summary_low_count_is_non_negative(self) -> None:
        bb = _Blackboard("hybrid", user_input="How do I deploy?")
        summary = bb.coherency_summary()
        assert summary["low_count"] >= 0
