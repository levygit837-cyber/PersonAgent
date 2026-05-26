"""Debate-phase setup generator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from personagent.application.team_chat.blackboard.core import _Blackboard
from personagent.application.team_chat.contracts import TeamChatRequest, TeamConfig
from personagent.application.team_chat.helpers import (
    COORDINATOR_PLANNING_PHASE,
    DEBATE_PHASE,
    _blackboard_event,
    _blackboard_snapshot_event,
    _claim_graph_delta_event,
    _coverage_matrix_event,
)
from personagent.application.team_chat.phases.coordinator import CoordinatorPhase
from personagent.domain.conversation.models import Conversation

from ._events import (
    _coordinator_planning_completed_event,
    _coordinator_planning_started_event,
    _coordinator_redirect_event,
    _debate_skipped_event,
    _debate_started_event,
)


async def _run_debate_phase(
    coordinator_phase: CoordinatorPhase,
    *,
    request: TeamChatRequest,
    team: TeamConfig,
    blackboard: _Blackboard,
    run_id: str,
    conversation: Conversation,
    round_index: int,
    debate_result: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    yield _blackboard_snapshot_event(run_id, conversation.id, round_index, blackboard)
    if blackboard.should_skip_debate():
        yield _debate_skipped_event(
            run_id=run_id,
            conversation_id=conversation.id,
            round_index=round_index,
            phase=DEBATE_PHASE,
            coverage_ratio=round(blackboard.coverage_ratio(), 3),
        )
        debate_result["skip_agent_turns"] = True
        return

    yield _coordinator_planning_started_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=round_index,
        phase=COORDINATOR_PLANNING_PHASE,
        coordinator=team.coordinator,
    )
    guidance = await coordinator_phase.run_coordinator_planning(
        request=request,
        team=team,
        round_index=round_index,
        blackboard=blackboard,
        run_id=run_id,
    )
    yield _coordinator_planning_completed_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=round_index,
        phase=COORDINATOR_PLANNING_PHASE,
        coordinator=team.coordinator,
        summary=guidance.summary,
        focus_assignments=guidance.focus_assignments,
        overlap_risks=guidance.overlap_risks,
        debate_goals=guidance.debate_goals,
        duration_ms=guidance.duration_ms,
    )
    guidance_entry = blackboard.publish_coordinator_guidance(
        coordinator=team.coordinator,
        round_index=round_index,
        guidance=guidance,
    )
    yield _blackboard_event(run_id, conversation.id, guidance_entry)
    yield _claim_graph_delta_event(run_id, conversation.id, guidance_entry, blackboard)
    for agent_id, redirect in guidance.redirects.items():
        yield _coordinator_redirect_event(
            run_id=run_id,
            conversation_id=conversation.id,
            round_index=round_index,
            phase=COORDINATOR_PLANNING_PHASE,
            agent_id=agent_id,
            redirect=redirect,
        )
    yield _blackboard_snapshot_event(run_id, conversation.id, round_index, blackboard)
    yield _coverage_matrix_event(run_id, conversation.id, round_index, blackboard)
    yield _debate_started_event(
        run_id=run_id,
        conversation_id=conversation.id,
        round_index=round_index,
        phase=DEBATE_PHASE,
    )
    debate_result["skip_agent_turns"] = False
