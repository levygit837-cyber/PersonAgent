"""Pure dataclasses and type aliases for the team-chat orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from personagent.application.team_chat.contracts import TeamAgentConfig


@dataclass(frozen=True, slots=True)
class TurnResult:
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
class Vote:
    agent: TeamAgentConfig
    approve: bool
    confidence: float
    blocker: str
    critical_blocker: bool
    final_points: str
    duration_ms: int
    usage: dict[str, int] | None = None


@dataclass(frozen=True, slots=True)
class CoordinatorGuidance:
    summary: str
    focus_assignments: dict[str, str]
    overlap_risks: list[str]
    debate_goals: list[str]
    redirects: dict[str, str]
    raw_content: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ExecutionContract:
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
class ToolAudit:
    calls: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BlackboardEntry:
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
class QueuedTurnItem:
    event: dict[str, Any] | None = None
    turn: TurnResult | None = None
    error: BaseException | None = None
    done: bool = False
