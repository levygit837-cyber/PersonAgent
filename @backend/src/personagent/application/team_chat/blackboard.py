"""In-memory claim graph and compact journal for Team Mode."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, TypeAlias

from personagent.application.team_chat.blackboard_json_parsing import (
    _digest,
    _normalize_coverage_matrix,
    _parse_json_object,
    _turn_blackboard_payload,
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

CLAIM_TYPES = ("claim", "evidence", "assumption", "risk", "blocker", "proposal", "tool_result", "decision")
MUTATING_TOOL_NAMES = {"Write", "Edit", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskClose", "TaskAppendOutput"}


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


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


