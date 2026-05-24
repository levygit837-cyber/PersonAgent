"""Coordinator phase for Team Mode.

Encapsulates execution-contract creation and per-round coordinator planning.
"""

from __future__ import annotations

import json
import time
from typing import Any

from personagent.application.team_chat.blackboard import (
    _normalize_coverage_matrix,
    _parse_json_object,
    _string_list,
)
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
)
from personagent.application.team_chat.types import (
    CoordinatorGuidance,
    ExecutionContract,
)
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

EXECUTION_CONTRACT_PHASE = "execution_contract"
COORDINATOR_PLANNING_PHASE = "coordinator_planning"


def _default_focus_for_agent(agent: TeamAgentConfig) -> str:
    role = agent.role.lower()
    if "risk" in role or "critic" in agent.id:
        return "Challenge weak assumptions, identify blockers, and avoid repeating baseline analysis."
    if "solution" in role or "builder" in agent.id:
        return "Convert the strongest evidence into a concrete execution path."
    if "review" in role or "reviewer" in agent.id:
        return "Check coherence, missing evidence, and final-readiness criteria."
    return "Clarify requirements, constraints, evidence, and the direct answer path."


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


class CoordinatorPhase:
    """Runs coordinator phases: execution contract and per-round planning."""

    def __init__(self, llm_backend: LLMBackendRepository) -> None:
        self._llm_backend = llm_backend

    async def run_execution_contract(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: Any,
        run_id: str,
    ) -> ExecutionContract:
        from personagent.application.team_chat.messages import (
            _agent_tool_context,
            _duration_ms,
        )

        started = time.perf_counter()
        result = await self._llm_backend.chat_completion(
            messages=self.execution_contract_messages(request, team, blackboard),
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
        return ExecutionContract(
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

    async def run_coordinator_planning(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        round_index: int,
        blackboard: Any,
        run_id: str,
    ) -> CoordinatorGuidance:
        from personagent.application.team_chat.messages import (
            _agent_tool_context,
            _duration_ms,
        )

        started = time.perf_counter()
        result = await self._llm_backend.chat_completion(
            messages=self.coordinator_planning_messages(request, team, round_index, blackboard),
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
        return CoordinatorGuidance(
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

    def execution_contract_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: Any,
    ) -> list[dict[str, str]]:
        from personagent.application.team_chat.messages import (
            _runtime_context,
            _team_policy_overlay,
        )

        return [
            {
                "role": "system",
                "content": (
                    f"{request.system_prompt or 'You coordinate a multi-agent team.'}\n\n"
                    f"Team mode is active. You are {team.coordinator.name}, role: {team.coordinator.role}.\n"
                    f"{team.coordinator.system_prompt}\n"
                    f"{_team_policy_overlay()}"
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

    def coordinator_planning_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        round_index: int,
        blackboard: Any,
    ) -> list[dict[str, str]]:
        from personagent.application.team_chat.messages import (
            _runtime_context,
            _team_policy_overlay,
        )

        return [
            {
                "role": "system",
                "content": (
                    f"{request.system_prompt or 'You coordinate a multi-agent team.'}\n\n"
                    f"Team mode is active. You are {team.coordinator.name}, role: {team.coordinator.role}.\n"
                    f"{team.coordinator.system_prompt}\n"
                    f"{_team_policy_overlay()}"
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
