"""Event payload builders for the team-chat phase loop."""

from __future__ import annotations

from typing import Any

from personagent.application.team_chat.blackboard import _Blackboard
from personagent.application.team_chat.blackboard_scoring import _now_iso
from personagent.application.team_chat.contracts import TeamAgentConfig
from personagent.application.team_chat.helpers import (
    COORDINATOR_PHASE,
    EXECUTION_CONTRACT_PHASE,
    VOTE_PHASE,
)


def _team_run_started_event(
    run_id: str,
    conversation_id: Any,
    serialized_team: dict[str, Any],
    blackboard_mode: str,
    tool_policy: str,
    workspace_id: str | None,
    compact_memory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "team_run_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "team": serialized_team,
        "blackboard_mode": blackboard_mode,
        "tool_policy": tool_policy,
        "workspace_id": workspace_id,
        "team_memory_snapshot": compact_memory,
        "created_at": _now_iso(),
    }


def _coordinator_planning_started_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
    coordinator: TeamAgentConfig,
) -> dict[str, Any]:
    return {
        "event": "coordinator_planning_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "agent_id": coordinator.id,
        "agent_name": coordinator.name,
        "agent_role": coordinator.role,
        "created_at": _now_iso(),
    }


def _execution_contract_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    coordinator: TeamAgentConfig,
    contract: Any,
) -> dict[str, Any]:
    return {
        "event": "execution_contract",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": EXECUTION_CONTRACT_PHASE,
        "agent_id": coordinator.id,
        "agent_name": coordinator.name,
        "agent_role": coordinator.role,
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


def _coordinator_planning_completed_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
    coordinator: TeamAgentConfig,
    summary: str,
    focus_assignments: dict[str, str],
    overlap_risks: list[str],
    debate_goals: list[str],
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "event": "coordinator_planning_completed",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "agent_id": coordinator.id,
        "agent_name": coordinator.name,
        "agent_role": coordinator.role,
        "guidance": {
            "summary": summary,
            "focus_assignments": focus_assignments,
            "overlap_risks": overlap_risks,
            "debate_goals": debate_goals,
        },
        "duration_ms": duration_ms,
        "created_at": _now_iso(),
    }


def _round_started_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
) -> dict[str, Any]:
    return {
        "event": "round_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "created_at": _now_iso(),
    }


def _debate_skipped_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
    coverage_ratio: float,
) -> dict[str, Any]:
    return {
        "event": "debate_skipped",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "reason": "coverage_ready_no_conflict_or_blocker",
        "coverage_ratio": coverage_ratio,
        "created_at": _now_iso(),
    }


def _coordinator_redirect_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
    agent_id: str,
    redirect: str,
) -> dict[str, Any]:
    return {
        "event": "coordinator_redirect",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "agent_id": agent_id,
        "redirect": redirect,
        "created_at": _now_iso(),
    }


def _debate_started_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    phase: str,
) -> dict[str, Any]:
    return {
        "event": "debate_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "created_at": _now_iso(),
    }


def _adaptive_vote_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    vote_triggers: list[str],
) -> dict[str, Any]:
    return {
        "event": "adaptive_vote",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": VOTE_PHASE,
        "triggers": vote_triggers,
        "scheduled": "scheduled_interval" in vote_triggers,
        "final_round": "final_round" in vote_triggers,
        "created_at": _now_iso(),
    }


def _vote_started_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    vote_triggers: list[str],
) -> dict[str, Any]:
    return {
        "event": "vote_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": VOTE_PHASE,
        "vote_triggers": vote_triggers,
        "created_at": _now_iso(),
    }


def _consensus_reached_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    consensus: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "consensus_reached",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "consensus": consensus,
        "created_at": _now_iso(),
    }


def _coordinator_started_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    coordinator: TeamAgentConfig,
) -> dict[str, Any]:
    return {
        "event": "coordinator_started",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "agent_id": coordinator.id,
        "agent_name": coordinator.name,
        "agent_role": coordinator.role,
        "phase": COORDINATOR_PHASE,
        "created_at": _now_iso(),
    }


def _coordinator_completed_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    coordinator: TeamAgentConfig,
    content_length: int,
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "event": "coordinator_completed",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "agent_id": coordinator.id,
        "agent_name": coordinator.name,
        "agent_role": coordinator.role,
        "phase": COORDINATOR_PHASE,
        "content_length": content_length,
        "duration_ms": duration_ms,
        "created_at": _now_iso(),
    }


def _team_run_completed_event(
    run_id: str,
    conversation_id: Any,
    title: str | None,
    final_output: str,
    consensus: dict[str, Any],
    blackboard_snapshot: dict[str, Any],
    team_memory_snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "team_run_completed",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "title": title,
        "final_output": final_output,
        "consensus": consensus,
        "blackboard_snapshot": blackboard_snapshot,
        "team_memory_snapshot": team_memory_snapshot,
        "created_at": _now_iso(),
    }


def _team_consensus_failed_event(
    run_id: str,
    conversation_id: Any,
    title: str | None,
    failure_consensus: dict[str, Any],
    blackboard: _Blackboard,
    workspace_id: str | None,
) -> dict[str, Any]:
    return {
        "event": "team_consensus_failed",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "title": title,
        "reason": "max_rounds_without_consensus",
        "consensus": failure_consensus,
        "blackboard_snapshot": blackboard.snapshot(),
        "team_memory_snapshot": blackboard.memory_snapshot(
            workspace_id=workspace_id,
            conversation_id=str(conversation_id),
            run_id=run_id,
        ),
        "created_at": _now_iso(),
    }
