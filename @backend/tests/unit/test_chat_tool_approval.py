"""Tests for tool approval endpoint extraction."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from personagent.interfaces.api.routes.chat.tool_approval import register_tool_approval_routes

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubConversation:
    id = "conv-1"
    metadata: dict[str, Any] = {
        "pending_tool_approval": {
            "approval_id": "tid-1",
            "tool_call_id": "call-1",
            "tool_name": "bash",
            "status": "awaiting_approval",
            "arguments": {"cmd": "ls"},
        }
    }

    def add_message(self, message: Any) -> None:
        pass


class _StubConversationRepo:
    async def get_by_id(self, conv_id: Any) -> _StubConversation | None:
        return _StubConversation()

    async def update(self, conversation: Any) -> None:
        pass


class _StubToolResult:
    tool_call_id = "call-1"
    tool_name = "bash"
    status: Any = None
    content = "output"
    is_error = False
    data: dict = {}
    metadata: dict = {}

    def to_stream_dict(self) -> dict:
        return {"tool_call_id": self.tool_call_id, "content": self.content}


async def _stub_load_conversation_for_decision(conversation_id: str, session: Any) -> tuple[Any, Any]:
    return _StubConversation(), _StubConversationRepo()


async def _stub_approve_pending_tool_call(
    *, request: Any, conversation: Any, conv_repo: Any, container: Any
) -> tuple[Any, Any, dict[str, Any], _StubToolResult]:
    pending = conversation.metadata.get("pending_tool_approval", {})
    return None, None, pending, _StubToolResult()


def _stub_get_container() -> Any:
    return object()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    import personagent.interfaces.api.routes.chat as chat_pkg

    monkeypatch.setattr(chat_pkg, "_load_conversation_for_decision", _stub_load_conversation_for_decision)
    monkeypatch.setattr(chat_pkg, "_approve_pending_tool_call", _stub_approve_pending_tool_call)
    monkeypatch.setattr(chat_pkg, "get_container", _stub_get_container)

    router = APIRouter()
    register_tool_approval_routes(router)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestApproveTool:
    def test_approve_returns_200(self, client):
        response = client.post(
            "/tools/approve",
            json={
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "approval_id": "tid-1",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["resume_available"] is True

    def test_approve_requires_approval_id(self, client):
        response = client.post(
            "/tools/approve",
            json={"conversation_id": "00000000-0000-0000-0000-000000000001"},
        )
        assert response.status_code == 422


class TestRejectTool:
    def test_reject_returns_200(self, client):
        response = client.post(
            "/tools/reject",
            json={
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "approval_id": "tid-1",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"
        assert body["resume_available"] is False

    def test_reject_with_wrong_approval_id_returns_409(self, monkeypatch, client):
        import personagent.interfaces.api.routes.chat as chat_pkg

        async def _load_mismatched(conversation_id: str, session: Any) -> tuple[Any, Any]:
            conv = _StubConversation()
            conv.metadata["pending_tool_approval"]["approval_id"] = "other-id"
            return conv, _StubConversationRepo()

        monkeypatch.setattr(chat_pkg, "_load_conversation_for_decision", _load_mismatched)
        response = client.post(
            "/tools/reject",
            json={
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "approval_id": "tid-1",
            },
        )
        assert response.status_code == 409


class TestAnswerUserQuestion:
    def test_requires_conversation_id(self, client):
        response = client.post("/user-question/respond/stream", json={})
        assert response.status_code == 422


class TestRouteRegistration:
    def test_all_tool_routes_are_registered(self, app):
        route_paths = [r.path for r in app.routes]
        assert "/tools/approve" in route_paths
        assert "/tools/approve/stream" in route_paths
        assert "/tools/reject" in route_paths
        assert "/user-question/respond/stream" in route_paths
