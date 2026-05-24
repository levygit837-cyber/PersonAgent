"""Team chat orchestration primitives."""

from personagent.application.team_chat.consensus_phase import ConsensusPhase
from personagent.application.team_chat.contracts import (
    DEFAULT_TEAM_ID,
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
    TeamValidationError,
    default_team_config,
    parse_team_config,
    serialize_team_config,
)
from personagent.application.team_chat.coordinator_phase import CoordinatorPhase
from personagent.application.team_chat.orchestrator import TeamChatOrchestrator
from personagent.application.team_chat.types import (
    BlackboardEntry,
    CoordinatorGuidance,
    ExecutionContract,
    QueuedTurnItem,
    ToolAudit,
    TurnResult,
    Vote,
)

__all__ = [
    "ConsensusPhase",
    "CoordinatorPhase",
    "DEFAULT_TEAM_ID",
    "TeamAgentConfig",
    "TeamChatOrchestrator",
    "TeamChatRequest",
    "TeamConfig",
    "TeamValidationError",
    "default_team_config",
    "parse_team_config",
    "serialize_team_config",
    # Re-export types for tests and downstream consumers
    "BlackboardEntry",
    "CoordinatorGuidance",
    "ExecutionContract",
    "QueuedTurnItem",
    "ToolAudit",
    "TurnResult",
    "Vote",
]
