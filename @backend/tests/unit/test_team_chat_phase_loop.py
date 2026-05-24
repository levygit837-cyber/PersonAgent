"""Unit tests for the team-chat outer phase loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.team_chat.contracts import TeamAgentConfig, TeamChatRequest, TeamConfig
from personagent.application.team_chat.phase_loop import TeamChatPhaseLoop
from personagent.domain.models.conversation import Conversation


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
    )


@pytest.fixture
def loop() -> TeamChatPhaseLoop:
    return TeamChatPhaseLoop(
        conversation_repo=AsyncMock(),
        consensus_phase=MagicMock(),
        coordinator_phase=MagicMock(),
        final_synthesis=MagicMock(),
        agent_turn_runner=MagicMock(),
    )


# ---------------------------------------------------------------------------
# _get_or_create_conversation
# ---------------------------------------------------------------------------


async def test_get_or_create_conversation_creates_new(loop: TeamChatPhaseLoop) -> None:
    req = TeamChatRequest(message="hi", model="gpt-4")
    loop._conversation_repo.get_by_id.return_value = None
    loop._conversation_repo.create = AsyncMock()

    conv = await loop._get_or_create_conversation(req)

    assert isinstance(conv, Conversation)
    loop._conversation_repo.create.assert_awaited_once()


async def test_get_or_create_conversation_fetches_existing(loop: TeamChatPhaseLoop) -> None:
    existing = Conversation()
    req = TeamChatRequest(message="hi", model="gpt-4", conversation_id=str(existing.id))
    loop._conversation_repo.get_by_id = AsyncMock(return_value=existing)

    conv = await loop._get_or_create_conversation(req)

    assert conv is existing
    loop._conversation_repo.get_by_id.assert_awaited_once_with(str(existing.id))


async def test_get_or_create_conversation_raises_when_missing(loop: TeamChatPhaseLoop) -> None:
    req = TeamChatRequest(message="hi", model="gpt-4", conversation_id="missing-uuid")
    loop._conversation_repo.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="missing-uuid not found"):
        await loop._get_or_create_conversation(req)


# ---------------------------------------------------------------------------
# _refresh_session_title
# ---------------------------------------------------------------------------


async def test_refresh_session_title_delegates_to_service(loop: TeamChatPhaseLoop) -> None:
    service = AsyncMock()
    loop._session_title_service = service
    conv = Conversation()

    await loop._refresh_session_title(conv, was_empty=True)

    service.refresh_title.assert_awaited_once()


async def test_refresh_session_title_fallback_when_empty(loop: TeamChatPhaseLoop) -> None:
    loop._session_title_service = None
    loop._conversation_repo.update = AsyncMock()
    conv = Conversation()

    await loop._refresh_session_title(conv, was_empty=True)

    assert conv.title is not None
    loop._conversation_repo.update.assert_awaited_once()


async def test_refresh_session_title_noop_when_not_empty(loop: TeamChatPhaseLoop) -> None:
    loop._session_title_service = None
    loop._conversation_repo.update = AsyncMock()
    conv = Conversation()
    conv.title = "Existing"

    await loop._refresh_session_title(conv, was_empty=False)

    loop._conversation_repo.update.assert_not_awaited()


# ---------------------------------------------------------------------------
# run — initial events
# ---------------------------------------------------------------------------


async def test_run_yields_team_run_started(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    loop._coordinator_phase.run_execution_contract.return_value.summary = "s"
    loop._coordinator_phase.run_execution_contract.return_value.objective = "o"
    loop._coordinator_phase.run_execution_contract.return_value.subproblems = []
    loop._coordinator_phase.run_execution_contract.return_value.success_criteria = []
    loop._coordinator_phase.run_execution_contract.return_value.risks = []
    loop._coordinator_phase.run_execution_contract.return_value.coverage_matrix = []
    loop._coordinator_phase.run_execution_contract.return_value.focus_assignments = {}
    loop._coordinator_phase.run_execution_contract.return_value.duration_ms = 100

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)
        if event["event"] == "team_run_started":
            break

    assert events[0]["event"] == "team_run_started"
    assert events[0]["run_id"] == "run-1"


async def test_run_yields_execution_contract(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract = AsyncMock(return_value=contract)

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)
        if event["event"] == "execution_contract":
            break

    assert any(e["event"] == "execution_contract" for e in events)


# ---------------------------------------------------------------------------
# run — consensus failure path (max rounds)
# ---------------------------------------------------------------------------


async def test_run_fails_without_consensus(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract

    loop._agent_turn_runner._run_agent_turns_parallel = MagicMock(return_value=empty_async_gen())
    loop._consensus_phase.run_vote = AsyncMock()

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)

    assert events[-1]["event"] == "team_consensus_failed"
    assert events[-1]["reason"] == "max_rounds_without_consensus"


# ---------------------------------------------------------------------------
# run — cancel event
# ---------------------------------------------------------------------------


async def test_run_respects_cancel_event(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    cancel = asyncio.Event()
    cancel.set()
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=cancel,
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)

    assert events[-1]["event"] == "team_run_cancelled"


async def test_run_debate_skipped_when_blackboard_ready(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract
    loop._agent_turn_runner._run_agent_turns_parallel = MagicMock(return_value=empty_async_gen())
    loop._consensus_phase.run_vote = AsyncMock()

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)
        if event["event"] == "debate_skipped":
            break

    assert any(e["event"] == "debate_skipped" for e in events)


async def test_run_executes_agent_turns(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract
    loop._agent_turn_runner._run_agent_turns_parallel = MagicMock(return_value=empty_async_gen())
    loop._consensus_phase.run_vote = AsyncMock()

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)

    loop._agent_turn_runner._run_agent_turns_parallel.assert_called_once()


async def test_run_reaches_consensus_and_synthesizes(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract

    loop._agent_turn_runner._run_agent_turns_parallel = MagicMock(return_value=empty_async_gen())

    vote = MagicMock()
    vote.approve = True
    vote.critical_blocker = False
    loop._consensus_phase.run_vote = AsyncMock(return_value=vote)

    loop._final_synthesis.synthesize_final = MagicMock(return_value=empty_async_gen())
    loop._conversation_repo.update = AsyncMock()

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)

    assert any(e["event"] == "consensus_reached" for e in events)
    loop._final_synthesis.synthesize_final.assert_called_once()


async def test_get_or_create_conversation_applies_workspace_metadata(loop: TeamChatPhaseLoop) -> None:
    req = TeamChatRequest(
        message="hi",
        model="gpt-4",
        workspace_root="/tmp",
        tool_context={"extra": 1},
    )
    loop._conversation_repo.get_by_id.return_value = None
    loop._conversation_repo.create = AsyncMock()

    conv = await loop._get_or_create_conversation(req)

    assert conv.metadata.get("workspace_root") == "/tmp"


async def test_run_yields_round_started(loop: TeamChatPhaseLoop, request_fixture: TeamChatRequest, team: TeamConfig) -> None:
    loop._coordinator_phase.run_execution_contract = AsyncMock()
    contract = MagicMock()
    contract.summary = "s"
    contract.objective = "o"
    contract.subproblems = []
    contract.success_criteria = []
    contract.risks = []
    contract.coverage_matrix = []
    contract.focus_assignments = {}
    contract.duration_ms = 100
    loop._coordinator_phase.run_execution_contract.return_value = contract
    loop._agent_turn_runner._run_agent_turns_parallel = MagicMock(return_value=empty_async_gen())
    loop._consensus_phase.run_vote = AsyncMock()

    conv = Conversation()
    events: list[dict[str, Any]] = []
    async for event in loop.run(
        request=request_fixture,
        team=team,
        cancel_event=asyncio.Event(),
        run_id="run-1",
        conversation=conv,
        was_empty=True,
        user_msg=MagicMock(),
    ):
        events.append(event)
        if event["event"] == "round_started":
            break

    assert any(e["event"] == "round_started" for e in events)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def empty_async_gen() -> AsyncIterator[tuple[dict[str, Any], Any]]:
    return
    yield
