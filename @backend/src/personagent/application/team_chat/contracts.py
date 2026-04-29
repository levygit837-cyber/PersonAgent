"""Contracts for configurable multi-agent team chat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

DEFAULT_TEAM_ID = "default-4"


class TeamValidationError(ValueError):
    """Raised when a Team Mode configuration is invalid."""


@dataclass(frozen=True, slots=True)
class TeamAgentConfig:
    """One agent inside a team."""

    id: str
    name: str
    role: str
    system_prompt: str
    temperature: float = 0.3
    max_tokens: int = 2048
    tools_enabled: bool = False


@dataclass(frozen=True, slots=True)
class TeamConfig:
    """Configuration for a Team Mode run."""

    id: str
    name: str
    agents: tuple[TeamAgentConfig, ...]
    execution_order: tuple[str, ...]
    coordinator: TeamAgentConfig
    max_rounds: int | None = 3
    vote_every_rounds: int = 2
    consensus_threshold: float = 0.75
    force_final_vote: bool = True
    blackboard_mode: str = "hybrid"
    tool_policy: str = "guarded_autonomy"


@dataclass(frozen=True, slots=True)
class TeamChatRequest:
    """Runtime request for a Team Mode execution."""

    conversation_id: UUID | None = None
    message: str = ""
    system_prompt: str | None = None
    provider: str = "llama"
    model: str = "local-model"
    temperature: float = 0.7
    max_tokens: int = -1
    reasoning_level: str | None = None
    reasoning_budget_tokens: int | None = None
    workspace_root: str | None = None
    tool_context: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] | None = None
    max_tool_iterations: int | None = None


def default_team_config() -> TeamConfig:
    """Return the built-in 4-agent team preset."""

    agents = (
            TeamAgentConfig(
            id="analyst",
            name="Analyst",
            role="Analysis",
            system_prompt=(
                "You are the Analyst in a PersonAgent team. Identify the task, constraints, "
                "missing context, and the strongest direct answer path. Be concise and factual."
            ),
            temperature=0.2,
            tools_enabled=True,
        ),
        TeamAgentConfig(
            id="critic",
            name="Critic",
            role="Risk Review",
            system_prompt=(
                "You are the Critic in a PersonAgent team. Challenge weak assumptions, find "
                "failure modes, and point out what would make the answer unsafe or incomplete."
            ),
            temperature=0.25,
            tools_enabled=True,
        ),
        TeamAgentConfig(
            id="builder",
            name="Builder",
            role="Solution",
            system_prompt=(
                "You are the Builder in a PersonAgent team. Turn the analysis into a concrete, "
                "usable answer or implementation direction while respecting prior critiques."
            ),
            temperature=0.25,
            tools_enabled=True,
        ),
        TeamAgentConfig(
            id="reviewer",
            name="Reviewer",
            role="Final Review",
            system_prompt=(
                "You are the Reviewer in a PersonAgent team. Check coherence, completeness, "
                "and whether the team is ready to synthesize a final answer."
            ),
            temperature=0.2,
            tools_enabled=True,
        ),
    )
    coordinator = TeamAgentConfig(
        id="coordinator",
        name="Coordinator",
        role="Final Synthesis",
        system_prompt=(
            "You are the Coordinator in a PersonAgent team. Synthesize the final report "
            "from the blackboard, votes, evidence, blockers, and decisions. Do not vote."
        ),
        temperature=0.2,
        max_tokens=4096,
    )
    return TeamConfig(
        id=DEFAULT_TEAM_ID,
        name="Default 4-agent team",
        agents=agents,
        execution_order=tuple(agent.id for agent in agents),
        coordinator=coordinator,
    )


def parse_team_config(team_id: str | None = None, raw: dict[str, Any] | None = None) -> TeamConfig:
    """Parse and validate a requested team config or known preset."""

    if raw is None:
        if team_id in (None, "", DEFAULT_TEAM_ID):
            return default_team_config()
        raise TeamValidationError(f"Unknown team preset: {team_id}")

    agents = tuple(_parse_agent(item) for item in _required_list(raw, "agents"))
    execution_order = tuple(str(item).strip() for item in _required_list(raw, "execution_order"))
    config = TeamConfig(
        id=str(raw.get("id") or team_id or "custom").strip() or "custom",
        name=str(raw.get("name") or "Custom team").strip() or "Custom team",
        agents=agents,
        execution_order=execution_order,
        coordinator=_parse_agent(raw.get("coordinator") or _default_coordinator_payload()),
        max_rounds=_parse_optional_positive_int(raw.get("max_rounds", 3), "max_rounds"),
        vote_every_rounds=int(raw.get("vote_every_rounds", 2)),
        consensus_threshold=float(raw.get("consensus_threshold", 0.75)),
        force_final_vote=bool(raw.get("force_final_vote", True)),
        blackboard_mode=str(raw.get("blackboard_mode", "hybrid") or "hybrid"),
        tool_policy=str(raw.get("tool_policy", "guarded_autonomy") or "guarded_autonomy"),
    )
    validate_team_config(config)
    return config


def serialize_team_config(config: TeamConfig) -> dict[str, Any]:
    """Serialize a team config for API responses and persistence."""

    return {
        "id": config.id,
        "name": config.name,
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "role": agent.role,
                "system_prompt": agent.system_prompt,
                "temperature": agent.temperature,
                "max_tokens": agent.max_tokens,
                "tools_enabled": agent.tools_enabled,
            }
            for agent in config.agents
        ],
        "execution_order": list(config.execution_order),
        "coordinator": {
            "id": config.coordinator.id,
            "name": config.coordinator.name,
            "role": config.coordinator.role,
            "system_prompt": config.coordinator.system_prompt,
            "temperature": config.coordinator.temperature,
            "max_tokens": config.coordinator.max_tokens,
            "tools_enabled": config.coordinator.tools_enabled,
        },
        "max_rounds": config.max_rounds,
        "vote_every_rounds": config.vote_every_rounds,
        "consensus_threshold": config.consensus_threshold,
        "force_final_vote": config.force_final_vote,
        "blackboard_mode": config.blackboard_mode,
        "tool_policy": config.tool_policy,
    }


def validate_team_config(config: TeamConfig) -> None:
    """Validate a team config against the MVP Team Mode contract."""

    agent_count = len(config.agents)
    if agent_count < 2 or agent_count > 6:
        raise TeamValidationError("team agent_count must be between 2 and 6")
    ids = [agent.id for agent in config.agents]
    if any(not agent_id for agent_id in ids):
        raise TeamValidationError("team agents must have non-empty ids")
    if len(set(ids)) != len(ids):
        raise TeamValidationError("team agents must have unique ids")
    if len(config.execution_order) != agent_count:
        raise TeamValidationError("execution_order must contain every agent exactly once")
    if len(set(config.execution_order)) != len(config.execution_order):
        raise TeamValidationError("execution_order must not contain duplicates")
    if set(config.execution_order) != set(ids):
        raise TeamValidationError("execution_order must match team agent ids")
    if config.max_rounds is not None and config.max_rounds < 1:
        raise TeamValidationError("max_rounds must be positive or null")
    if config.vote_every_rounds < 1:
        raise TeamValidationError("vote_every_rounds must be at least 1")
    if config.consensus_threshold < 0.5 or config.consensus_threshold > 1.0:
        raise TeamValidationError("consensus_threshold must be between 0.5 and 1.0")
    if config.coordinator.id in set(ids):
        raise TeamValidationError("coordinator id must not duplicate a team agent id")
    if config.blackboard_mode != "hybrid":
        raise TeamValidationError("blackboard_mode must be hybrid")
    if config.tool_policy != "guarded_autonomy":
        raise TeamValidationError("tool_policy must be guarded_autonomy")
    for agent in config.agents:
        if not agent.name.strip():
            raise TeamValidationError("team agents must have names")
        if not agent.role.strip():
            raise TeamValidationError("team agents must have roles")
        if agent.temperature < 0 or agent.temperature > 2:
            raise TeamValidationError("agent temperature must be between 0 and 2")
        if agent.max_tokens < 1:
            raise TeamValidationError("agent max_tokens must be positive")
    if not config.coordinator.id.strip():
        raise TeamValidationError("coordinator must have an id")
    if not config.coordinator.name.strip():
        raise TeamValidationError("coordinator must have a name")
    if not config.coordinator.role.strip():
        raise TeamValidationError("coordinator must have a role")
    if config.coordinator.temperature < 0 or config.coordinator.temperature > 2:
        raise TeamValidationError("coordinator temperature must be between 0 and 2")
    if config.coordinator.max_tokens < 1:
        raise TeamValidationError("coordinator max_tokens must be positive")


def _parse_agent(raw: Any) -> TeamAgentConfig:
    if not isinstance(raw, dict):
        raise TeamValidationError("agents must be objects")
    return TeamAgentConfig(
        id=str(raw.get("id", "")).strip(),
        name=str(raw.get("name", "")).strip(),
        role=str(raw.get("role", "")).strip(),
        system_prompt=str(raw.get("system_prompt", "")).strip(),
        temperature=float(raw.get("temperature", 0.3)),
        max_tokens=int(raw.get("max_tokens", 2048)),
        tools_enabled=bool(raw.get("tools_enabled", False)),
    )


def _parse_optional_positive_int(value: Any, key: str) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed < 1:
        raise TeamValidationError(f"{key} must be positive or null")
    return parsed


def _required_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise TeamValidationError(f"{key} must be a non-empty list")
    return value


def _default_coordinator_payload() -> dict[str, Any]:
    coordinator = default_team_config().coordinator
    return {
        "id": coordinator.id,
        "name": coordinator.name,
        "role": coordinator.role,
        "system_prompt": coordinator.system_prompt,
        "temperature": coordinator.temperature,
        "max_tokens": coordinator.max_tokens,
        "tools_enabled": coordinator.tools_enabled,
    }
