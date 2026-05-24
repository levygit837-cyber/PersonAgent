"""Final synthesis phase for Team Mode.

Produces the user-facing answer after consensus is reached.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from personagent.application.team_chat.blackboard import _Blackboard
from personagent.application.team_chat.blackboard_scoring import _now_iso
from personagent.application.team_chat.consensus_phase import _votes_text
from personagent.application.team_chat.contracts import (
    TeamChatRequest,
    TeamConfig,
)
from personagent.application.team_chat.helpers import (
    COORDINATOR_PHASE,
    _agent_tool_context,
    _duration_ms,
    _runtime_context,
    _team_policy_overlay,
)
from personagent.application.team_chat.types import Vote
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository


class FinalSynthesis:
    """Runs the final synthesis phase: streams the coordinator's answer."""

    def __init__(self, llm_backend: LLMBackendRepository) -> None:
        self._llm_backend = llm_backend

    async def synthesize_final(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        votes: list[Vote],
        consensus: dict[str, Any],
        blackboard: _Blackboard,
        cancel_event: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        async for chunk in self._llm_backend.chat_completion_stream(
            messages=self.final_messages(request, team, blackboard, votes, consensus),
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

    def final_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        blackboard: _Blackboard,
        votes: list[Vote],
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
