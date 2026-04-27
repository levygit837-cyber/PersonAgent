from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.interfaces.api.routes import chat


class FakeNvidiaBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_models(self, *, capability=None, refresh=False):
        self.calls.append({"capability": capability, "refresh": refresh})
        return {
            "object": "list",
            "provider": "nvidia",
            "data": [
                {
                    "id": "nvidia/nemotron-3-nano-30b-a3b",
                    "provider": "nvidia",
                    "label": "Nemotron 3 Nano 30B A3B",
                    "owned_by": "nvidia",
                    "capabilities": ["chat", "reasoning_chat"],
                    "supports_streaming": True,
                    "supports_reasoning": True,
                    "supports_thinking_budget": True,
                }
            ],
        }


class FakeVertexBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_models(self, *, capability=None, refresh=False):
        self.calls.append({"capability": capability, "refresh": refresh})
        return {
            "object": "list",
            "provider": "vertex",
            "data": [
                {
                    "id": "gemini-3.1-flash-lite-preview",
                    "provider": "vertex",
                    "label": "Gemini 3.1 Flash-Lite",
                    "capabilities": ["chat", "thinking", "image_input", "tools"],
                    "supports_streaming": True,
                    "supports_reasoning": True,
                }
            ],
        }


class FakeContainer:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            nvidia_default_model="deepseek-ai/deepseek-v4-flash",
            vertex_default_model="gemini-3.1-flash-lite-preview",
        )
        self.nvidia = FakeNvidiaBackend()
        self.vertex = FakeVertexBackend()
        self.requested_provider = None

    def get_llm_backend(self, provider="llama"):
        self.requested_provider = provider
        if provider == "vertex":
            return self.vertex
        return self.nvidia


class FakeConversationContainer:
    def __init__(self, repo: "MemoryConversationRepository") -> None:
        self.repo = repo

    async def get_conversation_repo(self, _session):
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
        return [
            conversation
            for conversation in self.conversations.values()
            if query in conversation.title
        ][:limit]


@pytest.mark.asyncio
async def test_chat_models_routes_to_nvidia_catalog(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/chat/models",
            params={
                "provider": "nvidia",
                "capability": "reasoning_chat",
                "refresh": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert container.requested_provider == "nvidia"
    assert container.nvidia.calls == [
        {"capability": "reasoning_chat", "refresh": True}
    ]
    assert body["provider"] == "nvidia"
    assert body["data"][0]["supports_reasoning"] is True


@pytest.mark.asyncio
async def test_chat_models_routes_to_vertex_catalog(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/chat/models",
            params={
                "provider": "vertex",
                "capability": "thinking",
                "refresh": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert container.requested_provider == "vertex"
    assert container.vertex.calls == [{"capability": "thinking", "refresh": True}]
    assert body["provider"] == "vertex"
    assert body["data"][0]["id"] == "gemini-3.1-flash-lite-preview"


def test_resolve_model_uses_nvidia_default_for_legacy_local_model(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    model = chat.resolve_model("nvidia", "local-model")

    assert model == "deepseek-ai/deepseek-v4-flash"


def test_resolve_model_uses_vertex_default_for_legacy_local_model(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    model = chat.resolve_model("vertex", "local-model")

    assert model == "gemini-3.1-flash-lite-preview"


@pytest.mark.asyncio
async def test_plan_decision_endpoints_approve_continue_and_cancel(monkeypatch):
    repo = MemoryConversationRepository()
    conversation = Conversation()
    conversation.metadata["plan_mode"] = {
        "active": True,
        "status": "awaiting_approval",
        "plan_id": "plan_1",
        "plan_content": "## Plan\n\n1. Patch backend.",
        "approval_id": "approval_1",
        "feedback": None,
        "cancelled": False,
    }
    await repo.create(conversation)
    container = FakeConversationContainer(repo)
    monkeypatch.setattr(chat, "get_container", lambda: container)

    async def fake_get_db():
        yield object()

    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[chat.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat/plan/approve",
            json={
                "conversation_id": str(conversation.id),
                "approval_id": "approval_1",
                "feedback": "Inclua testes.",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["plan_status"] == "approved"
        assert body["plan_active"] is False
        assert body["injected_message"].startswith("Implement the following plan:")
        assert "Inclua testes." in body["injected_message"]

        stored = await repo.get_by_id(conversation.id)
        assert stored is not None
        stored.metadata["plan_mode"].update(
            {
                "active": True,
                "status": "awaiting_approval",
                "approval_id": "approval_2",
                "cancelled": False,
            }
        )
        await repo.update(stored)

        response = await client.post(
            "/chat/plan/continue",
            json={
                "conversation_id": str(conversation.id),
                "approval_id": "approval_2",
                "feedback": "Detalhe migração.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["plan_status"] == "draft"
        assert body["plan_active"] is True
        assert "Detalhe migração." in body["suggested_message"]

        stored = await repo.get_by_id(conversation.id)
        assert stored is not None
        stored.metadata["plan_mode"].update(
            {
                "active": True,
                "status": "awaiting_approval",
                "approval_id": "approval_3",
                "cancelled": False,
            }
        )
        await repo.update(stored)

        response = await client.post(
            "/chat/plan/cancel",
            json={"conversation_id": str(conversation.id), "approval_id": "approval_3"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["plan_status"] == "cancelled"
        assert body["cancelled"] is True
