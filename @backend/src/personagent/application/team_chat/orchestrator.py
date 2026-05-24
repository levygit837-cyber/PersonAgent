"""Phase-based multi-agent team orchestration with a shared blackboard."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncIterator
from typing import Any, TypeAlias
from uuid import uuid4

import structlog

from personagent.application.services import SessionTitleService
from personagent.application.team_chat.agent_turn_runner import AgentTurnRunner
from personagent.application.team_chat.blackboard import (
    _Blackboard,
    _compact_workspace_memory,
    _now_iso,
    _parse_json_object,  # noqa: F401  # backward-compat for tests
)
from personagent.application.team_chat.consensus_phase import (
    ConsensusPhase,
    _consensus_snapshot,
    _fast_vote,
    _fast_vote_enabled,
    _parse_vote_payload,  # noqa: F401  # backward-compat for tests
    _vote_event,
)
from personagent.application.team_chat.contracts import (
    TeamChatRequest,
    TeamConfig,
    serialize_team_config,
    validate_team_config,
)
from personagent.application.team_chat.coordinator_phase import (
    CoordinatorPhase,
)
from personagent.application.team_chat.final_synthesis import FinalSynthesis
from personagent.application.team_chat.helpers import (
    COORDINATOR_PHASE,
    COORDINATOR_PLANNING_PHASE,
    DEBATE_PHASE,
    EXECUTION_CONTRACT_PHASE,
    INDEPENDENT_PHASE,
    VOTE_PHASE,
    _apply_workspace_metadata,
    _blackboard_event,
    _blackboard_snapshot_event,
    _cancelled_event,
    _claim_graph_delta_event,
    _coherency_score_event,
    _coverage_matrix_event,
    _duration_ms,
    _is_relative_to,  # noqa: F401  # backward-compat for tests
    _resolve_allowed_path,  # noqa: F401  # backward-compat for tests
    _team_policy_overlay,  # noqa: F401  # backward-compat for tests
    _workspace_id,
)
from personagent.application.team_chat.types import (
    BlackboardEntry,
    CoordinatorGuidance,
    ExecutionContract,
    QueuedTurnItem,
    ToolAudit,
    TurnResult,
    Vote,
)
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

SAFETY_TEAM_ROUND_CEILING: int = 25
"""Hard ceiling on team-mode rounds when ``team.max_rounds`` is ``None``.

Mirrors ``SAFETY_TOOL_ITERATION_CEILING`` in the chat completion path: when the
operator explicitly opts into "unbounded" rounds we still refuse to loop
forever, otherwise a non-converging debate could burn budget indefinitely.
"""

# Backward-compat aliases — existing tests import these names.
_TurnResult: TypeAlias = TurnResult
_Vote: TypeAlias = Vote
_CoordinatorGuidance: TypeAlias = CoordinatorGuidance
_ExecutionContract: TypeAlias = ExecutionContract
_ToolAudit: TypeAlias = ToolAudit
_BlackboardEntry: TypeAlias = BlackboardEntry
_QueuedTurnItem: TypeAlias = QueuedTurnItem



class TeamChatOrchestrator:
    """Runs Team Mode through independent, debate, vote, and coordinator phases."""

    def __init__(
        self,
        *,
        conversation_repo: ConversationRepository,
        llm_backend: LLMBackendRepository,
        tool_registry: ToolRegistry | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
        session_title_service: SessionTitleService | None = None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._llm_backend = llm_backend
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config
        self._session_title_service = session_title_service
        self._consensus_phase = ConsensusPhase(llm_backend=llm_backend)
        self._coordinator_phase = CoordinatorPhase(llm_backend=llm_backend)
        self._final_synthesis = FinalSynthesis(llm_backend=llm_backend)
        self._agent_turn_runner = AgentTurnRunner(
            llm_backend=llm_backend,
            tool_registry=tool_registry,
            tool_runtime_config=tool_runtime_config,
        )

    async def execute(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the team run and emit WebSocket-ready event payloads."""

        validate_team_config(team)
        cancel_event = cancel_event or asyncio.Event()
        run_id = f"team_{uuid4().hex}"
        conversation = await self._get_or_create_conversation(request)
        was_empty = len(conversation.messages) == 0
        user_msg = Message(role=Role.USER, content=request.message)
        conversation.add_message(user_msg)

        _conversation_persisted = False
        try:
            async for event in self._execute_generator(
                request=request,
                team=team,
                cancel_event=cancel_event,
                run_id=run_id,
                conversation=conversation,
                was_empty=was_empty,
                user_msg=user_msg,
            ):
                if event.get("event") in {"team_run_completed", "team_consensus_failed"}:
                    _conversation_persisted = True
                yield event
        finally:
            if not _conversation_persisted:
                try:
                    await self._conversation_repo.update(conversation)
                except Exception:
                    logger.exception("failed_to_persist_team_conversation_on_interrupt")

    async def _execute_generator(
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
        agent_by_id = {agent.id: agent for agent in team.agents}
        turns: list[_TurnResult] = []
        last_votes: list[_Vote] = []
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

        yield {
            "event": "team_run_started",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "team": serialize_team_config(team),
            "blackboard_mode": team.blackboard_mode,
            "tool_policy": team.tool_policy,
            "workspace_id": workspace_id,
            "team_memory_snapshot": _compact_workspace_memory(workspace_memory_snapshot or {}),
            "created_at": _now_iso(),
        }

        yield {
            "event": "coordinator_planning_started",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "round": 0,
            "phase": EXECUTION_CONTRACT_PHASE,
            "agent_id": team.coordinator.id,
            "agent_name": team.coordinator.name,
            "agent_role": team.coordinator.role,
            "created_at": _now_iso(),
        }
        contract = await self._coordinator_phase.run_execution_contract(
            request=request,
            team=team,
            blackboard=blackboard,
            run_id=run_id,
        )
        contract_entry = blackboard.publish_execution_contract(
            coordinator=team.coordinator,
            contract=contract,
        )
        yield {
            "event": "execution_contract",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "round": 0,
            "phase": EXECUTION_CONTRACT_PHASE,
            "agent_id": team.coordinator.id,
            "agent_name": team.coordinator.name,
            "agent_role": team.coordinator.role,
                "contract": {
                    "summary": contract.summary,
                    "objective": contract.objective,
                    "subproblems": contract.subproblems,
                    "success_criteria": contract.success_criteria,
                    "risks": contract.risks,
                    "coverage_matrix": contract.coverage_matrix,
                "focus_assignments": contract.focus_assignments,
            },
            "duration_ms": contract.duration_ms,
            "created_at": _now_iso(),
        }
        yield {
            "event": "coordinator_planning_completed",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "round": 0,
            "phase": EXECUTION_CONTRACT_PHASE,
            "agent_id": team.coordinator.id,
            "agent_name": team.coordinator.name,
            "agent_role": team.coordinator.role,
            "guidance": {
                "summary": contract.summary,
                "focus_assignments": contract.focus_assignments,
                "overlap_risks": contract.risks,
                "debate_goals": contract.success_criteria,
            },
            "duration_ms": contract.duration_ms,
            "created_at": _now_iso(),
        }
        yield _blackboard_event(run_id, conversation.id, contract_entry)
        yield _claim_graph_delta_event(run_id, conversation.id, contract_entry, blackboard)
        yield _coverage_matrix_event(run_id, conversation.id, 0, blackboard)
        yield _blackboard_snapshot_event(run_id, conversation.id, 0, blackboard)

        round_index = 1
        effective_round_cap = (
            team.max_rounds if team.max_rounds is not None else SAFETY_TEAM_ROUND_CEILING
        )
        while round_index <= effective_round_cap:
            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            phase = INDEPENDENT_PHASE if round_index == 1 else DEBATE_PHASE
            yield {
                "event": "round_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": phase,
                "created_at": _now_iso(),
            }

            skip_agent_turns = False
            if phase == DEBATE_PHASE:
                yield _blackboard_snapshot_event(run_id, conversation.id, round_index, blackboard)
                if blackboard.should_skip_debate():
                    yield {
                        "event": "debate_skipped",
                        "run_id": run_id,
                        "conversation_id": str(conversation.id),
                        "round": round_index,
                        "phase": phase,
                        "reason": "coverage_ready_no_conflict_or_blocker",
                        "coverage_ratio": round(blackboard.coverage_ratio(), 3),
                        "created_at": _now_iso(),
                    }
                    skip_agent_turns = True
                else:
                    yield {
                        "event": "coordinator_planning_started",
                        "run_id": run_id,
                        "conversation_id": str(conversation.id),
                        "round": round_index,
                        "phase": COORDINATOR_PLANNING_PHASE,
                        "agent_id": team.coordinator.id,
                        "agent_name": team.coordinator.name,
                        "agent_role": team.coordinator.role,
                        "created_at": _now_iso(),
                    }
                    guidance = await self._coordinator_phase.run_coordinator_planning(
                        request=request,
                        team=team,
                        round_index=round_index,
                        blackboard=blackboard,
                        run_id=run_id,
                    )
                    yield {
                        "event": "coordinator_planning_completed",
                        "run_id": run_id,
                        "conversation_id": str(conversation.id),
                        "round": round_index,
                        "phase": COORDINATOR_PLANNING_PHASE,
                        "agent_id": team.coordinator.id,
                        "agent_name": team.coordinator.name,
                        "agent_role": team.coordinator.role,
                        "guidance": {
                            "summary": guidance.summary,
                            "focus_assignments": guidance.focus_assignments,
                            "overlap_risks": guidance.overlap_risks,
                            "debate_goals": guidance.debate_goals,
                        },
                        "duration_ms": guidance.duration_ms,
                        "created_at": _now_iso(),
                    }
                    guidance_entry = blackboard.publish_coordinator_guidance(
                        coordinator=team.coordinator,
                        round_index=round_index,
                        guidance=guidance,
                    )
                    yield _blackboard_event(run_id, conversation.id, guidance_entry)
                    yield _claim_graph_delta_event(run_id, conversation.id, guidance_entry, blackboard)
                    for agent_id, redirect in guidance.redirects.items():
                        yield {
                            "event": "coordinator_redirect",
                            "run_id": run_id,
                            "conversation_id": str(conversation.id),
                            "round": round_index,
                            "phase": COORDINATOR_PLANNING_PHASE,
                            "agent_id": agent_id,
                            "redirect": redirect,
                            "created_at": _now_iso(),
                        }
                    yield _blackboard_snapshot_event(run_id, conversation.id, round_index, blackboard)
                    yield _coverage_matrix_event(run_id, conversation.id, round_index, blackboard)
                    yield {
                        "event": "debate_started",
                        "run_id": run_id,
                        "conversation_id": str(conversation.id),
                        "round": round_index,
                        "phase": phase,
                        "created_at": _now_iso(),
                    }

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

            yield {
                "event": "adaptive_vote",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": VOTE_PHASE,
                "triggers": vote_triggers,
                "scheduled": "scheduled_interval" in vote_triggers,
                "final_round": "final_round" in vote_triggers,
                "created_at": _now_iso(),
            }
            yield {
                "event": "vote_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": VOTE_PHASE,
                "vote_triggers": vote_triggers,
                "created_at": _now_iso(),
            }
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
            coordinator_started_at = time.perf_counter()
            yield {
                "event": "consensus_reached",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "consensus": consensus,
                "created_at": _now_iso(),
            }
            yield {
                "event": "coordinator_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "agent_id": team.coordinator.id,
                "agent_name": team.coordinator.name,
                "agent_role": team.coordinator.role,
                "phase": COORDINATOR_PHASE,
                "created_at": _now_iso(),
            }
            async for event in self._final_synthesis.synthesize_final(
                request=request,
                team=team,
                conversation=conversation,
                run_id=run_id,
                votes=last_votes,
                consensus=consensus,
                blackboard=blackboard,
                cancel_event=cancel_event,
            ):
                yield event
                if event.get("event") == "final_delta":
                    final_content_parts.append(str(event.get("content", "")))

            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            final_content = "".join(final_content_parts)
            yield {
                "event": "coordinator_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "agent_id": team.coordinator.id,
                "agent_name": team.coordinator.name,
                "agent_role": team.coordinator.role,
                "phase": COORDINATOR_PHASE,
                "content_length": len(final_content),
                "duration_ms": _duration_ms(coordinator_started_at),
                "created_at": _now_iso(),
            }
            blackboard_snapshot = blackboard.snapshot()
            team_memory_snapshot = blackboard.memory_snapshot(
                workspace_id=workspace_id,
                conversation_id=str(conversation.id),
                run_id=run_id,
            )
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
            yield {
                "event": "team_run_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "title": conversation.title,
                "final_output": final_content,
                "consensus": consensus,
                "blackboard_snapshot": blackboard_snapshot,
                "team_memory_snapshot": team_memory_snapshot,
                "created_at": _now_iso(),
            }
            return

        failure_consensus = _consensus_snapshot(team, last_votes)
        await self._conversation_repo.update(conversation)
        await self._refresh_session_title(conversation, was_empty=was_empty)
        yield {
            "event": "team_consensus_failed",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "reason": "max_rounds_without_consensus",
            "consensus": failure_consensus,
            "blackboard_snapshot": blackboard.snapshot(),
            "team_memory_snapshot": blackboard.memory_snapshot(
                workspace_id=workspace_id,
                conversation_id=str(conversation.id),
                run_id=run_id,
            ),
            "created_at": _now_iso(),
        }


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

