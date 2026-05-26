"""In-memory claim graph and compact journal for Team Mode."""

from __future__ import annotations

from typing import Any, TypeAlias

from personagent.application.team_chat.blackboard.claim_graph import (
    ClaimGraphAnalyzer,
)
from personagent.application.team_chat.blackboard.json_parsing import (
    _normalize_coverage_matrix,
    _turn_blackboard_payload,
)
from personagent.application.team_chat.blackboard.scoring import (
    _compact_workspace_memory,
    _is_real_blocker_text,
    _now_iso,
)
from personagent.application.team_chat.contracts import TeamAgentConfig, TeamConfig
from personagent.application.team_chat.types import (
    BlackboardEntry,
    CoordinatorGuidance,
    ExecutionContract,
    TurnResult,
)

# Backward-compat aliases
_TurnResult: TypeAlias = TurnResult
_CoordinatorGuidance: TypeAlias = CoordinatorGuidance
_ExecutionContract: TypeAlias = ExecutionContract
_BlackboardEntry: TypeAlias = BlackboardEntry
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
        self._entries: list[BlackboardEntry] = []
        self._claim_nodes: list[dict[str, Any]] = []
        self._claim_signatures: set[str] = set()
        self._duplicates: list[dict[str, Any]] = []
        self._execution_contract: dict[str, Any] = {}
        self._coverage_matrix: list[dict[str, Any]] = []
        self._agent_novelty_scores: dict[str, list[float]] = {}
        self._next_sequence = 1
        self._claim_graph = ClaimGraphAnalyzer(
            claim_nodes=self._claim_nodes,
            claim_signatures=self._claim_signatures,
            duplicates=self._duplicates,
            coverage_matrix=self._coverage_matrix,
            agent_novelty_scores=self._agent_novelty_scores,
        )

    def publish_execution_contract(
        self,
        *,
        coordinator: TeamAgentConfig,
        contract: ExecutionContract,
    ) -> BlackboardEntry:
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
        self._claim_graph.set_coverage_matrix(self._coverage_matrix)
        entry = self._new_entry(
            phase=EXECUTION_CONTRACT_PHASE,
            round_index=0,
            agent=coordinator,
            event_type="execution_contract",
            payload=payload,
        )
        return entry

    def publish_turn(self, turn: TurnResult) -> BlackboardEntry:
        payload = _turn_blackboard_payload(turn)
        entry = self._new_entry(
            phase=turn.phase,
            round_index=turn.round_index,
            agent=turn.agent,
            event_type="agent_observation" if not turn.blocker else "agent_blocker",
            payload=payload,
        )
        nodes = self._claim_graph.claim_nodes_from_turn(
            entry, turn,
            user_input=self._user_input,
            execution_contract=self._execution_contract,
        )
        payload["claim_nodes"] = nodes
        payload["claim_node_count"] = len(nodes)
        self._claim_graph.update_coverage(nodes)
        return entry

    def publish_coordinator_guidance(
        self,
        *,
        coordinator: TeamAgentConfig,
        round_index: int,
        guidance: CoordinatorGuidance,
    ) -> BlackboardEntry:
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

    def claim_delta_for(self, entry: BlackboardEntry) -> dict[str, Any]:
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
    ) -> BlackboardEntry:
        entry = BlackboardEntry(
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

