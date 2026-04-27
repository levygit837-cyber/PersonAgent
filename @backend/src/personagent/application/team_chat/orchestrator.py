"""Sequential turn-based multi-agent team orchestration."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
    serialize_team_config,
    validate_team_config,
)
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _TurnResult:
    agent: TeamAgentConfig
    round_index: int
    content: str
    reasoning: str
    digest: str
    usage: dict[str, int] | None
    duration_ms: int
    first_token_ms: int | None


@dataclass(frozen=True, slots=True)
class _Vote:
    agent: TeamAgentConfig
    approve: bool
    confidence: float
    blocker: str
    critical_blocker: bool
    final_points: str


class TeamChatOrchestrator:
    """Runs a Team Mode chat with sequential turns and consensus votes."""

    def __init__(
        self,
        *,
        conversation_repo: ConversationRepository,
        llm_backend: LLMBackendRepository,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._llm_backend = llm_backend

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
        agent_by_id = {agent.id: agent for agent in team.agents}
        turns: list[_TurnResult] = []
        last_votes: list[_Vote] = []
        final_content_parts: list[str] = []

        yield {
            "event": "team_run_started",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "team": serialize_team_config(team),
            "created_at": _now_iso(),
        }

        for round_index in range(1, team.max_rounds + 1):
            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            yield {
                "event": "round_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "created_at": _now_iso(),
            }

            for agent_id in team.execution_order:
                if cancel_event.is_set():
                    yield _cancelled_event(run_id, conversation.id)
                    return

                agent = agent_by_id[agent_id]
                async for event, turn in self._run_agent_turn(
                    request=request,
                    team=team,
                    conversation=conversation,
                    run_id=run_id,
                    agent=agent,
                    round_index=round_index,
                    previous_turns=turns,
                    cancel_event=cancel_event,
                ):
                    yield event
                    if turn is not None:
                        turns.append(turn)

            if round_index % team.vote_every_rounds != 0:
                continue

            yield {
                "event": "vote_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "created_at": _now_iso(),
            }
            last_votes = await asyncio.gather(
                *[
                    self._run_vote(request, team, agent_by_id[agent_id], round_index, turns)
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
                continue

            consensus = {
                "approvals": approvals,
                "required": required,
                "threshold": team.consensus_threshold,
                "critical_blocker": has_critical_blocker,
                "round": round_index,
            }
            yield {
                "event": "consensus_reached",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "consensus": consensus,
                "created_at": _now_iso(),
            }
            async for event in self._synthesize_final(
                request=request,
                team=team,
                conversation=conversation,
                run_id=run_id,
                turns=turns,
                votes=last_votes,
                consensus=consensus,
                cancel_event=cancel_event,
            ):
                yield event
                if event.get("event") == "final_delta":
                    final_content_parts.append(str(event.get("content", "")))

            if cancel_event.is_set():
                yield _cancelled_event(run_id, conversation.id)
                return

            final_content = "".join(final_content_parts)
            conversation.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=final_content,
                    metadata={
                        "team_mode": True,
                        "run_id": run_id,
                        "team_id": team.id,
                        "consensus": consensus,
                    },
                )
            )
            await self._conversation_repo.update(conversation)
            if was_empty:
                conversation.title = conversation.generate_title()
                await self._conversation_repo.update(conversation)
            yield {
                "event": "team_run_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "title": conversation.title,
                "final_output": final_content,
                "consensus": consensus,
                "created_at": _now_iso(),
            }
            return

        failure_consensus = _consensus_snapshot(team, last_votes)
        await self._conversation_repo.update(conversation)
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)
        yield {
            "event": "team_consensus_failed",
            "run_id": run_id,
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "reason": "max_rounds_without_consensus",
            "consensus": failure_consensus,
            "created_at": _now_iso(),
        }

    async def _run_agent_turn(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        agent: TeamAgentConfig,
        round_index: int,
        previous_turns: list[_TurnResult],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[tuple[dict[str, Any], _TurnResult | None]]:
        started = time.perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage = None
        yield (
            {
                "event": "agent_turn_started",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_role": agent.role,
                "started_at": _now_iso(),
            },
            None,
        )

        async for chunk in self._llm_backend.chat_completion_stream(
            messages=self._agent_messages(request, team, agent, round_index, previous_turns),
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
        ):
            if cancel_event.is_set():
                break
            if first_token_at is None and (chunk.content or chunk.reasoning_content):
                first_token_at = time.perf_counter()
            if chunk.content:
                content_parts.append(chunk.content)
            if chunk.reasoning_content:
                reasoning_parts.append(chunk.reasoning_content)
            if chunk.usage:
                usage = chunk.usage
            if chunk.content or chunk.reasoning_content:
                yield (
                    {
                        "event": "agent_delta",
                        "run_id": run_id,
                        "conversation_id": str(conversation.id),
                        "round": round_index,
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "content": chunk.content,
                        "reasoning_content": chunk.reasoning_content,
                        "is_thinking": chunk.is_thinking,
                        "created_at": _now_iso(),
                    },
                    None,
                )

        duration_ms = _duration_ms(started)
        first_token_ms = (
            int((first_token_at - started) * 1000) if first_token_at is not None else None
        )
        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        turn_content = _turn_text(content, reasoning)
        turn = _TurnResult(
            agent=agent,
            round_index=round_index,
            content=turn_content,
            reasoning=reasoning,
            digest=_digest(turn_content),
            usage=usage,
            duration_ms=duration_ms,
            first_token_ms=first_token_ms,
        )
        yield (
            {
                "event": "agent_turn_completed",
                "run_id": run_id,
                "conversation_id": str(conversation.id),
                "round": round_index,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "content": turn_content,
                "reasoning_content": reasoning,
                "digest": turn.digest,
                "usage": usage,
                "completed_at": _now_iso(),
                "duration_ms": duration_ms,
                "first_token_ms": first_token_ms,
            },
            turn,
        )

    async def _run_vote(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        turns: list[_TurnResult],
    ) -> _Vote:
        result = await self._llm_backend.chat_completion(
            messages=self._vote_messages(request, team, agent, round_index, turns),
            temperature=0,
            max_tokens=512,
            stream=False,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
        )
        payload = _parse_json_object(result.content)
        return _Vote(
            agent=agent,
            approve=bool(payload.get("approve", False)),
            confidence=_clamp_float(payload.get("confidence", 0), 0, 1),
            blocker=str(payload.get("blocker", "") or ""),
            critical_blocker=bool(payload.get("critical_blocker", False)),
            final_points=str(payload.get("final_points", "") or ""),
        )

    async def _synthesize_final(
        self,
        *,
        request: TeamChatRequest,
        team: TeamConfig,
        conversation: Conversation,
        run_id: str,
        turns: list[_TurnResult],
        votes: list[_Vote],
        consensus: dict[str, Any],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        async for chunk in self._llm_backend.chat_completion_stream(
            messages=self._final_messages(request, team, turns, votes, consensus),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
        ):
            if cancel_event.is_set():
                break
            if chunk.content or chunk.reasoning_content:
                yield {
                    "event": "final_delta",
                    "run_id": run_id,
                    "conversation_id": str(conversation.id),
                    "content": chunk.content,
                    "reasoning_content": chunk.reasoning_content,
                    "is_thinking": chunk.is_thinking,
                    "created_at": _now_iso(),
                    "duration_ms": _duration_ms(started),
                }

    async def _get_or_create_conversation(self, request: TeamChatRequest) -> Conversation:
        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(request.conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation {request.conversation_id} not found")
            return conversation
        conversation = Conversation()
        await self._conversation_repo.create(conversation)
        return conversation

    def _agent_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        turns: list[_TurnResult],
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _agent_system_prompt(request, team, agent)},
            {
                "role": "user",
                "content": (
                    f"User input:\n{request.message}\n\n"
                    f"Round: {round_index}\n"
                    f"Runtime context:\n{_runtime_context(request)}\n\n"
                    f"Team transcript so far:\n{_transcript(turns)}\n\n"
                    "Respond as your own agent persona. Add new useful perspective, "
                    "respect prior agent context, and keep the answer concise."
                ),
            },
        ]

    def _vote_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        turns: list[_TurnResult],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You vote on whether the team is ready to stop. Return only compact JSON "
                    "with keys approve, confidence, blocker, critical_blocker, final_points."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Agent voting: {agent.name} ({agent.role})\n"
                    f"Team: {team.name}\n"
                    f"Round: {round_index}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Team transcript:\n{_transcript(turns)}"
                ),
            },
        ]

    def _final_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        turns: list[_TurnResult],
        votes: list[_Vote],
        consensus: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    request.system_prompt
                    or "You synthesize the final answer for the user from a multi-agent team."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Team: {team.name}\n"
                    f"Consensus: {json.dumps(consensus, ensure_ascii=False)}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Runtime context:\n{_runtime_context(request)}\n\n"
                    f"Agent turns:\n{_transcript(turns)}\n\n"
                    f"Votes and final points:\n{_votes_text(votes)}\n\n"
                    "Write the final answer to the user. Do not mention internal voting unless "
                    "it is necessary to explain uncertainty."
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
        "Never claim to be the final answer. Your output is one turn in the team discussion."
    )


def _transcript(turns: list[_TurnResult]) -> str:
    if not turns:
        return "No prior team turns."
    lines = []
    for turn in turns:
        lines.append(
            f"- Round {turn.round_index} / {turn.agent.name} ({turn.agent.role}): {turn.digest}"
        )
    return "\n".join(lines)


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


def _runtime_context(request: TeamChatRequest) -> str:
    context: dict[str, Any] = {}
    if request.workspace_root:
        context["workspace_root"] = request.workspace_root
    if request.tool_context:
        context["tool_context"] = request.tool_context
    if not context:
        return "No workspace context was provided."
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:1200]


def _turn_text(content: str, reasoning: str) -> str:
    return content.strip()


def _digest(content: str, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", content).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rsplit(' ', 1)[0]}..."


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("team_vote_json_parse_failed", content=content)
        return {
            "approve": False,
            "confidence": 0,
            "blocker": "Vote response was not valid JSON.",
            "critical_blocker": True,
            "final_points": "",
        }
    return parsed if isinstance(parsed, dict) else {}


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
        "agent_id": vote.agent.id,
        "agent_name": vote.agent.name,
        "approve": vote.approve,
        "confidence": vote.confidence,
        "blocker": vote.blocker,
        "critical_blocker": vote.critical_blocker,
        "final_points": vote.final_points,
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
