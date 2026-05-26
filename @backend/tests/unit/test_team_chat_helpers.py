"""Unit tests for team_chat shared helpers."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from personagent.application.team_chat.contracts import TeamAgentConfig, TeamChatRequest, TeamConfig
from personagent.application.team_chat.helpers import (
    TOOL_PHASE_PLAN,
    _agent_system_prompt,
    _agent_tool_context,
    _apply_workspace_metadata,
    _blackboard_event,
    _blackboard_snapshot_event,
    _cancelled_event,
    _claim_graph_delta_event,
    _claim_graph_output_contract,
    _coherency_score_event,
    _coverage_matrix_event,
    _duration_ms,
    _is_relative_to,
    _resolve_allowed_path,
    _runtime_context,
    _team_policy_overlay,
    _tool_phase_event,
    _tool_proposal,
    _tool_result_payload,
    _tool_use_context_from_request,
    _turn_coherency_score,
    _turn_text,
    _unique_tool_call_ids,
    _workspace_id,
)
from personagent.application.team_chat.types import BlackboardEntry, TurnResult
from personagent.application.tools import ToolRuntimeConfig
from personagent.domain.conversation.models import Conversation
from personagent.domain.tools import ToolExecutionStatus, ToolResult


@pytest.fixture
def team() -> TeamConfig:
    return TeamConfig(
        id="team-1",
        name="Alpha",
        agents=[
            TeamAgentConfig(
                id="agent-1",
                name="Alice",
                role="analyst",
                system_prompt="Be thorough.",
            ),
        ],
        coordinator=TeamAgentConfig(
            id="coord-1",
            name="Carol",
            role="coordinator",
            system_prompt="Coordinate.",
        ),
        execution_order=["agent-1"],
    )


@pytest.fixture
def request_fixture() -> TeamChatRequest:
    return TeamChatRequest(
        message="Hello",
        model="gpt-4",
        system_prompt="You are helpful.",
    )


@pytest.fixture
def agent(team: TeamConfig) -> TeamAgentConfig:
    return team.agents[0]


# ---------------------------------------------------------------------------
# System prompt & policy
# ---------------------------------------------------------------------------


def test_agent_system_prompt_includes_team_and_agent_names(
    request_fixture: TeamChatRequest, team: TeamConfig
) -> None:
    prompt = _agent_system_prompt(request_fixture, team, team.agents[0])
    assert "Alpha" in prompt
    assert "Alice" in prompt
    assert "analyst" in prompt
    assert "Be thorough." in prompt


def test_team_policy_overlay_contains_expected_sections() -> None:
    overlay = _team_policy_overlay()
    assert "Intake" in overlay
    assert "Finalization" in overlay


# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


def test_runtime_context_returns_json_when_workspace_present() -> None:
    req = TeamChatRequest(
        message="hi",
        model="gpt-4",
        workspace_root="/tmp",
        tool_context={"extra": 1},
    )
    ctx = _runtime_context(req)
    assert "workspace_root" in ctx
    assert "tool_context" in ctx


def test_runtime_context_returns_fallback_when_empty() -> None:
    req = TeamChatRequest(message="hi", model="gpt-4")
    assert _runtime_context(req) == "No workspace context was provided."


# ---------------------------------------------------------------------------
# Tool context
# ---------------------------------------------------------------------------


def test_agent_tool_context_populates_required_keys(
    request_fixture: TeamChatRequest, agent: TeamAgentConfig
) -> None:
    ctx = _agent_tool_context(request_fixture, "run-1", agent, 2, "debate")
    assert ctx["team_run_id"] == "run-1"
    assert ctx["agent_id"] == "agent-1"
    assert ctx["agent_name"] == "Alice"
    assert ctx["round"] == 2
    assert ctx["phase"] == "debate"


def test_agent_tool_context_propagates_workspace_root(
    team: TeamConfig, agent: TeamAgentConfig
) -> None:
    req = TeamChatRequest(
        message="hi",
        model="gpt-4",
        workspace_root="/tmp",
    )
    ctx = _agent_tool_context(req, "run-1", agent, 1, "independent")
    assert ctx.get("workspace_root") == "/tmp"
    assert ctx.get("cwd") == "/tmp"
    assert ctx.get("allowed_roots") == ["/tmp"]


# ---------------------------------------------------------------------------
# Workspace id
# ---------------------------------------------------------------------------


def test_workspace_id_extracts_from_tool_context() -> None:
    req = TeamChatRequest(
        message="hi",
        model="gpt-4",
        tool_context={"workspace_id": "/home/user"},
    )
    assert _workspace_id(req) == "/home/user"


def test_workspace_id_falls_back_to_workspace_root() -> None:
    req = TeamChatRequest(
        message="hi",
        model="gpt-4",
        workspace_root="/tmp",
    )
    assert _workspace_id(req) == str(Path("/tmp").resolve())


def test_workspace_id_returns_none_when_missing() -> None:
    req = TeamChatRequest(message="hi", model="gpt-4")
    assert _workspace_id(req) is None


# ---------------------------------------------------------------------------
# Duration helper
# ---------------------------------------------------------------------------


def test_duration_ms_returns_non_negative_int() -> None:
    start = time.perf_counter()
    time.sleep(0.01)
    ms = _duration_ms(start)
    assert isinstance(ms, int)
    assert ms >= 10


# ---------------------------------------------------------------------------
# Tool phase event
# ---------------------------------------------------------------------------


def test_tool_phase_event_structure(agent: TeamAgentConfig) -> None:
    event = _tool_phase_event(
        "run-1", "conv-1", agent, 2, "debate", TOOL_PHASE_PLAN, calls=[{"id": "1"}]
    )
    assert event["event"] == "tool_phase"
    assert event["run_id"] == "run-1"
    assert event["tool_phase"] == TOOL_PHASE_PLAN
    assert event["calls"] == [{"id": "1"}]
    assert event["results"] == []


# ---------------------------------------------------------------------------
# Tool proposal
# ---------------------------------------------------------------------------


def test_tool_proposal_structure() -> None:
    raw = {"id": "tc-1", "function": {"name": "Write"}}
    proposal = _tool_proposal(raw, reason="needs approval")
    assert proposal["tool_name"] == "Write"
    assert proposal["mutating"] is True
    assert "needs approval" in proposal["summary"]


def test_tool_proposal_fallback_name() -> None:
    raw = {"id": "tc-1"}
    proposal = _tool_proposal(raw, reason="x")
    assert proposal["tool_name"] == "tool"


# ---------------------------------------------------------------------------
# Tool result payload
# ---------------------------------------------------------------------------


def test_tool_result_payload_structure() -> None:
    result = ToolResult(
        tool_call_id="tc-1",
        tool_name="Read",
        status=ToolExecutionStatus.COMPLETED,
        content="hello",
        data={"content": "hello"},
    )
    payload = _tool_result_payload(result)
    assert payload["tool_call_id"] == "tc-1"
    assert payload["status"] == "completed"
    assert payload["is_error"] is False
    assert "hello" in payload["content"]


# ---------------------------------------------------------------------------
# Unique tool call ids
# ---------------------------------------------------------------------------


def test_unique_tool_call_ids_generates_ids_when_missing() -> None:
    calls = [{}, {}]
    out = _unique_tool_call_ids(calls, round_index=1, agent_id="a")
    assert out[0]["id"].startswith("team-tool-1-a-0")
    assert out[1]["id"].startswith("team-tool-1-a-1")


def test_unique_tool_call_ids_deduplicates() -> None:
    calls = [{"id": "x"}, {"id": "x"}]
    out = _unique_tool_call_ids(calls, round_index=1, agent_id="a")
    assert out[0]["id"] == "x"
    assert out[1]["id"] == "x-1"
    assert out[0]["extra_content"]["agent_id"] == "a"


# ---------------------------------------------------------------------------
# Turn text
# ---------------------------------------------------------------------------


def test_turn_text_strips_content() -> None:
    assert _turn_text("  hello  ", "reasoning") == "hello"


# ---------------------------------------------------------------------------
# Claim graph output contract
# ---------------------------------------------------------------------------


def test_claim_graph_output_contract_contains_expected_keys() -> None:
    contract = _claim_graph_output_contract()
    assert "claims" in contract
    assert "coherency_score" in contract
    assert "proposals" in contract


# ---------------------------------------------------------------------------
# Turn coherency score
# ---------------------------------------------------------------------------


def test_turn_coherency_score_fallback() -> None:
    blackboard = MagicMock()
    blackboard.snapshot.return_value = {"execution_contract": None}
    score = _turn_coherency_score("plain text", "hi", blackboard)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_turn_coherency_score_extracts_from_json() -> None:
    blackboard = MagicMock()
    score = _turn_coherency_score('{"coherency_score": 0.75}', "hi", blackboard)
    assert score == 0.75


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_is_relative_to_true_when_inside_root() -> None:
    assert _is_relative_to(Path("/tmp/foo/bar"), Path("/tmp/foo")) is True


def test_is_relative_to_false_when_outside_root() -> None:
    assert _is_relative_to(Path("/tmp/other"), Path("/tmp/foo")) is False


def test_resolve_allowed_path_rejects_outside_roots(tmp_path: Path) -> None:
    real_outside = Path("/tmp")
    if str(tmp_path.resolve()) == str(real_outside.resolve()):
        real_outside = Path("/var")
    with pytest.raises(ValueError, match="Tool path is outside configured roots"):
        _resolve_allowed_path(str(real_outside), tmp_path, (tmp_path,))


def test_resolve_allowed_path_accepts_relative_paths(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    resolved = _resolve_allowed_path("sub", tmp_path, (tmp_path,))
    assert resolved == sub.resolve()


# ---------------------------------------------------------------------------
# Tool use context from request
# ---------------------------------------------------------------------------


def test_tool_use_context_from_request_structure() -> None:
    req = TeamChatRequest(message="hi", model="gpt-4", workspace_root="/tmp")
    conv = Conversation()
    config = ToolRuntimeConfig.from_values(workspace_root="/tmp")
    raw_ctx = {"workspace_root": "/tmp", "agent_id": "a1"}
    ctx = _tool_use_context_from_request(
        request=req, conversation=conv, raw_context=raw_ctx, config=config
    )
    assert ctx.conversation_id == str(conv.id)
    assert ctx.permissions["mode"] == "team_guarded_autonomy"
    assert ctx.metadata["agent_id"] == "a1"
    assert ctx.workspace_root == Path("/tmp").resolve()


def test_tool_use_context_allows_custom_roots() -> None:
    req = TeamChatRequest(message="hi", model="gpt-4")
    conv = Conversation()
    base = Path("/tmp")
    config = ToolRuntimeConfig.from_values(workspace_root="/tmp")
    raw_ctx = {"allowed_roots": [str(base)]}
    ctx = _tool_use_context_from_request(
        request=req, conversation=conv, raw_context=raw_ctx, config=config
    )
    assert base.resolve() in ctx.allowed_roots


# ---------------------------------------------------------------------------
# Blackboard event builders
# ---------------------------------------------------------------------------


def test_blackboard_event_structure(agent: TeamAgentConfig) -> None:
    entry = BlackboardEntry(
        sequence=1,
        phase="debate",
        round_index=2,
        agent=agent,
        event_type="turn",
        payload={"content": "hi"},
        created_at="2024-01-01T00:00:00",
    )
    event = _blackboard_event("run-1", "conv-1", entry)
    assert event["event"] == "blackboard_event"
    assert event["run_id"] == "run-1"
    assert event["agent_id"] == "agent-1"


def test_blackboard_snapshot_event_structure() -> None:
    blackboard = MagicMock()
    blackboard.snapshot.return_value = {"entries": []}
    event = _blackboard_snapshot_event("run-1", "conv-1", 3, blackboard)
    assert event["event"] == "blackboard_snapshot"
    assert event["round"] == 3
    assert event["snapshot"] == {"entries": []}


def test_claim_graph_delta_event_structure(agent: TeamAgentConfig) -> None:
    entry = BlackboardEntry(
        sequence=1,
        phase="debate",
        round_index=2,
        agent=agent,
        event_type="turn",
        payload={},
        created_at="2024-01-01T00:00:00",
    )
    blackboard = MagicMock()
    blackboard.claim_delta_for.return_value = {"added": []}
    event = _claim_graph_delta_event("run-1", "conv-1", entry, blackboard)
    assert event["event"] == "claim_graph_delta"
    assert event["delta"] == {"added": []}
    assert event["agent_name"] == "Alice"


def test_coverage_matrix_event_structure() -> None:
    blackboard = MagicMock()
    blackboard.coverage_matrix.return_value = [
        {"id": "c1", "status": "covered"},
        {"id": "c2", "status": "open"},
    ]
    event = _coverage_matrix_event("run-1", "conv-1", 2, blackboard)
    assert event["event"] == "coverage_matrix"
    assert event["coverage_complete"] == 1
    assert event["coverage_total"] == 2


def test_coherency_score_event_structure(agent: TeamAgentConfig) -> None:
    turn = TurnResult(
        agent=agent,
        round_index=2,
        phase="debate",
        content="hi",
        reasoning="",
        digest="",
        usage=None,
        duration_ms=100,
        first_token_ms=None,
        tool_context={},
        coherency_score=0.85,
    )
    blackboard = MagicMock()
    blackboard.coherency_summary.return_value = {}
    event = _coherency_score_event("run-1", "conv-1", turn, blackboard)
    assert event["event"] == "coherency_score"
    assert event["coherency_score"] == 0.85


# ---------------------------------------------------------------------------
# Cancelled event
# ---------------------------------------------------------------------------


def test_cancelled_event_structure() -> None:
    event = _cancelled_event("run-1", "conv-1")
    assert event["event"] == "team_run_cancelled"
    assert event["run_id"] == "run-1"
    assert "created_at" in event


# ---------------------------------------------------------------------------
# Workspace metadata
# ---------------------------------------------------------------------------


def test_apply_workspace_metadata_persists_workspace_root() -> None:
    conv = Conversation()
    _apply_workspace_metadata(conv, "/tmp", None)
    assert conv.metadata["workspace_root"] == "/tmp"


def test_apply_workspace_metadata_no_op_on_missing_context() -> None:
    conv = Conversation()
    _apply_workspace_metadata(conv, None, None)
    assert "workspace_root" not in conv.metadata
