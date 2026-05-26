"""Unit tests for the CoordinatorPhase extraction.

These tests pin the observable contract of CoordinatorPhase so that future
refactors can rely on stable invariants.
"""

from __future__ import annotations

from typing import Any

import pytest

from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig
from personagent.application.team_chat.phases.coordinator import (
    CoordinatorPhase,
    _coordinator_focus_assignments,
    _coordinator_redirects,
    _coverage_matrix_from_payload,
    _default_focus_for_agent,
    _normalize_subproblems,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _LLMResult:
    def __init__(self, content: str = "", usage: Any | None = None) -> None:
        self.content = content
        self.usage = usage


class _LLMBackendStub:
    def __init__(self, result: _LLMResult | None = None, fail: bool = False) -> None:
        self.result = result or _LLMResult()
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def chat_completion(self, **kwargs: Any) -> _LLMResult:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("LLM failed")
        return self.result

    async def chat_completion_stream(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True}

    async def get_model_info(self) -> dict[str, Any]:
        return {}


def _agent(agent_id: str = "agent-1", name: str = "Agent One", role: str = "developer") -> TeamAgentConfig:
    return TeamAgentConfig(
        id=agent_id,
        name=name,
        role=role,
        system_prompt=f"You are {name}.",
    )


def _team(*agents: TeamAgentConfig) -> TeamConfig:
    return TeamConfig(
        id="team-1",
        name="Test Team",
        coordinator=_agent("coord", "Coordinator", "coordinator"),
        agents=list(agents) if agents else [_agent()],
        execution_order=[a.id for a in (agents or [_agent()])],
        consensus_threshold=0.5,
        vote_every_rounds=2,
        max_rounds=3,
    )


def _request(message: str = "Hello", provider: str = "openai") -> Any:
    from personagent.application.team_chat.contracts import TeamChatRequest

    return TeamChatRequest(
        message=message,
        model="gpt-4",
        provider=provider,
    )


# ---------------------------------------------------------------------------
# execution_contract_messages
# ---------------------------------------------------------------------------

def test_execution_contract_messages_contains_system_and_user() -> None:
    phase = CoordinatorPhase(_LLMBackendStub())
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    msgs = phase.execution_contract_messages(request, team, blackboard)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "focus_assignments" in msgs[1]["content"]
    assert team.name in msgs[1]["content"]


# ---------------------------------------------------------------------------
# coordinator_planning_messages
# ---------------------------------------------------------------------------

def test_coordinator_planning_messages_contains_round_and_blackboard() -> None:
    phase = CoordinatorPhase(_LLMBackendStub())
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    msgs = phase.coordinator_planning_messages(request, team, 2, blackboard)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Round: 2" in msgs[1]["content"]
    assert "redirects" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# run_execution_contract — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_execution_contract_parses_json() -> None:
    stub = _LLMBackendStub(
        result=_LLMResult(
            content='{"summary": "test strategy", "objective": "do it", "success_criteria": ["c1"], "risks": ["r1"], "focus_assignments": {"a1": "focus1"}}'
        )
    )
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    contract = await phase.run_execution_contract(
        request=request, team=team, blackboard=blackboard, run_id="run-1"
    )
    assert contract.summary == "test strategy"
    assert contract.objective == "do it"
    assert contract.success_criteria == ["c1"]
    assert contract.risks == ["r1"]
    assert "a1" in contract.focus_assignments
    assert contract.duration_ms >= 0
    assert contract.raw_content == stub.result.content


@pytest.mark.asyncio
async def test_run_execution_contract_uses_defaults_when_keys_missing() -> None:
    stub = _LLMBackendStub(result=_LLMResult(content='{}'))
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"))
    request = _request(message="Solve this")
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    contract = await phase.run_execution_contract(
        request=request, team=team, blackboard=blackboard, run_id="run-1"
    )
    assert "Coordinator created an execution contract" in contract.summary
    assert contract.objective == "Solve this"
    assert len(contract.success_criteria) == 3  # defaults
    assert contract.risks == []


@pytest.mark.asyncio
async def test_run_execution_contract_records_duration_and_usage() -> None:
    stub = _LLMBackendStub(result=_LLMResult(content='{"summary": "s"}', usage={"tokens": 10}))
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    contract = await phase.run_execution_contract(
        request=request, team=team, blackboard=blackboard, run_id="run-1"
    )
    assert contract.duration_ms >= 0


@pytest.mark.asyncio
async def test_run_execution_contract_llm_failure_raises() -> None:
    stub = _LLMBackendStub(fail=True)
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    with pytest.raises(RuntimeError):
        await phase.run_execution_contract(
            request=request, team=team, blackboard=blackboard, run_id="run-1"
        )


# ---------------------------------------------------------------------------
# run_coordinator_planning — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_coordinator_planning_parses_json() -> None:
    stub = _LLMBackendStub(
        result=_LLMResult(
            content='{"summary": "plan", "overlap_risks": ["risk1"], "debate_goals": ["goal1"], "focus_assignments": {"a1": "f1"}, "redirects": {"a1": "r1"}}'
        )
    )
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    guidance = await phase.run_coordinator_planning(
        request=request, team=team, round_index=2, blackboard=blackboard, run_id="run-1"
    )
    assert guidance.summary == "plan"
    assert guidance.overlap_risks == ["risk1"]
    assert guidance.debate_goals == ["goal1"]
    assert "a1" in guidance.focus_assignments
    assert guidance.redirects == {"a1": "r1"}
    assert guidance.duration_ms >= 0


@pytest.mark.asyncio
async def test_run_coordinator_planning_uses_defaults() -> None:
    stub = _LLMBackendStub(result=_LLMResult(content='{}'))
    phase = CoordinatorPhase(stub)
    team = _team(_agent("a1", "One"))
    request = _request()
    from personagent.application.team_chat.blackboard.core import _Blackboard

    blackboard = _Blackboard("full", user_input=request.message)
    guidance = await phase.run_coordinator_planning(
        request=request, team=team, round_index=1, blackboard=blackboard, run_id="run-1"
    )
    assert "debate focus areas" in guidance.summary
    assert guidance.overlap_risks == []
    assert guidance.debate_goals == []
    assert guidance.redirects == {}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_default_focus_for_agent_by_role() -> None:
    risk_agent = _agent("a1", "One", "risk analyst")
    assert "blockers" in _default_focus_for_agent(risk_agent)

    builder_agent = _agent("a2", "Two", "solution architect")
    assert "execution path" in _default_focus_for_agent(builder_agent)

    review_agent = _agent("a3", "Three", "reviewer")
    assert "coherence" in _default_focus_for_agent(review_agent)

    generic_agent = _agent("a4", "Four", "developer")
    assert "Clarify requirements" in _default_focus_for_agent(generic_agent)


def test_coverage_matrix_from_payload_with_data() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    payload = {
        "coverage_matrix": [
            {"id": "cm1", "question": "q1", "expected_output": "e1", "owner_agent_id": "a1"}
        ]
    }
    matrix = _coverage_matrix_from_payload(payload, team)
    assert len(matrix) == 1
    assert matrix[0]["id"] == "cm1"


def test_coverage_matrix_from_payload_defaults() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"), _agent("a3", "Three"), _agent("a4", "Four"))
    matrix = _coverage_matrix_from_payload({}, team)
    assert len(matrix) == 4
    assert matrix[0]["id"] == "requirements"
    assert matrix[0]["status"] == "open"


def test_normalize_subproblems_with_list() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    raw = [
        {"id": "sp1", "description": "desc1", "required_output": "out1"},
        {"id": "sp2", "description": "desc2"},
    ]
    result = _normalize_subproblems(raw, team, [])
    assert len(result) == 2
    assert result[0]["id"] == "sp1"
    assert result[0]["owner_agent_id"] == "a1"
    assert result[1]["owner_agent_id"] == "a2"


def test_normalize_subproblems_with_dict_input() -> None:
    team = _team(_agent("a1", "One"))
    raw = {"key1": "value1"}
    result = _normalize_subproblems(raw, team, [])
    assert len(result) == 1
    assert result[0]["id"] == "key1"
    assert result[0]["description"] == "value1"


def test_normalize_subproblems_defaults() -> None:
    team = _team(_agent("a1", "One"))
    result = _normalize_subproblems(None, team, [])
    assert len(result) == 1
    assert result[0]["owner_agent_id"] == "a1"


def test_coordinator_focus_assignments_from_payload() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    payload = {"focus_assignments": {"a1": "focus1", "a2": "focus2"}}
    assignments = _coordinator_focus_assignments(payload, team)
    assert assignments == {"a1": "focus1", "a2": "focus2"}


def test_coordinator_focus_assignments_fallback() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    payload = {}
    assignments = _coordinator_focus_assignments(payload, team)
    assert "a1" in assignments
    assert "a2" in assignments
    # Should fall back to _default_focus_for_agent
    assert "Clarify requirements" in assignments["a1"]


def test_coordinator_redirects_from_payload() -> None:
    team = _team(_agent("a1", "One"), _agent("a2", "Two"))
    payload = {"redirects": {"a1": "redirect1"}}
    redirects = _coordinator_redirects(payload, team)
    assert redirects == {"a1": "redirect1"}


def test_coordinator_redirects_empty() -> None:
    team = _team(_agent("a1", "One"))
    payload = {}
    redirects = _coordinator_redirects(payload, team)
    assert redirects == {}
