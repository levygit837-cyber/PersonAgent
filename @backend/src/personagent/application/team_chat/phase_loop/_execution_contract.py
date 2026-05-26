"""Execution-contract phase generator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from personagent.application.team_chat.blackboard import _Blackboard
from personagent.application.team_chat.contracts import TeamChatRequest, TeamConfig
from personagent.application.team_chat.coordinator_phase import CoordinatorPhase
from personagent.application.team_chat.helpers import (
    EXECUTION_CONTRACT_PHASE,
    _blackboard_event,
    _blackboard_snapshot_event,
    _claim_graph_delta_event,
    _coverage_matrix_event,
)
from personagent.domain.models.conversation import Conversation

from ._events import (
    _coordinator_planning_completed_event,
    _coordinator_planning_started_event,
    _execution_contract_event,
)


async def _run_execution_contract_phase(
    coordinator_phase: CoordinatorPhase,
    *,
    request: TeamChatRequest,
    team: TeamConfig,
    blackboard: _Blackboard,
    run_id: str,
    conversation: Conversation,
) -> AsyncIterator[dict[str, Any]]:
    yield _coordinator_planning_started_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=0,
        phase=EXECUTION_CONTRACT_PHASE,
        coordinator=team.coordinator,
    )
    contract = await coordinator_phase.run_execution_contract(
        request=request,
        team=team,
        blackboard=blackboard,
        run_id=run_id,
    )
    contract_entry = blackboard.publish_execution_contract(
        coordinator=team.coordinator,
        contract=contract,
    )
    yield _execution_contract_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=0,
        coordinator=team.coordinator,
        contract=contract,
    )
    yield _coordinator_planning_completed_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=0,
        phase=EXECUTION_CONTRACT_PHASE,
        coordinator=team.coordinator,
        summary=contract.summary,
        focus_assignments=contract.focus_assignments,
        overlap_risks=contract.risks,
        debate_goals=contract.success_criteria,
        duration_ms=contract.duration_ms,
    )
    yield _blackboard_event(run_id, conversation.id, contract_entry)
    yield _claim_graph_delta_event(run_id, conversation.id, contract_entry, blackboard)
    yield _coverage_matrix_event(run_id, conversation.id, 0, blackboard)
    yield _blackboard_snapshot_event(run_id, conversation.id, 0, blackboard)
