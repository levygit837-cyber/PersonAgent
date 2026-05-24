"""Phase-based multi-agent team orchestration with a shared blackboard."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, TypeAlias
from uuid import uuid4

import structlog

from personagent.application.services import SessionTitleService
from personagent.application.team_chat.agent_turn_runner import AgentTurnRunner
from personagent.application.team_chat.blackboard_json_parsing import (
    _parse_json_object,  # noqa: F401  # backward-compat for tests
)
from personagent.application.team_chat.consensus_phase import (
    ConsensusPhase,
    _parse_vote_payload,  # noqa: F401  # backward-compat for tests
)
from personagent.application.team_chat.contracts import (
    TeamChatRequest,
    TeamConfig,
    validate_team_config,
)
from personagent.application.team_chat.coordinator_phase import CoordinatorPhase
from personagent.application.team_chat.final_synthesis import FinalSynthesis
from personagent.application.team_chat.phase_loop import TeamChatPhaseLoop
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
from personagent.domain.models.conversation import Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

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

        consensus_phase = ConsensusPhase(llm_backend=llm_backend)
        coordinator_phase = CoordinatorPhase(llm_backend=llm_backend)
        final_synthesis = FinalSynthesis(llm_backend=llm_backend)
        agent_turn_runner = AgentTurnRunner(
            llm_backend=llm_backend,
            tool_registry=tool_registry,
            tool_runtime_config=tool_runtime_config,
        )

        self._phase_loop = TeamChatPhaseLoop(
            conversation_repo=conversation_repo,
            consensus_phase=consensus_phase,
            coordinator_phase=coordinator_phase,
            final_synthesis=final_synthesis,
            agent_turn_runner=agent_turn_runner,
            session_title_service=session_title_service,
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
        conversation = await self._phase_loop._get_or_create_conversation(request)
        was_empty = len(conversation.messages) == 0
        user_msg = Message(role=Role.USER, content=request.message)
        conversation.add_message(user_msg)

        _conversation_persisted = False
        try:
            async for event in self._phase_loop.run(
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
