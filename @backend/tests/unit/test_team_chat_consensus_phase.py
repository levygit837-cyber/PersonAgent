"""Unit tests for the ConsensusPhase extraction.

These tests pin the observable contract of ConsensusPhase so that future
refactors can rely on stable invariants.
"""

from __future__ import annotations

from typing import Any

import pytest

from personagent.application.team_chat.blackboard import _Blackboard
from personagent.application.team_chat.consensus_phase import (
    ConsensusPhase,
    _consensus_snapshot,
    _fast_vote,
    _fast_vote_enabled,
    _parse_vote_payload,
    _regex_bool,
    _regex_number,
    _regex_string_or_bool,
    _regex_string_or_list_hint,
    _vote_event,
    _votes_text,
)
from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig
from personagent.application.team_chat.types import Vote

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
# vote_messages
# ---------------------------------------------------------------------------

def test_vote_messages_contains_system_and_user() -> None:
    phase = ConsensusPhase(_LLMBackendStub())
    agent = _agent()
    team = _team(agent)
    request = _request()
    blackboard = _Blackboard("full", user_input=request.message)
    msgs = phase.vote_messages(request, team, agent, 1, blackboard)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "approve" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert agent.name in msgs[1]["content"]
    assert "Round: 1" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# run_vote — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_vote_parses_json_payload() -> None:
    stub = _LLMBackendStub(
        result=_LLMResult(
            content='{"approve": true, "confidence": 0.9, "blocker": "", "critical_blocker": false, "final_points": "looks good"}'
        )
    )
    phase = ConsensusPhase(stub)
    agent = _agent()
    team = _team(agent)
    request = _request()
    blackboard = _Blackboard("full", user_input=request.message)
    vote = await phase.run_vote(request, team, agent, 1, blackboard, "run-1")
    assert isinstance(vote, Vote)
    assert vote.approve is True
    assert vote.confidence == pytest.approx(0.9)
    assert vote.blocker == ""
    assert vote.critical_blocker is False
    assert vote.final_points == "looks good"
    assert vote.agent.id == agent.id


@pytest.mark.asyncio
async def test_run_vote_records_duration_and_usage() -> None:
    stub = _LLMBackendStub(
        result=_LLMResult(
            content='{"approve": true, "confidence": 0.8}',
            usage={"tokens": 42},
        )
    )
    phase = ConsensusPhase(stub)
    agent = _agent()
    team = _team(agent)
    request = _request()
    blackboard = _Blackboard("full", user_input=request.message)
    vote = await phase.run_vote(request, team, agent, 1, blackboard, "run-1")
    assert vote.duration_ms >= 0
    assert vote.usage == {"tokens": 42}


# ---------------------------------------------------------------------------
# run_vote — failure path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_vote_llm_failure_returns_fallback_vote() -> None:
    stub = _LLMBackendStub(fail=True)
    phase = ConsensusPhase(stub)
    agent = _agent()
    team = _team(agent)
    request = _request()
    blackboard = _Blackboard("full", user_input=request.message)
    vote = await phase.run_vote(request, team, agent, 1, blackboard, "run-1")
    assert vote.approve is False
    assert vote.confidence == 0.0
    assert agent.name in vote.blocker
    assert "failed" in vote.blocker
    assert vote.duration_ms >= 0


# ---------------------------------------------------------------------------
# _parse_vote_payload
# ---------------------------------------------------------------------------

def test_parse_vote_payload_valid_json() -> None:
    payload = _parse_vote_payload('{"approve": true, "confidence": 0.85, "critical_blocker": false}')
    assert payload["approve"] is True
    assert payload["confidence"] == pytest.approx(0.85)
    assert payload["critical_blocker"] is False


def test_parse_vote_payload_regex_fallback() -> None:
    text = 'some noise\n"approve": true\n"confidence": 0.75\n"blocker": "minor issue"\n"critical_blocker": false\n"final_points": "ok"'
    payload = _parse_vote_payload(text)
    assert payload["approve"] is True
    assert payload["confidence"] == pytest.approx(0.75)
    assert payload["blocker"] == "minor issue"
    assert payload["critical_blocker"] is False
    assert payload["final_points"] == "ok"


def test_parse_vote_payload_invalid_returns_defaults() -> None:
    payload = _parse_vote_payload("not json at all")
    assert payload["approve"] is False
    assert payload["confidence"] == 0.0
    assert "not valid JSON" in payload["blocker"]
    assert payload["critical_blocker"] is False


def test_parse_vote_payload_looks_like_vote_skips_regex() -> None:
    """When JSON has vote keys, return it directly even if fields are missing."""
    payload = _parse_vote_payload('{"approve": true}')
    assert payload["approve"] is True
    # Other keys come from the raw parsed object
    assert "confidence" not in payload


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

def test_regex_bool_finds_true_false() -> None:
    assert _regex_bool('{"approve": true}', "approve") is True
    assert _regex_bool('{"approve": false}', "approve") is False
    assert _regex_bool('{"approve": True}', "approve") is True
    assert _regex_bool('{"other": true}', "approve") is None


def test_regex_number_extracts_float() -> None:
    assert _regex_number('{"confidence": 0.85}', "confidence") == pytest.approx(0.85)
    assert _regex_number('{"confidence": 1}', "confidence") == pytest.approx(1.0)
    assert _regex_number('{"other": 0.5}', "confidence") is None


def test_regex_number_clamps_out_of_range() -> None:
    assert _regex_number('{"confidence": 1.5}', "confidence") == pytest.approx(1.0)
    # Negative numbers are not matched by the original regex; returns None
    assert _regex_number('{"confidence": -0.5}', "confidence") is None


def test_regex_string_or_bool_handles_bool_true() -> None:
    assert _regex_string_or_bool('{"blocker": true}', "blocker") == "Vote reported a blocker."


def test_regex_string_or_bool_handles_bool_false() -> None:
    assert _regex_string_or_bool('{"blocker": false}', "blocker") == ""


def test_regex_string_or_bool_extracts_string() -> None:
    assert _regex_string_or_bool('{"blocker": "issue"}', "blocker") == "issue"


def test_regex_string_or_list_hint_extracts_string() -> None:
    assert _regex_string_or_list_hint('{"final_points": "ok"}', "final_points") == "ok"


def test_regex_string_or_list_hint_detects_list() -> None:
    assert "list" in _regex_string_or_list_hint('{"final_points": []}', "final_points")


# ---------------------------------------------------------------------------
# _fast_vote
# ---------------------------------------------------------------------------

def test_fast_vote_returns_approve_true() -> None:
    agent = _agent()
    blackboard = _Blackboard("full", user_input="test")
    vote = _fast_vote(agent, blackboard)
    assert vote.approve is True
    assert vote.confidence == pytest.approx(0.82)
    assert vote.critical_blocker is False
    assert vote.duration_ms == 0
    assert vote.agent.id == agent.id


# ---------------------------------------------------------------------------
# _fast_vote_enabled
# ---------------------------------------------------------------------------

def test_fast_vote_enabled_openai() -> None:
    req = _request(provider="openai")
    assert _fast_vote_enabled(req) is True


def test_fast_vote_disabled_for_test_provider() -> None:
    req = _request(provider="test")
    assert _fast_vote_enabled(req) is False


def test_fast_vote_disabled_for_llama() -> None:
    req = _request(provider="llama")
    assert _fast_vote_enabled(req) is False


# ---------------------------------------------------------------------------
# _vote_event
# ---------------------------------------------------------------------------

def test_vote_event_shape() -> None:
    agent = _agent()
    vote = Vote(
        agent=agent,
        approve=True,
        confidence=0.9,
        blocker="",
        critical_blocker=False,
        final_points="ok",
        duration_ms=123,
        usage=None,
    )
    event = _vote_event("run-1", "conv-1", 2, vote)
    assert event["event"] == "agent_vote"
    assert event["run_id"] == "run-1"
    assert event["round"] == 2
    assert event["agent_id"] == agent.id
    assert event["approve"] is True
    assert event["confidence"] == pytest.approx(0.9)
    assert event["duration_ms"] == 123


# ---------------------------------------------------------------------------
# _votes_text
# ---------------------------------------------------------------------------

def test_votes_text_empty() -> None:
    assert _votes_text([]) == "No votes."


def test_votes_text_formats_vote() -> None:
    agent = _agent()
    vote = Vote(
        agent=agent,
        approve=False,
        confidence=0.5,
        blocker="issue",
        critical_blocker=True,
        final_points="needs work",
        duration_ms=100,
        usage=None,
    )
    text = _votes_text([vote])
    assert agent.name in text
    assert "approve=False" in text
    assert "critical_blocker=True" in text
    assert "issue" in text
    assert "needs work" in text


# ---------------------------------------------------------------------------
# _consensus_snapshot
# ---------------------------------------------------------------------------

def test_consensus_snapshot_with_majority_approval() -> None:
    a1 = _agent("a1", "One")
    a2 = _agent("a2", "Two")
    team = _team(a1, a2)
    votes = [
        Vote(agent=a1, approve=True, confidence=1.0, blocker="", critical_blocker=False, final_points="", duration_ms=0, usage=None),
        Vote(agent=a2, approve=False, confidence=0.0, blocker="no", critical_blocker=False, final_points="", duration_ms=0, usage=None),
    ]
    snapshot = _consensus_snapshot(team, votes)
    assert snapshot["approvals"] == 1
    assert snapshot["required"] == 1  # ceil(2 * 0.5)
    assert snapshot["threshold"] == 0.5
    assert snapshot["critical_blocker"] is False


def test_consensus_snapshot_detects_critical_blocker() -> None:
    a1 = _agent("a1", "One")
    a2 = _agent("a2", "Two")
    team = _team(a1, a2)
    votes = [
        Vote(agent=a1, approve=True, confidence=1.0, blocker="", critical_blocker=False, final_points="", duration_ms=0, usage=None),
        Vote(agent=a2, approve=True, confidence=1.0, blocker="", critical_blocker=True, final_points="", duration_ms=0, usage=None),
    ]
    snapshot = _consensus_snapshot(team, votes)
    assert snapshot["critical_blocker"] is True
    assert snapshot["approvals"] == 2


def test_consensus_snapshot_empty_votes() -> None:
    team = _team()
    snapshot = _consensus_snapshot(team, [])
    assert snapshot["approvals"] == 0
    assert snapshot["required"] == 1  # ceil(1 * 0.5)
    assert snapshot["critical_blocker"] is False
