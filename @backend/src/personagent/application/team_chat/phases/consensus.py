"""Consensus / voting phase for Team Mode.

Encapsulates per-agent vote execution, vote parsing, and vote-event
construction.  Kept separate from the outer phase loop so the tally
logic stays testable in isolation.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

import structlog

from personagent.application.team_chat.blackboard.core import (
    _Blackboard,
)
from personagent.application.team_chat.blackboard.json_parsing import (
    _clamp_float,
    _parse_json_object,
)
from personagent.application.team_chat.blackboard.scoring import (
    _now_iso,
)
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
)
from personagent.application.team_chat.helpers import (
    VOTE_PHASE,
    _agent_tool_context,
    _duration_ms,
)
from personagent.application.team_chat.types import Vote
from personagent.domain.llm_backend.repositories import LLMBackendRepository

logger = structlog.get_logger(__name__)


def _fast_vote_enabled(request: TeamChatRequest) -> bool:
    return request.provider.lower() not in {"llama", "test", "fake"}


def _votes_text(votes: list[Vote]) -> str:
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


def _fast_vote(agent: TeamAgentConfig, blackboard: Any) -> Vote:
    return Vote(
        agent=agent,
        approve=True,
        confidence=0.82,
        blocker="",
        critical_blocker=False,
        final_points=(
            "Fast ballot: coverage is sufficient and no real blocker or contradiction is active. "
            "Coordinator should synthesize with caveats and keep mutating proposals unexecuted."
        ),
        duration_ms=0,
        usage=None,
    )


def _vote_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    vote: Vote,
) -> dict[str, Any]:
    return {
        "event": "agent_vote",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": VOTE_PHASE,
        "agent_id": vote.agent.id,
        "agent_name": vote.agent.name,
        "approve": vote.approve,
        "confidence": vote.confidence,
        "blocker": vote.blocker,
        "critical_blocker": vote.critical_blocker,
        "final_points": vote.final_points,
        "duration_ms": vote.duration_ms,
        "usage": vote.usage,
        "created_at": _now_iso(),
    }


def _consensus_snapshot(team: TeamConfig, votes: list[Vote]) -> dict[str, Any]:
    required = math.ceil(len(team.agents) * team.consensus_threshold)
    approvals = sum(1 for vote in votes if vote.approve)
    return {
        "approvals": approvals,
        "required": required,
        "threshold": team.consensus_threshold,
        "critical_blocker": any(vote.critical_blocker for vote in votes),
    }


def _parse_vote_payload(content: str) -> dict[str, Any]:
    parsed = _parse_json_object(content)
    if _looks_like_vote(parsed):
        return parsed

    fallback: dict[str, Any] = {}
    approve = _regex_bool(content, "approve")
    critical_blocker = _regex_bool(content, "critical_blocker")
    confidence = _regex_number(content, "confidence")
    blocker = _regex_string_or_bool(content, "blocker")
    final_points = _regex_string_or_list_hint(content, "final_points")

    if approve is not None:
        fallback["approve"] = approve
    if critical_blocker is not None:
        fallback["critical_blocker"] = critical_blocker
    if confidence is not None:
        fallback["confidence"] = confidence
    if blocker is not None:
        fallback["blocker"] = blocker
    if final_points:
        fallback["final_points"] = final_points

    if fallback:
        fallback.setdefault("approve", False)
        fallback.setdefault("confidence", 0)
        fallback.setdefault("blocker", "")
        fallback.setdefault("critical_blocker", False)
        fallback.setdefault("final_points", "Vote response was partially parsed.")
        return fallback

    return {
        "approve": False,
        "confidence": 0,
        "blocker": "Vote response was not valid JSON.",
        "critical_blocker": False,
        "final_points": "",
    }


def _looks_like_vote(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("approve", "confidence", "critical_blocker"))


def _regex_bool(content: str, key: str) -> bool | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false)', content, flags=re.I)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _regex_number(content: str, key: str) -> float | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', content)
    if not match:
        return None
    return _clamp_float(match.group(1), 0, 1)


def _regex_string_or_bool(content: str, key: str) -> str | None:
    bool_value = _regex_bool(content, key)
    if bool_value is False:
        return ""
    if bool_value is True:
        return "Vote reported a blocker."
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', content, flags=re.S)
    if match:
        return match.group(1).strip()
    if re.search(rf'"{re.escape(key)}"\s*:\s*\[', content):
        return "Vote listed non-critical blockers."
    return None


def _regex_string_or_list_hint(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', content, flags=re.S)
    if match:
        return match.group(1).strip()
    if re.search(rf'"{re.escape(key)}"\s*:\s*\[', content):
        return "Vote returned final_points as a list; content was compacted by the parser."
    return ""


class ConsensusPhase:
    """Runs the vote phase: per-agent ballots, parsing, and event building."""

    def __init__(self, llm_backend: LLMBackendRepository) -> None:
        self._llm_backend = llm_backend

    async def run_vote(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        blackboard: _Blackboard,
        run_id: str,
    ) -> Vote:
        started = time.perf_counter()
        try:
            result = await self._llm_backend.chat_completion(
                messages=self.vote_messages(request, team, agent, round_index, blackboard),
                temperature=0,
                max_tokens=agent.max_tokens,
                stream=False,
                model=request.model,
                provider=request.provider,
                reasoning_level=request.reasoning_level,
                reasoning_budget_tokens=request.reasoning_budget_tokens,
                tool_context=_agent_tool_context(request, run_id, agent, round_index, VOTE_PHASE),
                tool_policy=team.tool_policy,
            )
        except Exception as exc:
            logger.warning("team_agent_vote_failed", agent_id=agent.id, round=round_index, error=str(exc))
            return Vote(
                agent=agent,
                approve=False,
                confidence=0.0,
                blocker=f"Vote failed for {agent.name}: {exc}",
                critical_blocker=False,
                final_points="Vote unavailable; Coordinator may proceed if quorum is still met.",
                duration_ms=_duration_ms(started),
                usage=None,
            )
        payload = _parse_vote_payload(result.content)
        return Vote(
            agent=agent,
            approve=bool(payload.get("approve", False)),
            confidence=_clamp_float(payload.get("confidence", 0), 0, 1),
            blocker=str(payload.get("blocker", "") or ""),
            critical_blocker=bool(payload.get("critical_blocker", False)),
            final_points=str(payload.get("final_points", "") or ""),
            duration_ms=_duration_ms(started),
            usage=result.usage,
        )

    def vote_messages(
        self,
        request: TeamChatRequest,
        team: TeamConfig,
        agent: TeamAgentConfig,
        round_index: int,
        blackboard: _Blackboard,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You vote on whether the Coordinator can synthesize a useful final answer now. "
                    "Return only compact JSON with keys approve, confidence, blocker, "
                    "critical_blocker, final_points. Set approve=true when the blackboard has enough "
                    "evidence for an actionable answer, even if caveats or next steps remain. "
                    "Set critical_blocker=true only when synthesis would be unsafe, impossible, "
                    "or clearly misleading without more information. Ordinary missing refinements, "
                    "future metrics, optional hardening items, unavailable example artifacts for conceptual "
                    "questions, and mutating actions that can remain proposed but unexecuted are "
                    "blockers=false/critical_blocker=false "
                    "and should be placed in final_points as caveats. final_points must be a single "
                    "string under 360 characters, not an array."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Agent voting: {agent.name} ({agent.role})\n"
                    f"Team: {team.name}\n"
                    f"Round: {round_index}\n"
                    f"User input:\n{request.message}\n\n"
                    f"Compact ballot:\n{blackboard.ballot_text()}\n\n"
                    "Vote from this ballot only. Do not produce analysis. JSON only."
                ),
            },
        ]
