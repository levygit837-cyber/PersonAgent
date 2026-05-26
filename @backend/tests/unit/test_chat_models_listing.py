"""Tests for models_listing endpoint extraction."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from personagent.adapters.api.routes.chat.models_listing import register_model_listing_routes
from personagent.application.dto import ChatRequestDTO

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubLLMBackend:
    def __init__(self) -> None:
        self.list_models_calls: list[dict] = []
        self.get_model_info_calls = 0

    async def list_models(self, *, capability: str | None = None, refresh: bool = False) -> dict:
        self.list_models_calls.append({"capability": capability, "refresh": refresh})
        return {"data": [{"id": "stub-model"}], "object": "list"}

    async def get_model_info(self) -> dict:
        self.get_model_info_calls += 1
        return {"data": [{"id": "llama-model"}], "object": "list"}

    def auth_status(self) -> dict[str, Any]:
        return {"authenticated": True, "user": "test-user"}

    async def logout(self) -> dict[str, Any]:
        return {"status": "logged_out"}


class _StubSettings:
    tools_enabled = True
    tool_workspace_root_path = "/ws"
    skill_roots: list[str] = []

    def __init__(self) -> None:
        self.llama_ctx_size = 4096
        self.llama_max_tokens = 2048
        self.nvidia_default_model = "nvidia-model"
        self.deepseek_default_model = "deepseek-model"


class _StubContainer:
    def __init__(self, llm_backend: _StubLLMBackend) -> None:
        self._llm_backend = llm_backend
        self.settings = _StubSettings()
        self.requested_provider: str | None = None
        self._tool_registry = _StubToolRegistry()

    def get_llm_backend(self, provider: str):
        self.requested_provider = provider
        return self._llm_backend

    async def get_conversation_repo(self, session: Any) -> Any:
        return _StubConversationRepo()

    def get_tool_runtime_config(self):
        return _StubToolRuntimeConfig()

    def get_tool_registry(self):
        return self._tool_registry

    def create_command_registry(self):
        return _StubCommandRegistry()

    def create_build_context_use_case(self, root: str):
        return _StubBuildContextUseCase()


class _StubToolRegistry:
    def get(self, name: str):
        return None


class _StubToolRuntimeConfig:
    skill_roots: list = []


class _StubCommandRegistry:
    def list_commands(self, workspace_root: Any = None) -> list:
        return []


class _StubCommandService:
    def list_prompt_commands(self, root: str) -> list:
        return []

    def list_builtin_commands(self) -> list:
        return []


class _StubConversationRepo:
    async def get_by_id(self, conv_id: Any) -> Any:
        return _StubConversation()

    async def update(self, conv: Any) -> None:
        pass


class _StubConversation:
    id = "conv-1"


class _StubBuildContextUseCase:
    pass


class _StubPromptPreviewUseCase:
    def __init__(self) -> None:
        self.requests: list[ChatRequestDTO] = []

    async def preview_prompt(self, dto: ChatRequestDTO) -> dict:
        self.requests.append(dto)
        return {
            "system_prompt": "# Test system prompt\n\nSecond line.",
            "sections": [],
            "surfaces": [],
            "dynamic_sections": [],
            "agent_states": [],
            "state_sections_used": [],
            "line_count": 2,
            "char_count": 25,
            "provider": dto.provider,
            "model": dto.model,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def llm_backend():
    return _StubLLMBackend()


@pytest.fixture
def container(llm_backend):
    return _StubContainer(llm_backend)


@pytest.fixture
def chat_module(container, llm_backend):
    """Simulate what the chat package exposes."""

    class _ChatModule:
        @staticmethod
        def get_container():
            return container

        @staticmethod
        def resolve_model(provider: str, model: str) -> str:
            if provider == "nvidia" and (not model or model == "local-model"):
                return container.settings.nvidia_default_model
            return model

        @staticmethod
        def resolve_context_workspace_root(request: Any) -> str:
            return "/resolved/workspace"

        @staticmethod
        def _create_chat_use_case(**kwargs: Any) -> _StubPromptPreviewUseCase:
            return _StubPromptPreviewUseCase()

    return _ChatModule


@pytest.fixture
def app_with_routes(monkeypatch, chat_module):
    """Create a FastAPI app with the model listing routes registered."""
    import personagent.adapters.api.routes.chat as chat_pkg

    monkeypatch.setattr(chat_pkg, "get_container", chat_module.get_container)
    monkeypatch.setattr(chat_pkg, "resolve_model", chat_module.resolve_model)
    monkeypatch.setattr(chat_pkg, "resolve_context_workspace_root", chat_module.resolve_context_workspace_root)
    monkeypatch.setattr(chat_pkg, "_create_chat_use_case", chat_module._create_chat_use_case)

    router = APIRouter()
    register_model_listing_routes(router)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app_with_routes):
    return TestClient(app_with_routes)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestModelsEndpoint:
    def test_returns_model_list(self, client):
        response = client.get("/models", params={"provider": "llama"})
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "list"

    def test_routes_to_provider_catalog(self, client, container):
        client.get("/models", params={"provider": "nvidia"})
        assert container.requested_provider == "nvidia"

    def test_passes_capability_and_refresh_params(self, client, llm_backend):
        client.get("/models", params={"provider": "nvidia", "capability": "chat", "refresh": "true"})
        assert llm_backend.list_models_calls == [{"capability": "chat", "refresh": True}]


class TestCodexAuthEndpoints:
    def test_auth_status_returns_200(self, client):
        response = client.get("/auth/codex/status")
        assert response.status_code == 200

    def test_auth_logout_returns_200(self, client):
        response = client.post("/auth/codex/logout")
        assert response.status_code == 200


class TestCommandsEndpoint:
    def test_returns_empty_list_when_no_commands(self, client):
        response = client.get("/commands")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestPromptPreviewEndpoint:
    def test_returns_200_with_valid_request(self, client):
        response = client.post(
            "/prompt/preview",
            json={"message": "test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "system_prompt" in body

    def test_returns_400_for_invalid_conversation_id(self, client):
        response = client.post(
            "/prompt/preview",
            json={"message": "test", "conversation_id": "not-a-uuid"},
        )
        assert response.status_code == 400


class TestRouteRegistration:
    def test_all_routes_are_registered(self, app_with_routes):
        route_paths = [r.path for r in app_with_routes.routes]
        assert "/models" in route_paths
        assert "/auth/codex/status" in route_paths
        assert "/auth/codex/logout" in route_paths
        assert "/commands" in route_paths
        assert "/prompt/preview" in route_paths

    def test_dynamic_lookup_uses_monkeypatched_functions(self, app_with_routes, monkeypatch):
        """Verify that the dynamic _chat() lookup picks up patched values."""
        import personagent.adapters.api.routes.chat as chat_pkg

        call_count = 0

        def counting_get_container():
            nonlocal call_count
            call_count += 1
            return _StubContainer(_StubLLMBackend())

        monkeypatch.setattr(chat_pkg, "get_container", counting_get_container)
        client = TestClient(app_with_routes)
        client.get("/models", params={"provider": "llama"})
        assert call_count >= 1
