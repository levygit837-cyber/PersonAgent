from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from personagent.domain.models.conversation import Conversation
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.interfaces.api.routes import chat


def test_team_websocket_streams_run_and_persists(monkeypatch):
    persisted = []
    app = _app_with_fakes(monkeypatch, ScriptedWsLLM(), persisted)

    with TestClient(app).websocket_connect("/chat/team/ws") as websocket:
        websocket.send_json(_start_payload())
        events = _receive_until(websocket, "team_run_completed")

    names = [event["event"] for event in events]
    assert names[:3] == ["team_run_started", "coordinator_planning_started", "execution_contract"]
    assert "blackboard_event" in names
    assert "blackboard_snapshot" in names
    assert "claim_graph_delta" in names
    assert "coverage_matrix" in names
    assert "coherency_score" in names
    assert "adaptive_vote" in names
    assert "coordinator_planning_started" in names
    assert "coordinator_planning_completed" in names
    assert "coordinator_started" in names
    assert "coordinator_completed" in names
    assert "agent_vote" in names
    assert names[-1] == "team_run_completed"
    assert persisted[0]["status"] == "completed"
    assert persisted[0]["final_output"] == "Team final."
    assert persisted[0]["run_id"].startswith("team_")
    assert persisted[0]["blackboard_snapshot"]["entry_count"] >= 4
    assert persisted[0]["team_memory_snapshot"]["claim_graph"]["nodes"]
    trace_events = persisted[0]["trace_events"]
    assert not any(event["event"] in {"agent_delta", "final_delta"} for event in trace_events)
    completed_turn = next(
        event for event in trace_events if event["event"] == "agent_turn_completed"
    )
    assert "content" not in completed_turn
    assert completed_turn["content_length"] == len("Agent turn.")
    completed_run = next(event for event in trace_events if event["event"] == "team_run_completed")
    assert "final_output" not in completed_run
    assert completed_run["final_output_length"] == len("Team final.")


def test_team_websocket_stop_cancels_run(monkeypatch):
    persisted = []
    app = _app_with_fakes(monkeypatch, SlowWsLLM(), persisted)

    with TestClient(app).websocket_connect("/chat/team/ws") as websocket:
        websocket.send_json(_start_payload())
        events = []
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["event"] == "agent_turn_started":
                websocket.send_json({"type": "team.run.stop"})
            if event["event"] == "team_run_cancelled":
                break

    assert events[-1]["event"] == "team_run_cancelled"
    assert persisted[0]["status"] == "cancelled"
    assert not any(event["event"] == "team_run_completed" for event in events)


def test_team_websocket_stop_persists_conversation(monkeypatch):
    """Ao interromper, a conversa deve ser persistida com a mensagem do usuário."""
    persisted = []
    app = _app_with_fakes(monkeypatch, SlowWsLLM(), persisted)

    with TestClient(app).websocket_connect("/chat/team/ws") as websocket:
        websocket.send_json(_start_payload())
        events = []
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["event"] == "agent_turn_started":
                websocket.send_json({"type": "team.run.stop"})
            if event["event"] == "team_run_cancelled":
                break

    # Recupera o repositório através do container para verificar persistência
    container = chat.get_container()
    repo = container.repo
    assert len(repo.conversations) == 1
    conversation = list(repo.conversations.values())[0]
    assert len(conversation.messages) >= 1
    assert conversation.messages[0].role.value == "user"
    assert conversation.messages[0].content == "Use the team"


def test_team_websocket_invalid_config_returns_error(monkeypatch):
    persisted = []
    app = _app_with_fakes(monkeypatch, ScriptedWsLLM(), persisted)
    payload = _start_payload()
    payload["team_config"] = {
        "id": "bad",
        "name": "Bad",
        "agents": [
            {"id": "a", "name": "A", "role": "A", "system_prompt": "A"},
            {"id": "b", "name": "B", "role": "B", "system_prompt": "B"},
        ],
        "execution_order": ["a", "a"],
    }

    with TestClient(app).websocket_connect("/chat/team/ws") as websocket:
        websocket.send_json(payload)
        event = websocket.receive_json()

    assert event["event"] == "error"
    assert event["status"] == 400
    assert persisted == []


def _app_with_fakes(monkeypatch, llm: LLMBackendRepository, persisted: list[dict]):
    repo = MemoryConversationRepository()
    container = FakeContainer(llm, repo)
    monkeypatch.setattr(chat, "get_container", lambda: container)
    monkeypatch.setattr(chat, "AsyncSessionLocal", lambda: FakeSession())

    async def fake_persist_team_run(**kwargs):
        persisted.append(kwargs)

    async def fake_persist_team_run_started(**kwargs):
        return None

    async def fake_persist_team_blackboard_event(**kwargs):
        return None

    monkeypatch.setattr(chat, "persist_team_run", fake_persist_team_run)
    monkeypatch.setattr(chat, "persist_team_run_started", fake_persist_team_run_started)
    monkeypatch.setattr(chat, "persist_team_blackboard_event", fake_persist_team_blackboard_event)
    app = FastAPI()
    app.include_router(chat.router)
    return app


def _start_payload():
    return {
        "type": "team.run.start",
        "message": "Use the team",
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 1024,
        "provider": "llama",
        "model": "local-model",
        "reasoning_level": "low",
        "reasoning_budget_tokens": 2048,
        "team_id": "default-4",
    }


def _receive_until(websocket, final_event: str):
    events = []
    while True:
        event = websocket.receive_json()
        events.append(event)
        if event["event"] == final_event:
            return events


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeContainer:
    def __init__(self, llm: LLMBackendRepository, repo: ConversationRepository) -> None:
        self.llm = llm
        self.repo = repo

    def get_llm_backend(self, provider="llama"):
        return self.llm

    async def get_conversation_repo(self, session):
        return self.repo


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return list(self.conversations.values())[:limit]


class ScriptedWsLLM(LLMBackendRepository):
    def __init__(self) -> None:
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
        if "Votes and final points" in messages[-1]["content"]:
            yield StreamChunk(content="Team final.")
        else:
            yield StreamChunk(content="Agent turn.")
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
                        "summary": "Coordinator split the next debate.",
                        "overlap_risks": ["duplicate summaries"],
                        "focus_assignments": {
                            "analyst": "requirements",
                            "critic": "risks",
                            "builder": "solution",
                            "reviewer": "coherence",
                        },
                        "debate_goals": ["distinct contributions"],
                    }
                )
            )
        approve = self.vote_index < 3
        self.vote_index += 1
        return InferenceResult(
            content=json.dumps(
                {
                    "approve": approve,
                    "confidence": 0.9,
                    "blocker": "",
                    "critical_blocker": False,
                    "final_points": "ready",
                }
            )
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {"data": []}


class SlowWsLLM(ScriptedWsLLM):
    async def chat_completion_stream(self, *args, **kwargs) -> AsyncIterator[StreamChunk]:
        await asyncio.sleep(0.05)
        yield StreamChunk(content="slow")
        yield StreamChunk(finish_reason="stop")
