"""Phase-based multi-agent team orchestration with a shared blackboard."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypeAlias
from uuid import uuid4

import structlog

from personagent.application.services import SessionTitleService
from personagent.application.team_chat.agent_turn_runner import AgentTurnRunner
from personagent.application.team_chat.blackboard import (
    _Blackboard,
    _clamp_float,
    _coherency_score,
    _compact_workspace_memory,
    _digest,
    _now_iso,
    _parse_json_object,
)
from personagent.application.team_chat.consensus_phase import (
    ConsensusPhase,
    _consensus_snapshot,
    _fast_vote,
    _fast_vote_enabled,
    _parse_vote_payload,  # noqa: F401  # backward-compat for tests
    _vote_event,
    _votes_text,
)
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
    serialize_team_config,
    validate_team_config,
)
from personagent.application.team_chat.coordinator_phase import (
    CoordinatorPhase,
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
from personagent.domain.prompts.prompt import shared_runtime_policy_overlay
from personagent.domain.prompts.sections.states import render_agent_state_policy
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolExecutionStatus, ToolResult, ToolUseContext

logger = structlog.get_logger(__name__)

SAFETY_TEAM_ROUND_CEILING: int = 25
"""Hard ceiling on team-mode rounds when ``team.max_rounds`` is ``None``.

Mirrors ``SAFETY_TOOL_ITERATION_CEILING`` in the chat completion path: when the
operator explicitly opts into "unbounded" rounds we still refuse to loop
forever, otherwise a non-converging debate could burn budget indefinitely.
"""

INDEPENDENT_PHASE = "independent_round"
BLACKBOARD_PHASE = "blackboard_publish"
DEBATE_PHASE = "debate_round"
VOTE_PHASE = "vote"
EXECUTION_CONTRACT_PHASE = "execution_contract"
COORDINATOR_PLANNING_PHASE = "coordinator_planning"
COORDINATOR_PHASE = "coordinator_final"
TOOL_PHASE_PLAN = "plan_tools"
TOOL_PHASE_READ = "read_tools"
TOOL_PHASE_MUTATING_PROPOSAL = "mutating_proposal"
TOOL_PHASE_AUDIT = "tool_audit"

CLAIM_TYPES = ("claim", "evidence", "assumption", "risk", "blocker", "proposal", "tool_result", "decision")
MUTATING_TOOL_NAMES = {"Write", "Edit", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskClose", "TaskAppendOutput"}


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
            async for event in self._synthesize_final(
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

    async def _synthesize_final(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        votes: list[_Vote],
        consensus: dict[str, Any],
        blackboard: _Blackboard,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        async for chunk in self._llm_backend.chat_completion_stream(
            messages=self._final_messages(request, team, blackboard, votes, consensus),
            temperature=team.coordinator.temperature,
            max_tokens=min(team.coordinator.max_tokens, request.max_tokens)
            if request.max_tokens and request.max_tokens > 0
            else team.coordinator.max_tokens,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
            tool_context=_agent_tool_context(request, run_id, team.coordinator, 0, COORDINATOR_PHASE),
            tool_policy=team.tool_policy,
        ):
            if cancel_event.is_set():
                break
            if chunk.content or chunk.reasoning_content or chunk.usage:
                yield {
                    "event": "final_delta",
                    "run_id": run_id,
                    "conversation_id": str(conversation.id),
                    "phase": COORDINATOR_PHASE,
                    "agent_id": team.coordinator.id,
                    "agent_name": team.coordinator.name,
                    "content": chunk.content,
                    "reasoning_content": chunk.reasoning_content,
                    "is_thinking": chunk.is_thinking,
                    "usage": chunk.usage,
                    "created_at": _now_iso(),
                    "duration_ms": _duration_ms(started),
                }

    def _final_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: _Blackboard,
        votes: list[_Vote],
        consensus: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    f"{request.system_prompt or 'You synthesize the final answer for the user from a multi-agent team.'}\n\n"
                    f"Team mode is active. You are {team.coordinator.name}, role: {team.coordinator.role}.\n"
                    f"{team.coordinator.system_prompt}\n"
                    f"{_team_policy_overlay()}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Team: {team.name}\n"
                    f"Consensus: {json.dumps(consensus, ensure_ascii=False)}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Runtime context:\n{_runtime_context(request)}\n\n"
                    f"Blackboard snapshot:\n{blackboard.snapshot_text()}\n\n"
                    f"Votes and final points:\n{_votes_text(votes)}\n\n"
                    "Write the final report to the user from the Coordinator perspective. "
                    "Use the coverage_matrix, accepted claims, evidence, decisions, blockers, "
                    "tool actions/proposals, and coherency scores. Required final contract: "
                    "direct answer, decisions, evidence used, risks/blockers, actions executed "
                    "or proposed, remaining gaps, and coherency_score. If workspace memory is "
                    "present, include a concise memory/snapshot note explaining which decision "
                    "was reused, why it is relevant, and which irrelevant contamination was ignored. "
                    "Do not expose internal voting mechanics unless uncertainty is necessary."
                ),
            },
        ]


def _agent_system_prompt(
    request: TeamChatRequest,
    team: TeamConfig,
    agent: TeamAgentConfig,
) -> str:
    base = request.system_prompt or "You are part of a collaborative PersonAgent team."
    return (
        f"{base}\n\n"
        f"Team mode is active. Team: {team.name}. You are {agent.name}, role: {agent.role}.\n"
        f"{agent.system_prompt}\n"
        f"{_team_policy_overlay()}\n"
        "Tool policy: guarded autonomy. Read-only investigation can be autonomous; destructive "
        "or mutating actions must be proposed on the blackboard and require team coordination.\n"
        "Never claim to be the final answer. Your output is one blackboard contribution."
    )


def _team_policy_overlay() -> str:
    return "\n\n".join(
        (
            shared_runtime_policy_overlay(
                todo_available=True,
                parallel_tools_available=True,
            ),
            render_agent_state_policy(
                (
                    "intake",
                    "context_discovery",
                    "tool_execution",
                    "debug_recovery",
                    "runtime_validation",
                    "memory_recall",
                    "user_checkpoint",
                    "finalization",
                )
            ),
        )
    )


def _blackboard_event(
    run_id: str,
    conversation_id: Any,
    entry: _BlackboardEntry,
) -> dict[str, Any]:
    return {
        "event": "blackboard_event",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        **entry.to_event_payload(),
    }


def _blackboard_snapshot_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "blackboard_snapshot",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": BLACKBOARD_PHASE,
        "snapshot": blackboard.snapshot(),
        "created_at": _now_iso(),
    }


def _claim_graph_delta_event(
    run_id: str,
    conversation_id: Any,
    entry: _BlackboardEntry,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "claim_graph_delta",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": entry.round_index,
        "phase": entry.phase,
        "agent_id": entry.agent.id,
        "agent_name": entry.agent.name,
        "agent_role": entry.agent.role,
        "sequence": entry.sequence,
        "delta": blackboard.claim_delta_for(entry),
        "created_at": _now_iso(),
    }


def _coverage_matrix_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    matrix = blackboard.coverage_matrix()
    covered = sum(1 for item in matrix if item.get("status") == "covered")
    return {
        "event": "coverage_matrix",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": BLACKBOARD_PHASE,
        "coverage_matrix": matrix,
        "coverage_complete": covered,
        "coverage_total": len(matrix),
        "created_at": _now_iso(),
    }


def _coherency_score_event(
    run_id: str,
    conversation_id: Any,
    turn: _TurnResult,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "coherency_score",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": turn.round_index,
        "phase": turn.phase,
        "agent_id": turn.agent.id,
        "agent_name": turn.agent.name,
        "agent_role": turn.agent.role,
        "coherency_score": turn.coherency_score,
        "coherency": blackboard.coherency_summary(),
        "created_at": _now_iso(),
    }


def _runtime_context(request: TeamChatRequest) -> str:
    context: dict[str, Any] = {}
    if request.workspace_root:
        context["workspace_root"] = request.workspace_root
    if request.tool_context:
        context["tool_context"] = request.tool_context
    if not context:
        return "No workspace context was provided."
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:1200]


def _agent_tool_context(
    request: TeamChatRequest,
    run_id: str,
    agent: TeamAgentConfig,
    round_index: int,
    phase: str,
) -> dict[str, Any]:
    context = dict(request.tool_context or {})
    context.update(
        {
            "team_run_id": run_id,
            "run_id": run_id,
            "workspace_id": _workspace_id(request),
            "agent_id": agent.id,
            "agent_name": agent.name,
            "round": round_index,
            "phase": phase,
            "tool_policy": "guarded_autonomy",
            "tool_phase": phase,
        }
    )
    if request.workspace_root:
        context.setdefault("workspace_root", request.workspace_root)
        context.setdefault("cwd", request.workspace_root)
        context.setdefault("allowed_roots", [request.workspace_root])
    return context


def _tool_use_context_from_request(
    *,
    request: TeamChatRequest,
    conversation: Conversation,
    raw_context: dict[str, Any],
    config: ToolRuntimeConfig,
) -> ToolUseContext:
    raw_workspace_root = raw_context.get("workspace_root") or request.workspace_root
    workspace_root = (
        Path(str(raw_workspace_root)).expanduser().resolve()
        if raw_workspace_root
        else config.workspace_root.resolve()
    )
    root_scope = (workspace_root,) if raw_workspace_root else config.allowed_roots
    requested_roots = raw_context.get("allowed_roots")
    allowed_roots = root_scope
    if isinstance(requested_roots, list) and requested_roots:
        allowed_roots = tuple(
            _resolve_allowed_path(str(path), workspace_root, root_scope)
            for path in requested_roots
        )
    raw_cwd = raw_context.get("cwd")
    cwd = _resolve_allowed_path(str(raw_cwd), workspace_root, allowed_roots) if raw_cwd else workspace_root
    metadata = {
        "team_mode": True,
        "team_run_id": raw_context.get("team_run_id"),
        "workspace_id": raw_context.get("workspace_id"),
        "agent_id": raw_context.get("agent_id"),
        "agent_name": raw_context.get("agent_name"),
        "round": raw_context.get("round"),
        "phase": raw_context.get("phase"),
        "tool_phase": raw_context.get("tool_phase"),
        "request": raw_context,
    }
    return ToolUseContext(
        conversation_id=str(conversation.id),
        workspace_root=workspace_root,
        cwd=cwd,
        allowed_roots=allowed_roots,
        permissions={
            "mode": "team_guarded_autonomy",
            "team_mode": True,
            "agent_id": raw_context.get("agent_id"),
            "mutating_requires_consensus": True,
        },
        limits={
            "read_max_bytes": config.read_max_bytes,
            "read_default_limit": config.read_default_limit,
            "read_max_lines": config.read_max_lines,
            "search_timeout_ms": config.search_timeout_ms,
            "shell_timeout_ms": config.shell_timeout_ms,
            "web_timeout_ms": config.web_timeout_ms,
            "web_max_bytes": config.web_max_bytes,
            "max_tool_iterations": config.max_tool_iterations,
            "max_concurrency": config.max_concurrency,
            "result_max_chars": config.result_max_chars,
            "tool_result_storage_root": (
                str(config.tool_result_storage_root) if config.tool_result_storage_root else None
            ),
            "web_allowed_domains": config.web_allowed_domains,
            "web_blocked_domains": config.web_blocked_domains,
            "skill_roots": tuple(str(path) for path in config.skill_roots),
        },
        metadata=metadata,
    )


def _resolve_allowed_path(
    raw_path: str,
    base_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    path = Path(raw_path).expanduser()
    candidate = path if path.is_absolute() else base_root / path
    resolved = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise ValueError(f"Tool path is outside configured roots: {raw_path}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _tool_phase_event(
    run_id: str,
    conversation_id: Any,
    agent: TeamAgentConfig,
    round_index: int,
    phase: str,
    tool_phase: str,
    *,
    calls: list[dict[str, Any]] | None = None,
    results: list[dict[str, Any]] | None = None,
    proposals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "event": "tool_phase",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "tool_phase": tool_phase,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_role": agent.role,
        "calls": calls or [],
        "results": results or [],
        "proposals": proposals or [],
        "created_at": _now_iso(),
    }


def _tool_proposal(raw_call: dict[str, Any], *, reason: str) -> dict[str, Any]:
    function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    name = str(function.get("name") or raw_call.get("name") or "tool")
    return {
        "tool_call": raw_call,
        "tool_call_id": str(raw_call.get("id") or ""),
        "tool_name": name,
        "reason": reason,
        "summary": f"{name} requires Coordinator consensus before execution: {reason}",
        "mutating": True,
    }


def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
    result_summary = result.data.get("content") if isinstance(result.data, dict) else result.content
    return {
        "tool_call_id": result.tool_call_id,
        "tool_name": result.tool_name,
        "status": result.status.value
        if isinstance(result.status, ToolExecutionStatus)
        else str(result.status),
        "is_error": result.is_error,
        "content": _digest(result.content, 900),
        "summary": _digest(str(result_summary or ""), 400),
        "data": result.data,
        "metadata": result.metadata,
    }


def _unique_tool_call_ids(
    tool_calls: list[dict[str, Any]],
    *,
    round_index: int,
    agent_id: str,
) -> list[dict[str, Any]]:
    unique_calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tool_call in enumerate(tool_calls):
        original_id = str(tool_call.get("id") or "").strip()
        candidate = original_id or f"team-tool-{round_index}-{agent_id}-{index}"
        if candidate in seen:
            candidate = f"{candidate}-{index}"
        seen.add(candidate)
        next_call = dict(tool_call)
        next_call["id"] = candidate
        extra = next_call.get("extra_content")
        next_extra = dict(extra) if isinstance(extra, dict) else {}
        next_extra.update({"agent_id": agent_id, "round": round_index, "original_tool_call_id": original_id or None})
        next_call["extra_content"] = next_extra
        unique_calls.append(next_call)
    return unique_calls


def _turn_text(content: str, reasoning: str) -> str:
    return content.strip()


def _claim_graph_output_contract() -> str:
    return (
        "Return one compact JSON object only, no markdown fence, no prose outside JSON. "
        "Use keys: claims, evidence, assumptions, risks, blockers, proposals, decisions, "
        "coherency_score. Publish at most 6 total list items. Each item must include text, "
        "confidence, and coverage; optional supports, contradicts, depends_on. "
        "Use proposals for mutating/destructive tool actions. Keep every text under 220 chars."
    )


def _turn_coherency_score(content: str, user_input: str, blackboard: _Blackboard) -> float:
    structured = _parse_json_object(content) if content.strip().startswith(("{", "```")) else {}
    raw = structured.get("coherency_score")
    if isinstance(raw, (int, float)):
        return round(_clamp_float(raw, 0, 1), 3)
    return round(_coherency_score(content, user_input, blackboard.snapshot().get("execution_contract")), 3)


def _workspace_id(request: TeamChatRequest) -> str | None:
    raw = request.tool_context.get("workspace_id") if isinstance(request.tool_context, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    root = request.workspace_root or (
        request.tool_context.get("workspace_root")
        if isinstance(request.tool_context, dict)
        else None
    )
    if isinstance(root, str) and root.strip():
        return str(Path(root).expanduser().resolve())
    return None


def _cancelled_event(run_id: str, conversation_id: Any) -> dict[str, Any]:
    return {
        "event": "team_run_cancelled",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "created_at": _now_iso(),
    }


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _apply_workspace_metadata(
    conversation: Conversation,
    workspace_root: str | None,
    tool_context: dict[str, Any] | None,
) -> None:
    value = workspace_root or (tool_context or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        conversation.metadata["workspace_root"] = value.strip()
