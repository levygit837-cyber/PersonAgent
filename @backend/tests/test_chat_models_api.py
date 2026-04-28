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


class FakeKimiBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_models(self, *, capability=None, refresh=False):
        self.calls.append({"capability": capability, "refresh": refresh})
        return {
            "object": "list",
            "provider": "kimi",
            "data": [
                {
                    "id": "kimi-for-coding",
                    "provider": "kimi",
                    "label": "Kimi K2.6",
                    "capabilities": ["chat", "reasoning_chat", "tools", "streaming"],
                    "supports_streaming": True,
                    "supports_reasoning": True,
                }
            ],
        }


class FakeCodexBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.logout_calls = 0

    async def list_models(self, *, capability=None, refresh=False):
        self.calls.append({"capability": capability, "refresh": refresh})
        return {
            "object": "list",
            "provider": "codex",
            "data": [
                {
                    "id": "gpt-5.5",
                    "provider": "codex",
                    "label": "GPT-5.5",
                    "capabilities": ["chat", "reasoning_chat", "tools", "streaming"],
                    "supports_streaming": True,
                    "supports_reasoning": True,
                },
                {
                    "id": "gpt-5.4-mini",
                    "provider": "codex",
                    "label": "GPT-5.4-Mini",
                    "capabilities": ["chat", "reasoning_chat", "tools", "streaming"],
                    "supports_streaming": True,
                    "supports_reasoning": True,
                },
            ],
        }

    def auth_status(self):
        return {
            "authenticated": True,
            "auth_mode": "chatgpt",
            "email": "user@example.com",
            "account_id": "acct_123",
        }

    async def logout(self):
        self.logout_calls += 1
        return {"authenticated": False, "logout_started": True}


class FakeContainer:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            nvidia_default_model="deepseek-ai/deepseek-v4-flash",
            vertex_default_model="gemini-3.1-flash-lite-preview",
            kimi_default_model="kimi-for-coding",
            codex_default_model="gpt-5.5",
        )
        self.nvidia = FakeNvidiaBackend()
        self.vertex = FakeVertexBackend()
        self.kimi = FakeKimiBackend()
        self.codex = FakeCodexBackend()
        self.requested_provider = None

    def get_llm_backend(self, provider="llama"):
        self.requested_provider = provider
        if provider == "vertex":
            return self.vertex
        if provider == "kimi":
            return self.kimi
        if provider == "codex":
            return self.codex
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


class FakePromptPreviewContainer(FakeContainer):
    def __init__(self) -> None:
        super().__init__()
        self.settings.tools_enabled = True
        self.settings.tool_workspace_root_path = "/tmp"
        self.repo = MemoryConversationRepository()

    async def get_conversation_repo(self, _session):
        return self.repo


class FakePromptPreviewUseCase:
    def __init__(self) -> None:
        self.requests = []

    async def preview_prompt(self, request):
        self.requests.append(request)
        prompt = "# Identity and Objective\n\n# Mode Overlay: Writing"
        return {
            "system_prompt": prompt,
            "user_context_message": "<system-reminder>context</system-reminder>",
            "sections": ["identity_and_objective", "mode_writing"],
            "surfaces": ["system", "mode:writing"],
            "dynamic_sections": ["system_context"],
            "mode": "writing",
            "requested_mode": "writing",
            "analysis_source": "override",
            "analysis_confidence": 1.0,
            "line_count": len(prompt.splitlines()),
            "char_count": len(prompt),
            "estimated_tokens": 32,
            "provider_data_boundary": "hosted_model_external_provider_local_tools",
            "provider": request.provider,
            "model": request.model,
        }


async def _fake_db():
    yield None


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
async def test_prompt_preview_endpoint_returns_prompt_package_without_completion(monkeypatch):
    container = FakePromptPreviewContainer()
    use_case = FakePromptPreviewUseCase()
    monkeypatch.setattr(chat, "get_container", lambda: container)
    monkeypatch.setattr(chat, "_create_chat_use_case", lambda **_: use_case)

    app = FastAPI()
    app.dependency_overrides[chat.get_db] = _fake_db
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat/prompt/preview",
            json={
                "message": "Implemente a melhoria",
                "provider": "nvidia",
                "model": "local-model",
                "prompt_mode": "writing",
                "tools_enabled": True,
                "allowed_tools": ["Read", "TodoWrite"],
                "workspace_root": "/tmp",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert use_case.requests
    assert use_case.requests[0].tools_enabled is True
    assert use_case.requests[0].allowed_tools == ["Read", "TodoWrite"]
    assert body["system_prompt"].startswith("# Identity and Objective")
    assert body["line_count"] == len(body["system_prompt"].splitlines())
    assert body["char_count"] == len(body["system_prompt"])
    assert body["model"] == "deepseek-ai/deepseek-v4-flash"
    assert body["provider_data_boundary"] == "hosted_model_external_provider_local_tools"


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


@pytest.mark.asyncio
async def test_chat_models_routes_to_kimi_catalog(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/chat/models",
            params={
                "provider": "kimi",
                "capability": "reasoning_chat",
                "refresh": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert container.requested_provider == "kimi"
    assert container.kimi.calls == [{"capability": "reasoning_chat", "refresh": True}]
    assert body["provider"] == "kimi"
    assert body["data"][0]["id"] == "kimi-for-coding"


@pytest.mark.asyncio
async def test_chat_models_routes_to_codex_catalog(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/chat/models",
            params={
                "provider": "codex",
                "capability": "reasoning_chat",
                "refresh": "true",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert container.requested_provider == "codex"
    assert container.codex.calls == [{"capability": "reasoning_chat", "refresh": True}]
    assert body["provider"] == "codex"
    assert [item["id"] for item in body["data"]] == ["gpt-5.5", "gpt-5.4-mini"]


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


def test_resolve_model_uses_kimi_default_for_legacy_local_model(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    model = chat.resolve_model("kimi", "local-model")

    assert model == "kimi-for-coding"


def test_resolve_model_uses_codex_default_for_legacy_local_model(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    model = chat.resolve_model("codex", "local-model")

    assert model == "gpt-5.5"


@pytest.mark.asyncio
async def test_codex_auth_status_and_logout(monkeypatch):
    container = FakeContainer()
    monkeypatch.setattr(chat, "get_container", lambda: container)

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status_response = await client.get("/chat/auth/codex/status")
        logout_response = await client.post("/chat/auth/codex/logout")

    assert status_response.status_code == 200
    assert status_response.json()["authenticated"] is True
    assert status_response.json()["email"] == "user@example.com"
    assert logout_response.status_code == 200
    assert logout_response.json()["logout_started"] is True
    assert container.codex.logout_calls == 1


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
                "feedback": "Include tests.",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["plan_status"] == "approved"
        assert body["plan_active"] is False
        assert body["injected_message"].startswith("Implement the following plan:")
        assert "Include tests." in body["injected_message"]

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
                "feedback": "Migration detail.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["plan_status"] == "draft"
        assert body["plan_active"] is True
        assert "Migration detail." in body["suggested_message"]

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
