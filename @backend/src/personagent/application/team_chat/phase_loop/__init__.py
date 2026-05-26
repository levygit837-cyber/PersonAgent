"""Outer phase loop that drives the team-chat execution flow.

This module owns the high-level sequence:
1. Execution contract (coordinator briefing)
2. Independent / debate rounds (agent turns + coordinator planning)
3. Consensus vote
4. Final synthesis

It yields WebSocket-ready event payloads throughout.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from typing import Any

from personagent.application.services import SessionTitleService
from personagent.application.team_chat.agent_turn_runner import AgentTurnRunner
from personagent.application.team_chat.blackboard import _Blackboard
from personagent.application.team_chat.blackboard_scoring import _compact_workspace_memory
from personagent.application.team_chat.consensus_phase import (
    ConsensusPhase,
    _consensus_snapshot,
    _fast_vote,
    _fast_vote_enabled,
    _vote_event,
)
from personagent.application.team_chat.contracts import (
    TeamChatRequest,
    TeamConfig,
    serialize_team_config,
)
from personagent.application.team_chat.coordinator_phase import CoordinatorPhase
from personagent.application.team_chat.final_synthesis import FinalSynthesis
from personagent.application.team_chat.helpers import (
    DEBATE_PHASE,
    INDEPENDENT_PHASE,
    _apply_workspace_metadata,
    _blackboard_event,
    _blackboard_snapshot_event,
    _cancelled_event,
    _claim_graph_delta_event,
    _coherency_score_event,
    _coverage_matrix_event,
    _duration_ms,
    _workspace_id,
)
from personagent.application.team_chat.types import (
    TurnResult,
    Vote,
)
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository

from ._consensus import _run_consensus_phase
from ._debate import _run_debate_phase
from ._events import (
    _adaptive_vote_event,
    _coordinator_completed_event,
    _round_started_event,
    _team_consensus_failed_event,
    _team_run_completed_event,
    _team_run_started_event,
    _vote_started_event,
)
from ._execution_contract import _run_execution_contract_phase

SAFETY_TEAM_ROUND_CEILING: int = 25
"""Hard ceiling on team-mode rounds when ``team.max_rounds`` is ``None``."""


class TeamChatPhaseLoop:
    """Runs the phase sequence: contract → rounds → vote → synthesis."""

    def __init__(
        self,
        *,
        conversation_repo: ConversationRepository,
        consensus_phase: ConsensusPhase,
        coordinator_phase: CoordinatorPhase,
        final_synthesis: FinalSynthesis,
        agent_turn_runner: AgentTurnRunner,
        session_title_service: SessionTitleService | None = None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._consensus_phase = consensus_phase
        self._coordinator_phase = coordinator_phase
        self._final_synthesis = final_synthesis
        self._agent_turn_runner = agent_turn_runner
        self._session_title_service = session_title_service

    async def run(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        cancel_event: asyncio.Event,
        run_id: str,
        conversation: Conversation,
        was_empty: bool,
        user_msg: Message,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the team run and emit WebSocket-ready event payloads."""
        agent_by_id = {agent.id: agent for agent in team.agents}
        turns: list[TurnResult] = []
        last_votes: list[Vote] = []
        final_content_parts: list[str] = []
        workspace_memory_snapshot = (
            request.tool_context.get("team_memory_snapshot")
            if isinstance(request.tool_context.get("team_memory_snapshot"), dict)
            else None
        )
        workspace_id = _workspace_id(request)
        blackboard = _Blackboard(
            team.blackboard_mode,
            user_input=request.message,
            workspace_memory_snapshot=workspace_memory_snapshot,
        )

        yield _team_run_started_event(
            run_id=run_id,
            conversation_id=conversation.id,
            serialized_team=serialize_team_config(team),
            blackboard_mode=team.blackboard_mode,
            tool_policy=team.tool_policy,
            workspace_id=workspace_id,
            compact_memory=_compact_workspace_memory(workspace_memory_snapshot or {}),
        )

        async for event in _run_execution_contract_phase(
            self._coordinator_phase,
            request=request,
            team=team,
            blackboard=blackboard,
            run_id=run_id,
            conversation=conversation,
        ):
            yield event

        round_index = 1
        effective_round_cap = (
            team.max_rounds if team.max_rounds is not None else SAFETY_TEAM_ROUND_CEILING
        )
        while round_index <= effective_round_cap:
            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            phase = INDEPENDENT_PHASE if round_index == 1 else DEBATE_PHASE
            yield _round_started_event(run_id, conversation.id, round_index, phase)

            skip_agent_turns = False
            if phase == DEBATE_PHASE:
                debate_result: dict[str, Any] = {}
                async for event in _run_debate_phase(
                    self._coordinator_phase,
                    request=request,
                    team=team,
                    blackboard=blackboard,
                    run_id=run_id,
                    conversation=conversation,
                    round_index=round_index,
                    debate_result=debate_result,
                ):
                    yield event
                skip_agent_turns = debate_result.get("skip_agent_turns", False)

            round_agents = [agent_by_id[agent_id] for agent_id in team.execution_order]
            if not skip_agent_turns:
                async for event, turn in self._agent_turn_runner._run_agent_turns_parallel(
                    request=request,
                    team=team,
                    conversation=conversation,
                    run_id=run_id,
                    agents=round_agents,
                    round_index=round_index,
                    phase=phase,
                    blackboard=blackboard,
                    cancel_event=cancel_event,
                ):
                    yield event
                    if turn is not None:
                        turns.append(turn)
                        entry = blackboard.publish_turn(turn)
                        yield _blackboard_event(run_id, conversation.id, entry)
                        yield _claim_graph_delta_event(run_id, conversation.id, entry, blackboard)
                        yield _coherency_score_event(run_id, conversation.id, turn, blackboard)

            yield _blackboard_snapshot_event(run_id, conversation.id, round_index, blackboard)
            yield _coverage_matrix_event(run_id, conversation.id, round_index, blackboard)

            vote_triggers = blackboard.vote_triggers(round_index, team)
            if not vote_triggers:
                round_index += 1
                continue

            yield _adaptive_vote_event(run_id, conversation.id, round_index, vote_triggers)
            yield _vote_started_event(run_id, conversation.id, round_index, vote_triggers)

            if _fast_vote_enabled(request) and blackboard.fast_vote_ready():
                last_votes = [
                    _fast_vote(agent_by_id[agent_id], blackboard)
                    for agent_id in team.execution_order
                ]
            else:
                last_votes = await asyncio.gather(
                    *[
                        self._consensus_phase.run_vote(
                            request, team, agent_by_id[agent_id], round_index, blackboard, run_id
                        )
                        for agent_id in team.execution_order
                    ]
                )
            for vote in last_votes:
                yield _vote_event(run_id, conversation.id, round_index, vote)

            required = math.ceil(len(team.agents) * team.consensus_threshold)
            approvals = sum(1 for vote in last_votes if vote.approve)
            has_critical_blocker = any(vote.critical_blocker for vote in last_votes)
            consensus_reached = approvals >= required and not has_critical_blocker
            if not consensus_reached:
                round_index += 1
                continue

            consensus = {
                "approvals": approvals,
                "required": required,
                "threshold": team.consensus_threshold,
                "critical_blocker": has_critical_blocker,
                "round": round_index,
            }

            consensus_result: dict[str, Any] = {}
            async for event in _run_consensus_phase(
                final_synthesis=self._final_synthesis,
                request=request,
                team=team,
                conversation=conversation,
                run_id=run_id,
                votes=last_votes,
                consensus=consensus,
                blackboard=blackboard,
                cancel_event=cancel_event,
                round_index=round_index,
                workspace_id=workspace_id,
                consensus_result=consensus_result,
            ):
                yield event
                if event.get("event") == "final_delta":
                    final_content_parts.append(str(event.get("content", "")))

            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            final_content = "".join(final_content_parts)
            yield _coordinator_completed_event(
                run_id=run_id,
                conversation_id=conversation.id,
                round_index=round_index,
                coordinator=team.coordinator,
                content_length=len(final_content),
                duration_ms=_duration_ms(consensus_result["coordinator_started_at"]),
            )
            blackboard_snapshot = consensus_result["blackboard_snapshot"]
            team_memory_snapshot = consensus_result["team_memory_snapshot"]
            conversation.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=final_content,
                    metadata={
                        "team_mode": True,
                        "run_id": run_id,
                        "team_id": team.id,
                        "consensus": consensus,
                        "blackboard_snapshot": blackboard_snapshot,
                        "team_memory_snapshot": team_memory_snapshot,
                    },
                )
            )
            await self._conversation_repo.update(conversation)
            await self._refresh_session_title(conversation, was_empty=was_empty)
            yield _team_run_completed_event(
                run_id=run_id,
                conversation_id=conversation.id,
                title=conversation.title,
                final_output=final_content,
                consensus=consensus,
                blackboard_snapshot=blackboard_snapshot,
                team_memory_snapshot=team_memory_snapshot,
            )
            return

        failure_consensus = _consensus_snapshot(team, last_votes)
        await self._conversation_repo.update(conversation)
        await self._refresh_session_title(conversation, was_empty=was_empty)
        yield _team_consensus_failed_event(
            run_id=run_id,
            conversation_id=conversation.id,
            title=conversation.title,
            failure_consensus=failure_consensus,
            blackboard=blackboard,
            workspace_id=workspace_id,
        )

    async def _get_or_create_conversation(self, request: TeamChatRequest) -> Conversation:
        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(request.conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation {request.conversation_id} not found")
            _apply_workspace_metadata(conversation, request.workspace_root, request.tool_context)
            return conversation
        conversation = Conversation()
        _apply_workspace_metadata(conversation, request.workspace_root, request.tool_context)
        await self._conversation_repo.create(conversation)
        return conversation

    async def _refresh_session_title(
        self,
        conversation: Conversation,
        *,
        was_empty: bool,
    ) -> None:
        if self._session_title_service is not None:
            await self._session_title_service.refresh_title(
                self._conversation_repo,
                conversation,
            )
            return
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)
