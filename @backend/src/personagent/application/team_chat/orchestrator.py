"""Phase-based multi-agent team orchestration with a shared blackboard."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from personagent.application.services import SessionTitleService
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
    serialize_team_config,
    validate_team_config,
)
from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.prompts.prompt import shared_runtime_policy_overlay
from personagent.domain.prompts.sections.states import render_agent_state_policy
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolResult, ToolUseContext

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


@dataclass(frozen=True, slots=True)
class _TurnResult:
    agent: TeamAgentConfig
    round_index: int
    phase: str
    content: str
    reasoning: str
    digest: str
    usage: dict[str, int] | None
    duration_ms: int
    first_token_ms: int | None
    tool_context: dict[str, Any]
    coherency_score: float
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    tool_proposals: list[dict[str, Any]] = field(default_factory=list)
    blocker: str = ""


@dataclass(frozen=True, slots=True)
class _Vote:
    agent: TeamAgentConfig
    approve: bool
    confidence: float
    blocker: str
    critical_blocker: bool
    final_points: str
    duration_ms: int
    usage: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class _CoordinatorGuidance:
    summary: str
    focus_assignments: dict[str, str]
    overlap_risks: list[str]
    debate_goals: list[str]
    redirects: dict[str, str]
    raw_content: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _ExecutionContract:
    summary: str
    objective: str
    subproblems: list[dict[str, Any]]
    success_criteria: list[str]
    risks: list[str]
    coverage_matrix: list[dict[str, Any]]
    focus_assignments: dict[str, str]
    raw_content: str
    duration_ms: int


@dataclass(slots=True)
class _ToolAudit:
    calls: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _BlackboardEntry:
    sequence: int
    phase: str
    round_index: int
    agent: TeamAgentConfig
    event_type: str
    payload: dict[str, Any]
    created_at: str

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "phase": self.phase,
            "round": self.round_index,
            "agent_id": self.agent.id,
            "agent_name": self.agent.name,
            "agent_role": self.agent.role,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class _QueuedTurnItem:
    event: dict[str, Any] | None = None
    turn: _TurnResult | None = None
    error: BaseException | None = None
    done: bool = False


class _Blackboard:
    """In-memory claim graph and compact journal used during one Team Mode run."""

    def __init__(
        self,
        mode: str,
        *,
        user_input: str,
        workspace_memory_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self._mode = mode
        self._user_input = user_input
        self._workspace_memory_snapshot = workspace_memory_snapshot or {}
        self._entries: list[_BlackboardEntry] = []
        self._claim_nodes: list[dict[str, Any]] = []
        self._claim_signatures: set[str] = set()
        self._duplicates: list[dict[str, Any]] = []
        self._execution_contract: dict[str, Any] = {}
        self._coverage_matrix: list[dict[str, Any]] = []
        self._agent_novelty_scores: dict[str, list[float]] = {}
        self._next_sequence = 1

    def publish_execution_contract(
        self,
        *,
        coordinator: TeamAgentConfig,
        contract: _ExecutionContract,
    ) -> _BlackboardEntry:
        payload = {
            "summary": contract.summary,
            "objective": contract.objective,
            "subproblems": contract.subproblems,
            "success_criteria": contract.success_criteria,
            "risks": contract.risks,
            "coverage_matrix": contract.coverage_matrix,
            "focus_assignments": contract.focus_assignments,
            "duration_ms": contract.duration_ms,
            "raw_content": contract.raw_content,
        }
        self._execution_contract = {
            key: value for key, value in payload.items() if key not in {"duration_ms", "raw_content"}
        }
        self._coverage_matrix = _normalize_coverage_matrix(contract.coverage_matrix)
        entry = self._new_entry(
            phase=EXECUTION_CONTRACT_PHASE,
            round_index=0,
            agent=coordinator,
            event_type="execution_contract",
            payload=payload,
        )
        return entry

    def publish_turn(self, turn: _TurnResult) -> _BlackboardEntry:
        payload = _turn_blackboard_payload(turn)
        entry = self._new_entry(
            phase=turn.phase,
            round_index=turn.round_index,
            agent=turn.agent,
            event_type="agent_observation" if not turn.blocker else "agent_blocker",
            payload=payload,
        )
        nodes = self._claim_nodes_from_turn(entry, turn)
        payload["claim_nodes"] = nodes
        payload["claim_node_count"] = len(nodes)
        self._update_coverage(nodes)
        return entry

    def publish_coordinator_guidance(
        self,
        *,
        coordinator: TeamAgentConfig,
        round_index: int,
        guidance: _CoordinatorGuidance,
    ) -> _BlackboardEntry:
        payload = {
            "summary": guidance.summary,
            "focus_assignments": guidance.focus_assignments,
            "overlap_risks": guidance.overlap_risks,
            "debate_goals": guidance.debate_goals,
            "redirects": guidance.redirects,
            "duration_ms": guidance.duration_ms,
            "raw_content": guidance.raw_content,
        }
        return self._new_entry(
            phase=COORDINATOR_PLANNING_PHASE,
            round_index=round_index,
            agent=coordinator,
            event_type="coordinator_guidance",
            payload=payload,
        )

    def snapshot(self) -> dict[str, Any]:
        timeline = [entry.to_event_payload() for entry in self._entries]
        blockers = [
            entry.to_event_payload()
            for entry in self._entries
            if entry.event_type == "agent_blocker" or entry.payload.get("blocker")
        ]
        active_nodes = [node for node in self._claim_nodes if node.get("status") != "duplicate"]
        return {
            "mode": self._mode,
            "entry_count": len(self._entries),
            "latest_sequence": self._entries[-1].sequence if self._entries else 0,
            "timeline": timeline[-16:],
            "execution_contract": self._execution_contract,
            "workspace_memory": _compact_workspace_memory(self._workspace_memory_snapshot),
            "claim_graph": {
                "node_count": len(self._claim_nodes),
                "active_count": len(active_nodes),
                "duplicate_count": len(self._duplicates),
                "nodes": self._claim_nodes[-24:],
                "duplicates": self._duplicates[-8:],
                "conflicts": [
                    node
                    for node in active_nodes
                    if node.get("contradicts") or node.get("type") in {"risk", "blocker"}
                ][-8:],
                "novelty_by_agent": self.novelty_by_agent(),
            },
            "coverage_matrix": self.coverage_matrix(),
            "coherency": self.coherency_summary(),
            "agents": {
                entry.agent.id: {
                    "name": entry.agent.name,
                    "role": entry.agent.role,
                    "latest_summary": entry.payload.get("summary", ""),
                    "latest_round": entry.round_index,
                }
                for entry in self._entries
            },
            "decisions": [
                node["text"]
                for node in active_nodes
                if node.get("type") == "decision"
            ][-8:],
            "evidence": [
                node["text"]
                for node in active_nodes
                if node.get("type") in {"evidence", "tool_result"}
            ][-8:],
            "blockers": blockers[-8:],
        }

    def snapshot_text(self) -> str:
        snapshot = self.snapshot()
        if not snapshot["timeline"]:
            return "Blackboard is empty."
        lines = [
            f"Mode: {snapshot['mode']}",
            f"Entries: {snapshot['entry_count']}",
        ]
        contract = snapshot.get("execution_contract")
        if isinstance(contract, dict) and contract.get("objective"):
            lines.append(f"Objective: {str(contract['objective'])[:500]}")
            subproblems = contract.get("subproblems")
            if isinstance(subproblems, list) and subproblems:
                compact_subproblems = "; ".join(
                    f"{item.get('id')}: {item.get('owner_agent_id') or item.get('owner')}={str(item.get('description') or item.get('question') or '')[:120]}"
                    for item in subproblems[:8]
                    if isinstance(item, dict)
                )
                if compact_subproblems:
                    lines.append(f"Subproblems: {compact_subproblems}")
        coverage = snapshot.get("coverage_matrix")
        if isinstance(coverage, list) and coverage:
            compact_coverage = "; ".join(
                f"{item.get('id')}: {item.get('status')}"
                for item in coverage[:8]
                if isinstance(item, dict)
            )
            if compact_coverage:
                lines.append(f"Coverage: {compact_coverage}")
        claim_graph = snapshot.get("claim_graph") if isinstance(snapshot.get("claim_graph"), dict) else {}
        nodes = claim_graph.get("nodes") if isinstance(claim_graph, dict) else []
        if isinstance(nodes, list) and nodes:
            lines.append("Claim graph:")
            for node in nodes[-12:]:
                if not isinstance(node, dict):
                    continue
                lines.append(
                    "- "
                    f"{node.get('id')} {node.get('type')} "
                    f"{node.get('agent_id')} c={node.get('coherency_score')} n={node.get('novelty_score')}: "
                    f"{str(node.get('text') or '')[:260]}"
                )
        lines.append("Timeline:")
        for item in snapshot["timeline"][-8:]:
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            lines.append(
                "- "
                f"#{item.get('sequence')} round {item.get('round')} "
                f"{item.get('agent_name')} ({item.get('phase')}): "
                f"{payload.get('summary') or payload.get('blocker') or payload.get('objective') or 'No summary.'}"
            )
            focus_assignments = payload.get("focus_assignments")
            if isinstance(focus_assignments, dict):
                compact_focus = "; ".join(
                    f"{agent_id}: {str(focus)[:160]}"
                    for agent_id, focus in focus_assignments.items()
                    if str(focus).strip()
                )
                if compact_focus:
                    lines.append(f"  Focus assignments: {compact_focus}")
        if snapshot["blockers"]:
            lines.append("Blockers:")
            for item in snapshot["blockers"]:
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                lines.append(f"- {item.get('agent_name')}: {payload.get('blocker') or payload.get('summary')}")
        return "\n".join(lines)

    def latest_focus_for(self, agent_id: str) -> str:
        for entry in reversed(self._entries):
            if entry.event_type not in {"coordinator_guidance", "execution_contract"}:
                continue
            assignments = entry.payload.get("focus_assignments")
            if isinstance(assignments, dict):
                focus = assignments.get(agent_id)
                if isinstance(focus, str) and focus.strip():
                    return focus.strip()
        return ""

    def latest_lane_for(self, agent_id: str) -> dict[str, Any]:
        contract = self._execution_contract if isinstance(self._execution_contract, dict) else {}
        subproblems = contract.get("subproblems")
        if isinstance(subproblems, list):
            for item in subproblems:
                if not isinstance(item, dict):
                    continue
                owner = str(item.get("owner_agent_id") or item.get("owner") or "").strip()
                if owner == agent_id:
                    return item
        return {}

    def delta_guard_text(self, agent_id: str) -> str:
        active_nodes = [
            node
            for node in self._claim_nodes
            if node.get("status") != "duplicate"
            and node.get("agent_id") != agent_id
            and node.get("type") in {"claim", "evidence", "decision", "risk", "proposal", "blocker"}
        ]
        if not active_nodes:
            return "No previous claims yet."
        lines = ["Already covered by other agents. Do not restate these unless you contradict or refine them:"]
        for node in active_nodes[-10:]:
            lines.append(
                f"- {node.get('id')} {node.get('type')} coverage={node.get('coverage')}: "
                f"{str(node.get('text') or '')[:180]}"
            )
        return "\n".join(lines)

    def claim_delta_for(self, entry: _BlackboardEntry) -> dict[str, Any]:
        nodes = entry.payload.get("claim_nodes")
        if not isinstance(nodes, list):
            nodes = []
        return {
            "sequence": entry.sequence,
            "nodes": nodes,
            "node_count": len(nodes),
            "duplicates": [node for node in nodes if isinstance(node, dict) and node.get("status") == "duplicate"],
            "coverage_matrix": self.coverage_matrix(),
            "coherency": self.coherency_summary(),
        }

    def coverage_matrix(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._coverage_matrix]

    def coherency_summary(self) -> dict[str, Any]:
        active_nodes = [node for node in self._claim_nodes if node.get("status") != "duplicate"]
        values = [
            float(node.get("coherency_score", 0))
            for node in active_nodes
            if isinstance(node.get("coherency_score"), (int, float))
        ]
        average = sum(values) / len(values) if values else 1.0
        low_nodes = [
            node
            for node in active_nodes
            if isinstance(node.get("coherency_score"), (int, float))
            and float(node.get("coherency_score", 0)) < 0.45
        ][-8:]
        return {
            "average": round(average, 3),
            "low_count": len(low_nodes),
            "low_nodes": low_nodes,
        }

    def novelty_by_agent(self) -> dict[str, float]:
        return {
            agent_id: round(sum(values) / len(values), 3)
            for agent_id, values in self._agent_novelty_scores.items()
            if values
        }

    def coverage_ratio(self) -> float:
        if not self._coverage_matrix:
            return 1.0
        covered = sum(1 for item in self._coverage_matrix if item.get("status") == "covered")
        return covered / len(self._coverage_matrix)

    def has_real_blocker(self) -> bool:
        return any(
            node.get("status") != "duplicate"
            and node.get("type") == "blocker"
            and _is_real_blocker_text(str(node.get("text") or ""))
            for node in self._claim_nodes
        )

    def has_conflict(self) -> bool:
        return any(
            node.get("status") != "duplicate"
            and bool(node.get("contradicts"))
            for node in self._claim_nodes
        )

    def has_mutating_proposal(self) -> bool:
        return any(
            node.get("status") != "duplicate"
            and node.get("type") == "proposal"
            and node.get("mutating")
            for node in self._claim_nodes
        )

    def should_skip_debate(self) -> bool:
        return (
            self.coverage_ratio() >= 0.85
            and not self.has_real_blocker()
            and not self.has_mutating_proposal()
            and not self.has_conflict()
        )

    def fast_vote_ready(self) -> bool:
        return self.coverage_ratio() >= 0.75 and not self.has_real_blocker() and not self.has_conflict()

    def vote_triggers(self, round_index: int, team: TeamConfig) -> list[str]:
        triggers: list[str] = []
        if round_index % team.vote_every_rounds == 0:
            triggers.append("scheduled_interval")
        if team.force_final_vote and team.max_rounds is not None and round_index == team.max_rounds:
            triggers.append("final_round")
        if self.has_real_blocker():
            triggers.append("blocker_present")
        if self.has_conflict():
            triggers.append("conflict_present")
        if self.has_mutating_proposal():
            triggers.append("mutating_proposal")
        return list(dict.fromkeys(triggers))

    def ballot_text(self) -> str:
        active_nodes = [node for node in self._claim_nodes if node.get("status") != "duplicate"]
        coverage_lines = [
            f"{item.get('id')}={item.get('status')}"
            for item in self._coverage_matrix[:10]
            if isinstance(item, dict)
        ]
        blockers = [
            node for node in active_nodes
            if node.get("type") == "blocker" and _is_real_blocker_text(str(node.get("text") or ""))
        ][-4:]
        proposals = [
            node for node in active_nodes
            if node.get("type") == "proposal" and node.get("mutating")
        ][-4:]
        conflicts = [
            node for node in active_nodes
            if node.get("contradicts") or node.get("type") == "risk"
        ][-4:]
        claims = [
            node for node in active_nodes
            if node.get("type") in {"claim", "decision", "evidence", "tool_result"}
        ][-10:]
        lines = [
            f"Objective: {str(self._execution_contract.get('objective') or self._user_input)[:300]}",
            f"Coverage ratio: {self.coverage_ratio():.2f} ({'; '.join(coverage_lines)})",
            f"Coherency: {self.coherency_summary().get('average')}",
            f"Novelty: {self.novelty_by_agent()}",
        ]
        if blockers:
            lines.append("Blockers: " + "; ".join(str(node.get("text") or "")[:160] for node in blockers))
        if proposals:
            lines.append("Mutating proposals: " + "; ".join(str(node.get("text") or "")[:160] for node in proposals))
        if conflicts:
            lines.append("Conflicts/risks: " + "; ".join(str(node.get("text") or "")[:160] for node in conflicts))
        if claims:
            lines.append("Accepted evidence/claims:")
            for node in claims:
                lines.append(
                    f"- {node.get('id')} {node.get('type')} coverage={node.get('coverage')} "
                    f"n={node.get('novelty_score')}: {str(node.get('text') or '')[:180]}"
                )
        return "\n".join(lines)

    def memory_snapshot(
        self,
        *,
        workspace_id: str | None,
        conversation_id: str | None,
        run_id: str,
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "run_id": run_id,
            "updated_at": _now_iso(),
            "execution_contract": snapshot.get("execution_contract") or {},
            "claim_graph": {
                "nodes": [
                    node
                    for node in self._claim_nodes
                    if node.get("status") != "duplicate" and node.get("type") != "assumption"
                ][-40:],
                "duplicate_count": len(self._duplicates),
            },
            "coverage_matrix": self.coverage_matrix(),
            "coherency": self.coherency_summary(),
            "novelty_by_agent": self.novelty_by_agent(),
            "decisions": snapshot.get("decisions", []),
            "evidence": snapshot.get("evidence", []),
            "blockers": snapshot.get("blockers", []),
        }

    def _new_entry(
        self,
        *,
        phase: str,
        round_index: int,
        agent: TeamAgentConfig,
        event_type: str,
        payload: dict[str, Any],
    ) -> _BlackboardEntry:
        entry = _BlackboardEntry(
            sequence=self._next_sequence,
            phase=phase,
            round_index=round_index,
            agent=agent,
            event_type=event_type,
            payload=payload,
            created_at=_now_iso(),
        )
        self._next_sequence += 1
        self._entries.append(entry)
        return entry

    def _claim_nodes_from_turn(
        self,
        entry: _BlackboardEntry,
        turn: _TurnResult,
    ) -> list[dict[str, Any]]:
        structured = _parse_json_object(turn.content) if turn.content.strip().startswith(("{", "```")) else {}
        nodes: list[dict[str, Any]] = []
        for claim_type in CLAIM_TYPES:
            raw_items = structured.get(f"{claim_type}s") or structured.get(claim_type)
            nodes.extend(
                self._normalize_claim_items(
                    raw_items,
                    claim_type=claim_type,
                    entry=entry,
                    turn=turn,
                )
            )
        for result in turn.tool_results:
            result_text = str(result.get("summary") or result.get("content") or result.get("tool_name") or "")
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="tool_result",
                    text=result_text,
                    confidence=0.8 if not result.get("is_error") else 0.2,
                    extra={
                        "tool_call_id": result.get("tool_call_id"),
                        "tool_name": result.get("tool_name"),
                        "coverage": [str(item.get("id")) for item in self._coverage_matrix if item.get("id")],
                    },
                )
            )
        for proposal in turn.tool_proposals:
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="proposal",
                    text=str(proposal.get("summary") or proposal.get("tool_name") or "Mutating tool proposal"),
                    confidence=0.6,
                    extra={"mutating": True, "tool_call": proposal},
                )
            )
        mutating_proposal_text = (
            "A mutating action was requested by the user and remains a proposal only; "
            "it must not execute until the Coordinator or consensus explicitly approves it."
        )
        mutating_proposal_signature = _claim_signature(mutating_proposal_text)
        if (
            _looks_mutating_text(self._user_input)
            and not any(node.get("type") == "proposal" and node.get("mutating") for node in nodes)
            and (
                not mutating_proposal_signature
                or mutating_proposal_signature not in self._claim_signatures
            )
        ):
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="proposal",
                    text=mutating_proposal_text,
                    confidence=0.65,
                    extra={
                        "mutating": True,
                        "coverage": self._infer_coverage_for_claim(self._user_input, turn.agent.id),
                    },
                )
            )
        if not nodes and not (turn.blocker or turn.digest):
            return []
        if not nodes:
            fallback_type = "blocker" if turn.blocker else "claim"
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type=fallback_type,
                    text=turn.blocker or turn.digest,
                    confidence=0.3 if turn.blocker else 0.55,
                )
            )
        accepted: list[dict[str, Any]] = []
        for index, node in enumerate(nodes, start=1):
            text = str(node.get("text") or "").strip()
            signature = _claim_signature(text)
            novelty_score = _novelty_score(text, self._claim_nodes)
            status = "active"
            if signature and signature in self._claim_signatures:
                status = "duplicate"
                duplicate_reason = "exact_signature"
            elif novelty_score < 0.35:
                status = "duplicate"
                duplicate_reason = "semantic_overlap"
            else:
                duplicate_reason = ""
            if status == "duplicate":
                duplicate = {
                    "id": f"n{entry.sequence}.{index}",
                    "agent_id": turn.agent.id,
                    "text": text[:500],
                    "sequence": entry.sequence,
                    "reason": duplicate_reason,
                    "novelty_score": round(novelty_score, 3),
                }
                self._duplicates.append(duplicate)
            elif signature:
                self._claim_signatures.add(signature)
            node.update(
                {
                    "id": f"n{entry.sequence}.{index}",
                    "status": status,
                    "novelty_score": round(novelty_score, 3),
                    "duplicate_reason": duplicate_reason or None,
                }
            )
            self._agent_novelty_scores.setdefault(turn.agent.id, []).append(novelty_score)
            self._claim_nodes.append(node)
            accepted.append(node)
        return accepted

    def _normalize_claim_items(
        self,
        raw_items: Any,
        *,
        claim_type: str,
        entry: _BlackboardEntry,
        turn: _TurnResult,
    ) -> list[dict[str, Any]]:
        if raw_items is None:
            return []
        if isinstance(raw_items, (str, int, float, bool)):
            raw_items = [raw_items]
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            return []
        nodes: list[dict[str, Any]] = []
        for raw in raw_items:
            if isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("summary") or raw.get("claim") or raw.get("content") or "").strip()
                confidence = _clamp_float(raw.get("confidence", turn.coherency_score), 0, 1)
                extra = {
                    "depends_on": _string_list(raw.get("depends_on")),
                    "supports": _string_list(
                        raw.get("supports")
                        or raw.get("support")
                        or raw.get("supported_by")
                        or raw.get("evidence")
                        or raw.get("evidence_ids")
                    ),
                    "contradicts": _string_list(
                        raw.get("contradicts")
                        or raw.get("conflicts")
                        or raw.get("conflicts_with")
                        or raw.get("opposes")
                    ),
                    "coverage": _string_list(
                        raw.get("coverage")
                        or raw.get("covers")
                        or raw.get("coverage_ids")
                        or raw.get("coverage_id")
                        or raw.get("coverage_matrix_ids")
                        or raw.get("cm")
                    ),
                }
            else:
                text = str(raw).strip()
                confidence = turn.coherency_score
                extra = {}
            if not text:
                continue
            if not extra.get("coverage"):
                extra["coverage"] = self._infer_coverage_for_claim(text, turn.agent.id)
                if extra["coverage"]:
                    extra["coverage_inferred"] = True
            if claim_type == "proposal" and _looks_mutating_text(text):
                extra["mutating"] = True
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type=claim_type,
                    text=text,
                    confidence=confidence,
                    extra=extra,
                )
            )
        return nodes

    def _claim_node(
        self,
        *,
        entry: _BlackboardEntry,
        turn: _TurnResult,
        claim_type: str,
        text: str,
        confidence: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = extra or {}
        coherency = _coherency_score(text, self._user_input, self._execution_contract)
        if turn.coherency_score > 0:
            coherency = max(coherency, turn.coherency_score * 0.6)
        if extra.get("coverage"):
            coherency = max(coherency, 0.68)
        if claim_type in {"evidence", "decision", "tool_result"}:
            coherency = max(coherency, 0.7)
        return {
            "type": claim_type if claim_type in CLAIM_TYPES else "claim",
            "text": _digest(text, 700),
            "agent_id": turn.agent.id,
            "agent_name": turn.agent.name,
            "round": entry.round_index,
            "phase": entry.phase,
            "confidence": round(_clamp_float(confidence, 0, 1), 3),
            "coherency_score": round(_clamp_float(coherency, 0, 1), 3),
            "depends_on": extra.get("depends_on", []),
            "supports": extra.get("supports", []),
            "contradicts": extra.get("contradicts", []),
            "coverage": extra.get("coverage", []),
            **{key: value for key, value in extra.items() if key not in {"depends_on", "supports", "contradicts", "coverage"}},
        }

    def _infer_coverage_for_claim(self, text: str, agent_id: str) -> list[str]:
        if not self._coverage_matrix:
            return []
        claim_terms = _keyword_set(text)
        matches: list[tuple[int, str]] = []
        for item in self._coverage_matrix:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            item_text = f"{item_id} {item.get('question', '')} {item.get('expected_output', '')}"
            item_terms = _keyword_set(item_text)
            score = len(claim_terms & item_terms)
            if str(item.get("owner_agent_id") or "").strip() == agent_id:
                score += 2
            if score > 0:
                matches.append((score, item_id))
        matches.sort(reverse=True)
        return [item_id for _, item_id in matches[:2]]

    def _update_coverage(self, nodes: list[dict[str, Any]]) -> None:
        if not self._coverage_matrix:
            return
        for item in self._coverage_matrix:
            item_text = f"{item.get('id', '')} {item.get('question', '')} {item.get('expected_output', '')}"
            item_terms = _keyword_set(item_text)
            if not item_terms:
                continue
            for node in nodes:
                if node.get("status") == "duplicate":
                    continue
                explicit = {value.lower() for value in _string_list(node.get("coverage"))}
                node_terms = _keyword_set(str(node.get("text") or ""))
                item_id = str(item.get("id") or "").lower()
                node_type = str(node.get("type") or "claim")
                generic_match = (
                    (item_id == "requirements" and node_type in {"claim", "evidence", "assumption"})
                    or (item_id == "risks" and node_type in {"risk", "blocker"})
                    or (item_id == "implementation" and node_type in {"claim", "proposal", "decision", "tool_result"})
                    or (item_id == "coherence" and node_type in {"claim", "evidence", "decision"})
                )
                matched = item_id in explicit or bool(item_terms & node_terms) or generic_match
                if not matched:
                    continue
                item["status"] = "covered"
                item.setdefault("agents", [])
                if node.get("agent_id") not in item["agents"]:
                    item["agents"].append(node.get("agent_id"))
                item.setdefault("evidence_node_ids", [])
                if node.get("id") not in item["evidence_node_ids"]:
                    item["evidence_node_ids"].append(node.get("id"))


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
        contract = await self._run_execution_contract(
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
                    guidance = await self._run_coordinator_planning(
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
                async for event, turn in self._run_agent_turns_parallel(
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
                        self._run_vote(request, team, agent_by_id[agent_id], round_index, blackboard, run_id)
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

    async def _run_agent_turns_parallel(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        agents: list[TeamAgentConfig],
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[tuple[dict[str, Any], _TurnResult | None]]:
        queue: asyncio.Queue[_QueuedTurnItem] = asyncio.Queue()

        async def run_one(agent: TeamAgentConfig) -> None:
            try:
                async for event, turn in self._run_agent_turn(
                    request=request,
                    team=team,
                    conversation=conversation,
                    run_id=run_id,
                    agent=agent,
                    round_index=round_index,
                    phase=phase,
                    blackboard=blackboard,
                    cancel_event=cancel_event,
                ):
                    await queue.put(_QueuedTurnItem(event=event, turn=turn))
            except Exception as exc:
                await queue.put(_QueuedTurnItem(error=exc))
            finally:
                await queue.put(_QueuedTurnItem(done=True))

        tasks = [asyncio.create_task(run_one(agent)) for agent in agents]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item.done:
                    remaining -= 1
                    continue
                if item.error is not None:
                    raise item.error
                if item.event is not None:
                    yield item.event, item.turn
        finally:
            if cancel_event.is_set():
                for task in tasks:
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_agent_turn(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[tuple[dict[str, Any], _TurnResult | None]]:
        started = time.perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        tool_context = _agent_tool_context(request, run_id, agent, round_index, phase)
        tool_schemas = self._tool_schemas_for_agent(request, agent)
        assistant_tool_calls: list[dict[str, Any]] | None = None
        yield (
            {
                "event": "agent_turn_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": phase,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_role": agent.role,
                "tool_context": tool_context,
                "started_at": _now_iso(),
            },
            None,
        )

        blocker = ""
        try:
            async for chunk in self._llm_backend.chat_completion_stream(
                messages=self._agent_messages(request, team, agent, round_index, phase, blackboard),
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
                model=request.model,
                provider=request.provider,
                reasoning_level=request.reasoning_level,
                reasoning_budget_tokens=request.reasoning_budget_tokens,
                tools=tool_schemas,
                tool_choice="auto" if tool_schemas else None,
                tools_enabled=agent.tools_enabled,
                tool_context=tool_context,
                tool_policy=team.tool_policy,
            ):
                if cancel_event.is_set():
                    break
                if first_token_at is None and (chunk.content or chunk.reasoning_content):
                    first_token_at = time.perf_counter()
                if chunk.content:
                    content_parts.append(chunk.content)
                if chunk.reasoning_content:
                    reasoning_parts.append(chunk.reasoning_content)
                if chunk.tool_calls:
                    assistant_tool_calls = _unique_tool_call_ids(
                        chunk.tool_calls,
                        round_index=round_index,
                        agent_id=agent.id,
                    )
                if chunk.usage:
                    usage = chunk.usage
                if chunk.content or chunk.reasoning_content:
                    yield (
                        {
                            "event": "agent_delta",
                            "run_id": run_id,
                            "conversation_id": str(conversation.id),
                            "round": round_index,
                            "phase": phase,
                            "agent_id": agent.id,
                            "agent_name": agent.name,
                            "content": chunk.content,
                            "reasoning_content": chunk.reasoning_content,
                            "is_thinking": chunk.is_thinking,
                            "created_at": _now_iso(),
                        },
                        None,
                    )
        except Exception as exc:
            blocker = f"{agent.name} failed during {phase}: {exc}"
            logger.warning("team_agent_turn_failed", agent_id=agent.id, phase=phase, error=str(exc))

        duration_ms = _duration_ms(started)
        first_token_ms = (
            int((first_token_at - started) * 1000) if first_token_at is not None else None
        )
        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        turn_content = _turn_text(content, reasoning)
        digest = blocker or _digest(turn_content)
        tool_audit = _ToolAudit()
        if assistant_tool_calls and not blocker:
            async for event in self._execute_agent_tools(
                request=request,
                conversation=conversation,
                run_id=run_id,
                agent=agent,
                round_index=round_index,
                phase=phase,
                raw_tool_context=tool_context,
                raw_tool_calls=assistant_tool_calls,
                audit=tool_audit,
            ):
                yield event, None
        coherency_score = _turn_coherency_score(turn_content, request.message, blackboard)
        turn = _TurnResult(
            agent=agent,
            round_index=round_index,
            phase=phase,
            content=turn_content,
            reasoning=reasoning,
            digest=digest,
            usage=usage,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms,
            tool_context=tool_context,
            coherency_score=coherency_score,
            tool_calls=assistant_tool_calls or [],
            tool_results=tool_audit.results,
            tool_proposals=tool_audit.proposals,
            blocker=blocker,
        )
        yield (
            {
                "event": "agent_turn_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "phase": phase,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "content": turn_content,
                "reasoning_content": reasoning,
                "digest": turn.digest,
                "usage": usage,
                "tool_context": tool_context,
                "coherency_score": coherency_score,
                "tool_calls": assistant_tool_calls or [],
                "tool_summary": {
                    "calls": len(tool_audit.calls),
                    "results": len(tool_audit.results),
                    "proposals": len(tool_audit.proposals),
                },
                "blocker": blocker or None,
                "status": "failed" if blocker else "completed",
                "completed_at": _now_iso(),
                "duration_ms": duration_ms,
                "first_token_ms": first_token_ms,
            },
            turn,
        )

    def _tool_schemas_for_agent(
        self,
        request: TeamChatRequest,
        agent: TeamAgentConfig,
    ) -> list[dict[str, Any]]:
        if not agent.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        return self._tool_registry.openai_schemas(
            allowed_tools=allowed_tools,
            cache_scope=f"team:{request.provider}:{request.model}:{agent.id}",
        )

    async def _execute_agent_tools(
        self,
        *,
        request: TeamChatRequest,
        conversation: Conversation,
        run_id: str,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        raw_tool_context: dict[str, Any],
        raw_tool_calls: list[dict[str, Any]],
        audit: _ToolAudit,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._tool_registry is None or self._tool_runtime_config is None:
            for raw_call in raw_tool_calls:
                proposal = _tool_proposal(raw_call, reason="tool runtime is not configured")
                audit.proposals.append(proposal)
            if audit.proposals:
                yield _tool_phase_event(
                    run_id,
                    conversation.id,
                    agent,
                    round_index,
                    phase,
                    TOOL_PHASE_MUTATING_PROPOSAL,
                    proposals=audit.proposals,
                )
            return

        calls = [ToolCall.from_openai(raw_call) for raw_call in raw_tool_calls]
        calls = [call for call in calls if call.id and call.name]
        if not calls:
            return
        audit.calls.extend(raw_tool_calls)
        yield _tool_phase_event(
            run_id,
            conversation.id,
            agent,
            round_index,
            phase,
            TOOL_PHASE_PLAN,
            calls=[call.to_openai() for call in calls],
        )

        read_calls: list[ToolCall] = []
        for call in calls:
            tool = self._tool_registry.get(call.name)
            if tool is None:
                audit.proposals.append(_tool_proposal(call.to_openai(), reason="unknown tool"))
                continue
            try:
                is_read_only = tool.is_read_only(call.arguments)
            except Exception:
                is_read_only = bool(tool.definition.is_read_only)
            if is_read_only:
                read_calls.append(call)
            else:
                audit.proposals.append(
                    _tool_proposal(
                        call.to_openai(),
                        reason="mutating or non-read-only tool requires Coordinator consensus",
                    )
                )

        if audit.proposals:
            yield _tool_phase_event(
                run_id,
                conversation.id,
                agent,
                round_index,
                phase,
                TOOL_PHASE_MUTATING_PROPOSAL,
                proposals=audit.proposals,
            )
        if not read_calls:
            yield _tool_phase_event(
                run_id,
                conversation.id,
                agent,
                round_index,
                phase,
                TOOL_PHASE_AUDIT,
                calls=[call.to_openai() for call in calls],
                proposals=audit.proposals,
            )
            return

        context = _tool_use_context_from_request(
            request=request,
            conversation=conversation,
            raw_context=raw_tool_context,
            config=self._tool_runtime_config,
        )
        orchestrator = ToolOrchestrator(self._tool_registry, self._tool_runtime_config)
        async for tool_event in orchestrator.execute(read_calls, context):
            metadata = tool_event.to_stream_metadata()
            metadata.update(
                {
                    "event": "tool_phase",
                    "run_id": run_id,
                    "conversation_id": str(conversation.id),
                    "round": round_index,
                    "phase": phase,
                    "tool_phase": TOOL_PHASE_READ,
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "agent_role": agent.role,
                    "created_at": _now_iso(),
                }
            )
            if tool_event.result is not None:
                audit.results.append(_tool_result_payload(tool_event.result))
            yield metadata

        yield _tool_phase_event(
            run_id,
            conversation.id,
            agent,
            round_index,
            phase,
            TOOL_PHASE_AUDIT,
            calls=[call.to_openai() for call in calls],
            results=audit.results,
            proposals=audit.proposals,
        )

    async def _run_vote(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        blackboard: _Blackboard,
        run_id: str,
    ) -> _Vote:
        started = time.perf_counter()
        try:
            result = await self._llm_backend.chat_completion(
                messages=self._vote_messages(request, team, agent, round_index, blackboard),
                temperature=0,
                max_tokens=agent.max_tokens,
                stream=False,
                model=request.model,
                provider=request.provider,
                reasoning_level=request.reasoning_level,
                reasoning_budget_tokens=request.reasoning_budget_tokens,
                tool_context=_agent_tool_context(request, run_id, agent, round_index, VOTE_PHASE),
                tool_policy=team.tool_policy,
            )
        except Exception as exc:
            logger.warning("team_agent_vote_failed", agent_id=agent.id, round=round_index, error=str(exc))
            return _Vote(
                agent=agent,
                approve=False,
                confidence=0.0,
                blocker=f"Vote failed for {agent.name}: {exc}",
                critical_blocker=False,
                final_points="Vote unavailable; Coordinator may proceed if quorum is still met.",
                duration_ms=_duration_ms(started),
                usage=None,
            )
        payload = _parse_vote_payload(result.content)
        return _Vote(
            agent=agent,
            approve=bool(payload.get("approve", False)),
            confidence=_clamp_float(payload.get("confidence", 0), 0, 1),
            blocker=str(payload.get("blocker", "") or ""),
            critical_blocker=bool(payload.get("critical_blocker", False)),
            final_points=str(payload.get("final_points", "") or ""),
            duration_ms=_duration_ms(started),
            usage=result.usage,
        )

    async def _run_execution_contract(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: _Blackboard,
        run_id: str,
    ) -> _ExecutionContract:
        started = time.perf_counter()
        result = await self._llm_backend.chat_completion(
            messages=self._execution_contract_messages(request, team, blackboard),
            temperature=team.coordinator.temperature,
            max_tokens=team.coordinator.max_tokens,
            stream=False,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
            tool_context=_agent_tool_context(
                request,
                run_id,
                team.coordinator,
                0,
                EXECUTION_CONTRACT_PHASE,
            ),
            tool_policy=team.tool_policy,
        )
        payload = _parse_json_object(result.content)
        focus_assignments = _coordinator_focus_assignments(payload, team)
        coverage_matrix = _coverage_matrix_from_payload(payload, team)
        subproblems = _normalize_subproblems(payload.get("subproblems"), team, coverage_matrix)
        objective = str(payload.get("objective") or request.message).strip()
        success_criteria = _string_list(payload.get("success_criteria")) or [
            "answer the user request directly",
            "cover risks, evidence, and actionable next steps",
            "avoid duplicated agent perspectives",
        ]
        return _ExecutionContract(
            summary=str(payload.get("summary") or "Coordinator created an execution contract."),
            objective=objective,
            subproblems=subproblems,
            success_criteria=success_criteria,
            risks=_string_list(payload.get("risks")),
            coverage_matrix=coverage_matrix,
            focus_assignments=focus_assignments,
            raw_content=result.content,
            duration_ms=_duration_ms(started),
        )

    async def _run_coordinator_planning(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        round_index: int,
        blackboard: _Blackboard,
        run_id: str,
    ) -> _CoordinatorGuidance:
        started = time.perf_counter()
        result = await self._llm_backend.chat_completion(
            messages=self._coordinator_planning_messages(request, team, round_index, blackboard),
            temperature=team.coordinator.temperature,
            max_tokens=team.coordinator.max_tokens,
            stream=False,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
            tool_context=_agent_tool_context(
                request,
                run_id,
                team.coordinator,
                round_index,
                COORDINATOR_PLANNING_PHASE,
            ),
            tool_policy=team.tool_policy,
        )
        payload = _parse_json_object(result.content)
        focus_assignments = _coordinator_focus_assignments(payload, team)
        return _CoordinatorGuidance(
            summary=str(
                payload.get("summary")
                or "Coordinator assigned debate focus areas to reduce duplicated reasoning."
            ),
            focus_assignments=focus_assignments,
            overlap_risks=_string_list(payload.get("overlap_risks")),
            debate_goals=_string_list(payload.get("debate_goals")),
            redirects=_coordinator_redirects(payload, team),
            raw_content=result.content,
            duration_ms=_duration_ms(started),
        )

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

    def _agent_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        phase: str,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        focus = blackboard.latest_focus_for(agent.id)
        lane = blackboard.latest_lane_for(agent.id)
        lane_text = ""
        if lane:
            lane_text = (
                "Your mandatory subproblem lane:\n"
                f"{json.dumps(lane, ensure_ascii=False)}\n\n"
            )
        delta_guard = blackboard.delta_guard_text(agent.id)
        focus_text = (
            f"Your Coordinator focus assignment:\n{focus}\n\n"
            if focus
            else ""
        )
        if phase == INDEPENDENT_PHASE:
            body = (
                f"User input:\n{request.message}\n\n"
                f"Round: {round_index}\n"
                f"Runtime context:\n{_runtime_context(request)}\n\n"
                f"Execution contract and workspace memory:\n{blackboard.snapshot_text()}\n\n"
                f"{lane_text}"
                f"{focus_text}"
                "This is the independent first pass. Do not assume, cite, or react to "
                "other agents. Follow your assigned focus and publish a distinct view "
                "for the shared claim_graph. You must cover your mandatory subproblem "
                "and include coverage ids for every claim. If the user asks for a conceptual "
                "evaluation and did not provide a concrete artifact, proceed with explicit "
                "assumptions instead of blocking the run.\n\n"
                f"{_claim_graph_output_contract()}"
            )
        else:
            body = (
                f"User input:\n{request.message}\n\n"
                f"Round: {round_index}\n"
                f"Runtime context:\n{_runtime_context(request)}\n\n"
                f"Blackboard snapshot:\n{blackboard.snapshot_text()}\n\n"
                f"{lane_text}"
                f"{focus_text}"
                f"Delta guard:\n{delta_guard}\n\n"
                "Debate only the compact blackboard delta. Publish only new information: "
                "critique, refinements, evidence, contradictions, blockers, or decisions that "
                "are not already covered. Repeated claims will be marked duplicate and penalized. "
                "Do not restate existing claims. If your lane is already covered, add a targeted "
                "coherence check or a missing risk with coverage ids. Treat missing optional examples "
                "as assumptions for conceptual questions, not blockers. Keep it concise.\n\n"
                f"{_claim_graph_output_contract()}"
            )
        return [
            {"role": "system", "content": _agent_system_prompt(request, team, agent)},
            {"role": "user", "content": body},
        ]

    def _execution_contract_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    f"{request.system_prompt or 'You coordinate a multi-agent team.'}\n\n"
                    f"Team mode is active. You are {team.coordinator.name}, role: {team.coordinator.role}.\n"
                    f"{team.coordinator.system_prompt}\n"
                    f"{_team_policy_overlay()}\n"
                    "You are authoritative for flow control. Before any agent answers, create "
                    "distinct work lanes so agents do not solve the same subproblem."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Team: {team.name}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Runtime context:\n{_runtime_context(request)}\n\n"
                    f"Workspace Team memory snapshot:\n{json.dumps(blackboard.snapshot().get('workspace_memory') or {}, ensure_ascii=False)}\n\n"
                    "Return only compact JSON with these keys:\n"
                    "- summary: one sentence strategy\n"
                    "- objective: the exact execution objective\n"
                    "- success_criteria: array of concrete criteria\n"
                    "- risks: array of likely blockers or failure modes\n"
                    "- subproblems: array of objects with id, description, required_output, owner_agent_id\n"
                    "- coverage_matrix: array of objects with id, question, expected_output, owner_agent_id\n"
                    "- focus_assignments: object keyed by every agent id with one distinct directive each\n\n"
                    "Every team agent id must appear in focus_assignments. Coverage items must cover "
                    "different perspectives, evidence needs, tool needs, risk checks, and final response needs. "
                    "Every agent must own exactly one mandatory subproblem; focus_assignments must reference "
                    "that subproblem id and define a non-overlapping deliverable."
                ),
            },
        ]

    def _coordinator_planning_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        round_index: int,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    f"{request.system_prompt or 'You coordinate a multi-agent team.'}\n\n"
                    f"Team mode is active. You are {team.coordinator.name}, role: {team.coordinator.role}.\n"
                    f"{team.coordinator.system_prompt}\n"
                    f"{_team_policy_overlay()}\n"
                    "Act as a real coordinator before debate. Detect overlap, assign distinct "
                    "focus areas, and steer agents away from duplicated reasoning."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Team: {team.name}\n"
                    f"Round: {round_index}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Runtime context:\n{_runtime_context(request)}\n\n"
                    f"Current Blackboard snapshot:\n{blackboard.snapshot_text()}\n\n"
                    "Return only compact JSON with these keys:\n"
                    "- summary: one sentence describing the coordination strategy\n"
                    "- overlap_risks: array of likely duplicated lines of thought\n"
                    "- focus_assignments: object keyed by agent id with one concise directive each\n"
                    "- debate_goals: array of concrete outcomes the next debate round must produce\n"
                    "- redirects: object keyed by agent id when an agent should change direction due to duplication, low coverage, or low coherency\n\n"
                    "Every agent id in the team must appear in focus_assignments. Assign concrete subproblems "
                    "and required outputs, not generic perspectives. Agents must publish deltas only."
                ),
            },
        ]

    def _vote_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You vote on whether the Coordinator can synthesize a useful final answer now. "
                    "Return only compact JSON with keys approve, confidence, blocker, "
                    "critical_blocker, final_points. Set approve=true when the blackboard has enough "
                    "evidence for an actionable answer, even if caveats or next steps remain. "
                    "Set critical_blocker=true only when synthesis would be unsafe, impossible, "
                    "or clearly misleading without more information. Ordinary missing refinements, "
                    "future metrics, optional hardening items, unavailable example artifacts for conceptual "
                    "questions, and mutating actions that can remain proposed but unexecuted are "
                    "blockers=false/critical_blocker=false "
                    "and should be placed in final_points as caveats. final_points must be a single "
                    "string under 360 characters, not an array."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Agent voting: {agent.name} ({agent.role})\n"
                    f"Team: {team.name}\n"
                    f"Round: {round_index}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Compact ballot:\n{blackboard.ballot_text()}\n\n"
                    "Vote from this ballot only. Do not produce analysis. JSON only."
                ),
            },
        ]

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


def _turn_blackboard_payload(turn: _TurnResult) -> dict[str, Any]:
    summary = turn.digest or ("Reasoning-only contribution." if turn.reasoning else "No visible output.")
    payload: dict[str, Any] = {
        "summary": summary,
        "phase": turn.phase,
        "duration_ms": turn.duration_ms,
        "first_token_ms": turn.first_token_ms,
        "tool_context": turn.tool_context,
        "coherency_score": turn.coherency_score,
        "tool_calls": turn.tool_calls,
        "tool_results": turn.tool_results,
        "tool_proposals": turn.tool_proposals,
    }
    if turn.blocker:
        payload["blocker"] = turn.blocker
    structured = _parse_json_object(turn.content) if turn.content.strip().startswith(("{", "```")) else {}
    for key in ("claims", "decisions", "evidence", "blockers", "proposals", "risks", "assumptions"):
        if key in structured:
            payload[key] = structured[key]
    return payload


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


def _should_vote(round_index: int, team: TeamConfig) -> bool:
    return round_index % team.vote_every_rounds == 0 or (
        team.force_final_vote and team.max_rounds is not None and round_index == team.max_rounds
    )


def _fast_vote_enabled(request: TeamChatRequest) -> bool:
    return request.provider.lower() not in {"llama", "test", "fake"}


def _votes_text(votes: list[_Vote]) -> str:
    if not votes:
        return "No votes."
    return "\n".join(
        (
            f"- {vote.agent.name}: approve={vote.approve}, confidence={vote.confidence:.2f}, "
            f"critical_blocker={vote.critical_blocker}, blocker={vote.blocker or 'none'}, "
            f"final_points={vote.final_points or 'none'}"
        )
        for vote in votes
    )


def _fast_vote(agent: TeamAgentConfig, blackboard: _Blackboard) -> _Vote:
    return _Vote(
        agent=agent,
        approve=True,
        confidence=0.82,
        blocker="",
        critical_blocker=False,
        final_points=(
            "Fast ballot: coverage is sufficient and no real blocker or contradiction is active. "
            "Coordinator should synthesize with caveats and keep mutating proposals unexecuted."
        ),
        duration_ms=0,
        usage=None,
    )


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


def _digest(content: str, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", str(content)).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rsplit(' ', 1)[0]}..."


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_json_fence(content)
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        candidates.insert(0, match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else {}
    return _parse_partial_claim_graph(text)


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text


def _parse_partial_claim_graph(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    key_aliases = {
        "claims": "claims",
        "evidence": "evidence",
        "evidences": "evidence",
        "assumptions": "assumptions",
        "risks": "risks",
        "blockers": "blockers",
        "proposals": "proposals",
        "tool_results": "tool_results",
        "decisions": "decisions",
    }
    for source_key, target_key in key_aliases.items():
        items = _extract_complete_json_objects_from_array(text, source_key)
        if items:
            payload.setdefault(target_key, []).extend(items)
    coherency_match = re.search(r'"coherency_score"\s*:\s*([0-9]*\.?[0-9]+)', text)
    if coherency_match:
        with suppress(ValueError):
            payload["coherency_score"] = _clamp_float(float(coherency_match.group(1)), 0, 1)
    return payload


def _extract_complete_json_objects_from_array(text: str, key: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*\[', flags=re.I)
    for match in pattern.finditer(text):
        depth = 0
        start: int | None = None
        in_string = False
        escape = False
        for index in range(match.end(), len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
                continue
            if char == "}":
                if depth <= 0:
                    continue
                depth -= 1
                if depth == 0 and start is not None:
                    raw_object = text[start : index + 1]
                    try:
                        parsed = json.loads(raw_object)
                    except json.JSONDecodeError:
                        start = None
                        continue
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start = None
                continue
            if char == "]" and depth == 0:
                break
    return objects


def _coverage_matrix_from_payload(payload: dict[str, Any], team: TeamConfig) -> list[dict[str, Any]]:
    matrix = _normalize_coverage_matrix(payload.get("coverage_matrix"))
    if matrix:
        return matrix
    defaults = [
        ("requirements", "What exactly must be answered?", "clear requirements and constraints", "analyst"),
        ("risks", "What can make the answer unsafe or incomplete?", "risks and blockers", "critic"),
        ("implementation", "What concrete plan or action should be proposed?", "actionable implementation path", "builder"),
        ("coherence", "Is the final answer coherent and complete?", "coherence check and final gaps", "reviewer"),
    ]
    agent_ids = {agent.id for agent in team.agents}
    return [
        {
            "id": item_id,
            "question": question,
            "expected_output": expected,
            "owner_agent_id": owner if owner in agent_ids else team.agents[index % len(team.agents)].id,
            "status": "open",
            "agents": [],
            "evidence_node_ids": [],
        }
        for index, (item_id, question, expected, owner) in enumerate(defaults)
    ]


def _normalize_coverage_matrix(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    matrix: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            matrix.append(
                {
                    "id": f"c{index}",
                    "question": item,
                    "expected_output": item,
                    "owner_agent_id": "",
                    "status": "open",
                    "agents": [],
                    "evidence_node_ids": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"c{index}").strip()
        matrix.append(
            {
                "id": item_id,
                "question": str(item.get("question") or item.get("objective") or item_id).strip(),
                "expected_output": str(item.get("expected_output") or item.get("output") or "").strip(),
                "owner_agent_id": str(item.get("owner_agent_id") or item.get("owner") or "").strip(),
                "status": str(item.get("status") or "open").strip() or "open",
                "agents": _string_list(item.get("agents")),
                "evidence_node_ids": _string_list(item.get("evidence_node_ids")),
            }
        )
    return matrix


def _normalize_subproblems(
    raw: Any,
    team: TeamConfig,
    coverage_matrix: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = [
            {"id": key, **value} if isinstance(value, dict) else {"id": key, "description": value}
            for key, value in raw.items()
        ]
    if not isinstance(raw, list):
        raw = []
    agent_ids = [agent.id for agent in team.agents]
    subproblems: list[dict[str, Any]] = []
    for index, agent_id in enumerate(agent_ids):
        source: Any = raw[index] if index < len(raw) else {}
        coverage_item = coverage_matrix[index % len(coverage_matrix)] if coverage_matrix else {}
        if isinstance(source, str):
            source = {"description": source}
        if not isinstance(source, dict):
            source = {}
        item_id = str(source.get("id") or coverage_item.get("id") or f"sp{index + 1}").strip()
        description = str(
            source.get("description")
            or source.get("question")
            or coverage_item.get("question")
            or _default_focus_for_agent(team.agents[index])
        ).strip()
        subproblems.append(
            {
                "id": item_id,
                "description": description,
                "required_output": str(
                    source.get("required_output")
                    or source.get("expected_output")
                    or coverage_item.get("expected_output")
                    or "one compact delta with coverage ids"
                ).strip(),
                "owner_agent_id": agent_id,
                "coverage_ids": _string_list(source.get("coverage_ids") or source.get("coverage"))
                or _string_list(coverage_item.get("id")),
            }
        )
    return subproblems


def _coordinator_focus_assignments(
    payload: dict[str, Any],
    team: TeamConfig,
) -> dict[str, str]:
    raw = payload.get("focus_assignments")
    assignments: dict[str, str] = {}
    if isinstance(raw, dict):
        for agent in team.agents:
            value = raw.get(agent.id) or raw.get(agent.name)
            if isinstance(value, str) and value.strip():
                assignments[agent.id] = value.strip()
    for agent in team.agents:
        assignments.setdefault(agent.id, _default_focus_for_agent(agent))
    return assignments


def _coordinator_redirects(payload: dict[str, Any], team: TeamConfig) -> dict[str, str]:
    raw = payload.get("redirects")
    redirects: dict[str, str] = {}
    if isinstance(raw, dict):
        for agent in team.agents:
            value = raw.get(agent.id) or raw.get(agent.name)
            if isinstance(value, str) and value.strip():
                redirects[agent.id] = value.strip()
    return redirects


def _default_focus_for_agent(agent: TeamAgentConfig) -> str:
    role = agent.role.lower()
    if "risk" in role or "critic" in agent.id:
        return "Challenge weak assumptions, identify blockers, and avoid repeating baseline analysis."
    if "solution" in role or "builder" in agent.id:
        return "Convert the strongest evidence into a concrete execution path."
    if "review" in role or "reviewer" in agent.id:
        return "Check coherence, missing evidence, and final-readiness criteria."
    return "Clarify requirements, constraints, evidence, and the direct answer path."


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


def _coherency_score(text: str, user_input: str, execution_contract: Any) -> float:
    text_terms = _keyword_set(text)
    if not text_terms:
        return 0.0
    target_text = user_input
    if isinstance(execution_contract, dict):
        target_text = " ".join(
            str(value)
            for value in (
                execution_contract.get("objective"),
                execution_contract.get("summary"),
                " ".join(_string_list(execution_contract.get("success_criteria"))),
            )
            if value
        ) or user_input
    target_terms = _keyword_set(target_text)
    if not target_terms:
        return 0.5
    overlap = len(text_terms & target_terms) / max(1, min(len(text_terms), len(target_terms)))
    return _clamp_float(0.25 + overlap, 0, 1)


def _claim_signature(text: str) -> str:
    terms = sorted(_keyword_set(text))
    return " ".join(terms[:18])


def _novelty_score(text: str, existing_nodes: list[dict[str, Any]]) -> float:
    terms = _keyword_set(text)
    if not terms:
        return 0.0
    max_overlap = 0.0
    for node in existing_nodes:
        if node.get("status") == "duplicate":
            continue
        other_terms = _keyword_set(str(node.get("text") or ""))
        if not other_terms:
            continue
        overlap = len(terms & other_terms) / max(1, len(terms | other_terms))
        max_overlap = max(max_overlap, overlap)
    return _clamp_float(1.0 - max_overlap, 0.0, 1.0)


def _is_real_blocker_text(text: str) -> bool:
    normalized = text.lower().strip()
    if not normalized:
        return False
    false_signals = (
        "vote response was not valid json",
        "partially parsed",
        "no blocker",
        "blocker=false",
        "no blocker",
        "no blocking issue",
        "no block",
        "missing domain",
        "example question",
        "missing read result",
        "missing tool_result",
        "need to execute the read tool",
        "missing read content",
        "missing automatic signaling",
        "lack of automatic signaling",
        "missing opinion-based answer text",
        "regional data scarcity",
        "missing concrete citations",
        "explicit approval token",
        "verifiable signature",
        "missing unique identifier",
        "missing standardized parser",
        "missing quantitative metrics",
        "missing asynchronous notification mechanism",
        "missing standardized metadata",
        "does not list exhaustively",
        "possible visual tags",
    )
    return not any(signal in normalized for signal in false_signals)


def _looks_mutating_text(text: str) -> bool:
    normalized = text.lower()
    return any(
        token in normalized
        for token in (
            "write",
            "edit",
            "delete",
            "remove",
            "mutating",
            "migra",
        )
    )


def _keyword_set(text: str) -> set[str]:
    stopwords = {
        "para",
        "como",
        "com",
        "uma",
        "que",
        "the",
        "and",
        "this",
        "that",
        "agent",
        "agents",
        "team",
        "mode",
        "blackboard",
    }
    return {
        word
        for word in re.findall(r"[a-zA-Z0-9_]{4,}", str(text).lower())
        if word not in stopwords
    }


def _compact_workspace_memory(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot:
        return {}
    claim_graph = snapshot.get("claim_graph") if isinstance(snapshot.get("claim_graph"), dict) else {}
    nodes = claim_graph.get("nodes") if isinstance(claim_graph, dict) else []
    if not isinstance(nodes, list) or not nodes:
        raw_nodes = snapshot.get("claim_nodes")
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
    return {
        "workspace_id": snapshot.get("workspace_id"),
        "updated_at": snapshot.get("updated_at"),
        "run_id": snapshot.get("run_id"),
        "decisions": _string_list(snapshot.get("decisions"))[-8:],
        "evidence": _string_list(snapshot.get("evidence"))[-8:],
        "coverage_matrix": _normalize_coverage_matrix(snapshot.get("coverage_matrix"))[-8:],
        "claim_nodes": [
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "text": node.get("text"),
                "agent_id": node.get("agent_id"),
                "coherency_score": node.get("coherency_score"),
            }
            for node in nodes[-16:]
            if isinstance(node, dict)
        ]
        if isinstance(nodes, list)
        else [],
    }


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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_string_list(item))
        return values
    if isinstance(value, str) and value.strip():
        if "," in value or ";" in value:
            return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
        return [value.strip()]
    return []


def _parse_vote_payload(content: str) -> dict[str, Any]:
    parsed = _parse_json_object(content)
    if _looks_like_vote(parsed):
        return parsed

    fallback: dict[str, Any] = {}
    approve = _regex_bool(content, "approve")
    critical_blocker = _regex_bool(content, "critical_blocker")
    confidence = _regex_number(content, "confidence")
    blocker = _regex_string_or_bool(content, "blocker")
    final_points = _regex_string_or_list_hint(content, "final_points")

    if approve is not None:
        fallback["approve"] = approve
    if critical_blocker is not None:
        fallback["critical_blocker"] = critical_blocker
    if confidence is not None:
        fallback["confidence"] = confidence
    if blocker is not None:
        fallback["blocker"] = blocker
    if final_points:
        fallback["final_points"] = final_points

    if fallback:
        fallback.setdefault("approve", False)
        fallback.setdefault("confidence", 0)
        fallback.setdefault("blocker", "")
        fallback.setdefault("critical_blocker", False)
        fallback.setdefault("final_points", "Vote response was partially parsed.")
        return fallback

    return {
        "approve": False,
        "confidence": 0,
        "blocker": "Vote response was not valid JSON.",
        "critical_blocker": False,
        "final_points": "",
    }


def _looks_like_vote(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("approve", "confidence", "critical_blocker"))


def _regex_bool(content: str, key: str) -> bool | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', content, flags=re.I)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _regex_number(content: str, key: str) -> float | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', content)
    if not match:
        return None
    return _clamp_float(match.group(1), 0, 1)


def _regex_string_or_bool(content: str, key: str) -> str | None:
    bool_value = _regex_bool(content, key)
    if bool_value is False:
        return ""
    if bool_value is True:
        return "Vote reported a blocker."
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', content, flags=re.S)
    if match:
        return match.group(1).strip()
    if re.search(rf'"{re.escape(key)}"\s*:\s*\[', content):
        return "Vote listed non-critical blockers."
    return None


def _regex_string_or_list_hint(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', content, flags=re.S)
    if match:
        return match.group(1).strip()
    if re.search(rf'"{re.escape(key)}"\s*:\s*\[', content):
        return "Vote returned final_points as a list; content was compacted by the parser."
    return ""


def _vote_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    vote: _Vote,
) -> dict[str, Any]:
    return {
        "event": "agent_vote",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": VOTE_PHASE,
        "agent_id": vote.agent.id,
        "agent_name": vote.agent.name,
        "approve": vote.approve,
        "confidence": vote.confidence,
        "blocker": vote.blocker,
        "critical_blocker": vote.critical_blocker,
        "final_points": vote.final_points,
        "duration_ms": vote.duration_ms,
        "usage": vote.usage,
        "created_at": _now_iso(),
    }


def _consensus_snapshot(team: TeamConfig, votes: list[_Vote]) -> dict[str, Any]:
    required = math.ceil(len(team.agents) * team.consensus_threshold)
    approvals = sum(1 for vote in votes if vote.approve)
    return {
        "approvals": approvals,
        "required": required,
        "threshold": team.consensus_threshold,
        "critical_blocker": any(vote.critical_blocker for vote in votes),
    }


def _cancelled_event(run_id: str, conversation_id: Any) -> dict[str, Any]:
    return {
        "event": "team_run_cancelled",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "created_at": _now_iso(),
    }


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _apply_workspace_metadata(
    conversation: Conversation,
    workspace_root: str | None,
    tool_context: dict[str, Any] | None,
) -> None:
    value = workspace_root or (tool_context or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        conversation.metadata["workspace_root"] = value.strip()
