"""Consensus-reached phase generator (final synthesis)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from personagent.application.team_chat.blackboard.core import _Blackboard
from personagent.application.team_chat.contracts import TeamChatRequest, TeamConfig
from personagent.application.team_chat.phases.final_synthesis import FinalSynthesis
from personagent.application.team_chat.types import Vote
from personagent.domain.conversation.models import Conversation

from ._events import (
    _consensus_reached_event,
    _coordinator_started_event,
)


async def _run_consensus_phase(
    *,
    final_synthesis: FinalSynthesis,
    request: TeamChatRequest,
    team: TeamConfig,
    conversation: Conversation,
    run_id: str,
    votes: list[Vote],
    consensus: dict[str, Any],
    blackboard: _Blackboard,
    cancel_event: Any,
    round_index: int,
    workspace_id: str | None,
    consensus_result: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    coordinator_started_at = time.perf_counter()
    yield _consensus_reached_event(run_id, conversation.id, round_index, consensus)
    yield _coordinator_started_event(run_id, conversation.id, round_index, team.coordinator)

    final_content_parts: list[str] = []
    async for event in final_synthesis.synthesize_final(
        request=request,
        team=team,
        conversation=conversation,
        run_id=run_id,
        votes=votes,
        consensus=consensus,
        blackboard=blackboard,
        cancel_event=cancel_event,
    ):
        yield event
        if event.get("event") == "final_delta":
            final_content_parts.append(str(event.get("content", "")))

    consensus_result["final_content"] = "".join(final_content_parts)
    consensus_result["coordinator_started_at"] = coordinator_started_at
    consensus_result["blackboard_snapshot"] = blackboard.snapshot()
    consensus_result["team_memory_snapshot"] = blackboard.memory_snapshot(
        workspace_id=workspace_id,
        conversation_id=str(conversation.id),
        run_id=run_id,
    )
