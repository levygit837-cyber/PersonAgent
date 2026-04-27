from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest

from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.application.team_chat import (
    TeamChatOrchestrator,
    TeamChatRequest,
    TeamValidationError,
    default_team_config,
    parse_team_config,
)
from personagent.application.team_chat.orchestrator import _parse_json_object, _parse_vote_payload
from personagent.domain.models.conversation import Conversation
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.infrastructure.tools import create_read_file_tool, create_write_file_tool


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


def test_vote_parser_recovers_truncated_positive_vote():
    payload = _parse_vote_payload(
        '{ "approve": true, "confidence": 0.91, "blocker": false, '
        '"critical_blocker": false, "final_points": ["caveat one", "caveat two"'
    )

    assert payload["approve"] is True
    assert payload["confidence"] == 0.91
    assert payload["blocker"] == ""
    assert payload["critical_blocker"] is False
    assert "compacted" in payload["final_points"]


def test_generic_json_parser_recovers_complete_items_from_truncated_agent_content():
    payload = _parse_json_object('```json\n{"claims": [{"text": "partial agent claim"}]\n')

    assert payload == {"claims": [{"text": "partial agent claim"}]}


@pytest.mark.asyncio
async def test_team_orchestrator_runs_independent_then_debate_and_reaches_consensus():
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
    expected_round = ["analyst", "critic", "builder", "reviewer"]
    assert started_agents[:4] == expected_round
    assert len(started_agents) % 4 == 0
    for offset in range(0, len(started_agents), 4):
        assert started_agents[offset : offset + 4] == expected_round
    assert completed_agents == started_agents
    assert [call["agent"] for call in llm.turn_calls] == started_agents
    assert all("independent first pass" in call["prompt"] for call in llm.turn_calls[:4])
    assert all("Blackboard snapshot" not in call["prompt"] for call in llm.turn_calls[:4])
    if len(llm.turn_calls) > 4:
        assert all("Blackboard snapshot" in call["prompt"] for call in llm.turn_calls[4:])
        assert all("Delta guard" in call["prompt"] for call in llm.turn_calls[4:])
    else:
        assert any(event["event"] == "debate_skipped" for event in events)
    assert all("Your mandatory subproblem lane" in call["prompt"] for call in llm.turn_calls)
    assert all(call["kwargs"]["tool_context"]["agent_id"] == call["agent"] for call in llm.turn_calls)
    assert any(event["event"] == "execution_contract" for event in events)
    assert any(event["event"] == "claim_graph_delta" for event in events)
    assert any(event["event"] == "coverage_matrix" for event in events)
    assert any(event["event"] == "coherency_score" for event in events)
    assert any(event["event"] == "adaptive_vote" for event in events)
    assert any(event["event"] == "coordinator_planning_started" for event in events)
    assert any(event["event"] == "coordinator_planning_completed" for event in events)
    assert llm.planning_calls
    assert events[-1]["event"] == "team_run_completed"
    consensus = next(event["consensus"] for event in events if event["event"] == "consensus_reached")
    assert consensus["approvals"] == 3
    assert consensus["required"] == 3
    assert next(event for event in events if event["event"] == "coordinator_started")
    assert llm.final_calls
    assert "Blackboard snapshot" in llm.final_calls[0]
    blackboard_events = [event for event in events if event["event"] == "blackboard_event"]
    assert [event["sequence"] for event in blackboard_events] == list(range(1, len(blackboard_events) + 1))
    assert blackboard_events[0]["event_type"] == "execution_contract"
    completed = events[-1]
    assert completed["blackboard_snapshot"]["entry_count"] == len(blackboard_events)
    assert completed["blackboard_snapshot"]["claim_graph"]["node_count"] >= 4
    assert completed["blackboard_snapshot"]["claim_graph"]["novelty_by_agent"]
    assert completed["team_memory_snapshot"]["claim_graph"]["nodes"]


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
    assert [event["round"] for event in events if event["event"] == "vote_started"] == [1]


@pytest.mark.asyncio
async def test_team_orchestrator_forces_final_vote_when_interval_does_not_match():
    raw = {
        **_serializable_default_team(),
        "max_rounds": 3,
        "vote_every_rounds": 2,
    }
    team = parse_team_config(raw=raw)
    repo = MemoryConversationRepository()
    llm = ScriptedTeamLLM(vote_approvals=[False, False, False, False])
    orchestrator = TeamChatOrchestrator(conversation_repo=repo, llm_backend=llm)

    events = [
        event
        async for event in orchestrator.execute(
            request=TeamChatRequest(message="Needs final vote", provider="llama", model="local-model"),
            team=team,
        )
    ]

    assert [event["round"] for event in events if event["event"] == "vote_started"] == [3]
    assert events[-1]["event"] == "team_consensus_failed"


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


@pytest.mark.asyncio
async def test_team_orchestrator_executes_read_tools_and_proposes_mutations(tmp_path):
    (tmp_path / "notes.txt").write_text("safe evidence", encoding="utf-8")
    raw = {
        **_serializable_default_team(),
        "max_rounds": 1,
    }
    team = parse_team_config(raw=raw)
    repo = MemoryConversationRepository()
    llm = ToolCallingTeamLLM()
    orchestrator = TeamChatOrchestrator(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_read_file_tool(), create_write_file_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    events = [
        event
        async for event in orchestrator.execute(
            request=TeamChatRequest(
                message="Use tools safely",
                provider="llama",
                model="local-model",
                workspace_root=str(tmp_path),
            ),
            team=team,
        )
    ]

    tool_events = [event for event in events if event["event"] == "tool_phase"]
    assert any(event.get("tool_phase") == "read_tools" and event.get("tool_result") for event in tool_events)
    assert any(
        event.get("tool_phase") == "mutating_proposal" and event.get("proposals")
        for event in tool_events
    )
    completed = events[-1]
    nodes = completed["blackboard_snapshot"]["claim_graph"]["nodes"]
    assert any(node["type"] == "tool_result" for node in nodes)
    assert any(node["type"] == "proposal" and node.get("mutating") for node in nodes)
    assert not (tmp_path / "mutated.txt").exists()


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
        "coordinator": {
            "id": team.coordinator.id,
            "name": team.coordinator.name,
            "role": team.coordinator.role,
            "system_prompt": team.coordinator.system_prompt,
            "temperature": team.coordinator.temperature,
            "max_tokens": team.coordinator.max_tokens,
            "tools_enabled": team.coordinator.tools_enabled,
        },
        "max_rounds": team.max_rounds,
        "vote_every_rounds": team.vote_every_rounds,
        "consensus_threshold": team.consensus_threshold,
        "force_final_vote": team.force_final_vote,
        "blackboard_mode": team.blackboard_mode,
        "tool_policy": team.tool_policy,
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
        self.turn_calls: list[dict[str, Any]] = []
        self.final_calls: list[str] = []
        self.planning_calls: list[str] = []
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
            self.final_calls.append(prompt)
            yield StreamChunk(content="Final synthesized answer.")
            yield StreamChunk(finish_reason="stop")
            return
        agent_name = messages[0]["content"].split("You are ", 1)[-1].split(",", 1)[0]
        agent_id = _agent_id_from_system(messages[0]["content"])
        self.turn_calls.append({"agent": agent_id, "prompt": prompt, "kwargs": kwargs})
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
        if "focus_assignments" in messages[-1]["content"]:
            self.planning_calls.append(messages[-1]["content"])
            return InferenceResult(
                content=json.dumps(
                    {
                        "summary": "Split the debate into distinct concerns.",
                        "overlap_risks": ["All agents may repeat the same summary."],
                        "focus_assignments": {
                            "analyst": "requirements",
                            "critic": "risks",
                            "builder": "implementation",
                            "reviewer": "coherence",
                        },
                        "debate_goals": ["reduce overlap"],
                    }
                )
            )
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
        if "focus_assignments" in messages[-1]["content"]:
            return InferenceResult(
                content=json.dumps(
                    {
                        "summary": "Assign focus areas.",
                        "focus_assignments": {
                            "analyst": "requirements",
                            "critic": "risks",
                            "builder": "solution",
                            "reviewer": "coherence",
                        },
                        "overlap_risks": [],
                        "debate_goals": [],
                    }
                )
            )
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


class ToolCallingTeamLLM(ScriptedTeamLLM):
    def __init__(self) -> None:
        super().__init__(vote_approvals=[True, True, True, True])

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
            self.final_calls.append(prompt)
            yield StreamChunk(content="Final synthesized answer.")
            yield StreamChunk(finish_reason="stop")
            return
        agent_id = _agent_id_from_system(messages[0]["content"])
        self.turn_calls.append({"agent": agent_id, "prompt": prompt, "kwargs": kwargs})
        yield StreamChunk(
            content=json.dumps({"claims": [{"text": "Read notes before any mutation."}], "coherency_score": 0.8}),
            tool_calls=[
                {
                    "id": f"read-{agent_id}",
                    "type": "function",
                    "function": {
                        "name": "Read",
                        "arguments": json.dumps({"path": "notes.txt", "limit": 5}),
                    },
                },
                {
                    "id": f"write-{agent_id}",
                    "type": "function",
                    "function": {
                        "name": "Write",
                        "arguments": json.dumps({"path": "mutated.txt", "content": "blocked"}),
                    },
                },
            ],
        )
        yield StreamChunk(finish_reason="tool_calls")


def _agent_id_from_system(system_prompt: str) -> str:
    for agent_id in ("analyst", "critic", "builder", "reviewer"):
        if agent_id.capitalize() in system_prompt or agent_id in system_prompt.lower():
            return agent_id
    return "unknown"
