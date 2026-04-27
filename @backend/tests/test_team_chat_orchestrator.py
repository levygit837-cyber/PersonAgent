from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import pytest

from personagent.application.team_chat import (
    TeamChatOrchestrator,
    TeamChatRequest,
    TeamValidationError,
    default_team_config,
    parse_team_config,
)
from personagent.domain.models.conversation import Conversation
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository


def test_team_config_validation_rejects_duplicate_order():
    raw = {
        "id": "bad",
        "name": "Bad",
        "agents": [
            {"id": "a", "name": "A", "role": "A", "system_prompt": "A"},
            {"id": "b", "name": "B", "role": "B", "system_prompt": "B"},
        ],
        "execution_order": ["a", "a"],
    }

    with pytest.raises(TeamValidationError, match="duplicates"):
        parse_team_config(raw=raw)


def test_team_config_validation_rejects_invalid_threshold():
    raw = {
        "id": "bad",
        "name": "Bad",
        "agents": [
            {"id": "a", "name": "A", "role": "A", "system_prompt": "A"},
            {"id": "b", "name": "B", "role": "B", "system_prompt": "B"},
        ],
        "execution_order": ["a", "b"],
        "consensus_threshold": 0.25,
    }

    with pytest.raises(TeamValidationError, match="consensus_threshold"):
        parse_team_config(raw=raw)


@pytest.mark.asyncio
async def test_team_orchestrator_runs_agents_sequentially_and_reaches_75_percent_consensus():
    repo = MemoryConversationRepository()
    llm = ScriptedTeamLLM(vote_approvals=[True, True, True, False])
    orchestrator = TeamChatOrchestrator(conversation_repo=repo, llm_backend=llm)

    events = [
        event
        async for event in orchestrator.execute(
            request=TeamChatRequest(message="Build the answer", provider="llama", model="local-model"),
            team=default_team_config(),
        )
    ]

    started_agents = [
        event["agent_id"] for event in events if event["event"] == "agent_turn_started"
    ]
    completed_agents = [
        event["agent_id"] for event in events if event["event"] == "agent_turn_completed"
    ]
    assert started_agents == ["analyst", "critic", "builder", "reviewer"]
    assert completed_agents == started_agents
    assert [call["agent"] for call in llm.turn_calls] == started_agents
    assert "Analyst" in llm.turn_calls[1]["prompt"]
    assert events[-1]["event"] == "team_run_completed"
    consensus = next(event["consensus"] for event in events if event["event"] == "consensus_reached")
    assert consensus["approvals"] == 3
    assert consensus["required"] == 3


@pytest.mark.asyncio
async def test_team_orchestrator_fails_without_consensus_after_max_rounds():
    raw = {
        **_serializable_default_team(),
        "max_rounds": 1,
    }
    team = parse_team_config(raw=raw)
    repo = MemoryConversationRepository()
    llm = ScriptedTeamLLM(vote_approvals=[False, False, False, False])
    orchestrator = TeamChatOrchestrator(conversation_repo=repo, llm_backend=llm)

    events = [
        event
        async for event in orchestrator.execute(
            request=TeamChatRequest(message="Not ready", provider="llama", model="local-model"),
            team=team,
        )
    ]

    assert events[-1]["event"] == "team_consensus_failed"
    assert not any(event["event"] == "team_run_completed" for event in events)


@pytest.mark.asyncio
async def test_team_orchestrator_does_not_promote_reasoning_to_agent_output():
    repo = MemoryConversationRepository()
    llm = ReasoningOnlyTurnLLM()
    orchestrator = TeamChatOrchestrator(conversation_repo=repo, llm_backend=llm)

    events = [
        event
        async for event in orchestrator.execute(
            request=TeamChatRequest(message="Keep reasoning separate", provider="llama", model="local-model"),
            team=default_team_config(),
        )
    ]

    completed_turn = next(event for event in events if event["event"] == "agent_turn_completed")
    assert completed_turn["content"] == ""
    assert completed_turn["reasoning_content"] == "hidden analysis"
    assert completed_turn["digest"] == ""


def _serializable_default_team():
    team = default_team_config()
    return {
        "id": team.id,
        "name": team.name,
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
            for agent in team.agents
        ],
        "execution_order": list(team.execution_order),
        "max_rounds": team.max_rounds,
        "vote_every_rounds": team.vote_every_rounds,
        "consensus_threshold": team.consensus_threshold,
    }


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return [
            conversation
            for conversation in self.conversations.values()
            if query.lower() in conversation.title.lower()
        ][:limit]


class ScriptedTeamLLM(LLMBackendRepository):
    def __init__(self, vote_approvals: list[bool]) -> None:
        self.vote_approvals = vote_approvals
        self.turn_calls: list[dict[str, str]] = []
        self.vote_index = 0

    async def chat_completion_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        prompt = messages[-1]["content"]
        if "Votes and final points" in prompt:
            yield StreamChunk(content="Final synthesized answer.")
            yield StreamChunk(finish_reason="stop")
            return
        agent_name = messages[0]["content"].split("You are ", 1)[-1].split(",", 1)[0]
        self.turn_calls.append({"agent": _agent_id_from_system(messages[0]["content"]), "prompt": prompt})
        yield StreamChunk(content=f"{agent_name} says useful context.")
        yield StreamChunk(finish_reason="stop")

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> InferenceResult:
        approve = self.vote_approvals[self.vote_index % len(self.vote_approvals)]
        self.vote_index += 1
        return InferenceResult(
            content=json.dumps(
                {
                    "approve": approve,
                    "confidence": 0.9 if approve else 0.2,
                    "blocker": "" if approve else "Needs another round",
                    "critical_blocker": False,
                    "final_points": "Keep the strongest answer.",
                }
            )
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {"data": []}


class ReasoningOnlyTurnLLM(LLMBackendRepository):
    async def chat_completion_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        if "Votes and final points" in messages[-1]["content"]:
            yield StreamChunk(content="Final synthesized answer.")
            yield StreamChunk(finish_reason="stop")
            return
        yield StreamChunk(reasoning_content="hidden analysis", is_thinking=True)
        yield StreamChunk(finish_reason="stop")

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> InferenceResult:
        return InferenceResult(
            content=json.dumps(
                {
                    "approve": True,
                    "confidence": 0.9,
                    "blocker": "",
                    "critical_blocker": False,
                    "final_points": "Ready.",
                }
            )
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {"data": []}


def _agent_id_from_system(system_prompt: str) -> str:
    for agent_id in ("analyst", "critic", "builder", "reviewer"):
        if agent_id.capitalize() in system_prompt or agent_id in system_prompt.lower():
            return agent_id
    return "unknown"
