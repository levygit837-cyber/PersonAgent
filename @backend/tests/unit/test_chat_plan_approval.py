"""Tests for plan approval endpoint extraction."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from personagent.adapters.api.routes.chat.plan_approval import register_plan_approval_routes
from personagent.domain.conversation.models import Conversation

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubConversationRepo:
    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation
        self.update_calls: list[dict[str, Any]] = []

    async def get_by_id(self, conv_id: Any) -> Conversation | None:
        if str(conv_id) == str(self._conversation.id):
            return self._conversation
        return None

    async def update(self, conversation: Any) -> None:
        self.update_calls.append({"session_status": conversation.metadata.get("session_status")})


def _make_conversation(plan_status: str = "awaiting_approval", approval_id: str = "appr-1") -> Conversation:
    conv = Conversation()
    conv.metadata["plan_mode"] = {
        "active": True,
        "status": plan_status,
        "plan_id": "plan_1",
        "plan_content": "## Plan\n\n1. Do the thing.\n2. Test it.",
        "approval_id": approval_id,
        "feedback": None,
        "cancelled": False,
    }
    return conv


async def _stub_load_conversation_for_decision(conversation_id: str, session: Any) -> tuple[Any, Any]:
    conv = _make_conversation()
    repo = _StubConversationRepo(conv)
    return conv, repo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def chat_module():
    class _ChatModule:
        _load_conversation_for_decision = _stub_load_conversation_for_decision

    return _ChatModule


@pytest.fixture
def app(monkeypatch, chat_module):
    import personagent.adapters.api.routes.chat as chat_pkg

    monkeypatch.setattr(chat_pkg, "_load_conversation_for_decision", chat_module._load_conversation_for_decision)

    router = APIRouter()
    register_plan_approval_routes(router)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestApprovePlan:
    def test_approve_returns_200_and_injected_message(self, client):
        response = client.post(
            "/plan/approve",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "injected_message" in body
        assert "Approved Plan" in body["injected_message"]

    def test_approve_includes_user_feedback(self, client):
        response = client.post(
            "/plan/approve",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
                "feedback": "Add tests too.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "Add tests too." in body["injected_message"]

    def test_approve_returns_400_when_plan_content_empty(self, monkeypatch, client, chat_module):
        async def _empty_plan_load(conversation_id: str, session: Any) -> tuple[Any, Any]:
            conv = _make_conversation()
            conv.metadata["plan_mode"]["plan_content"] = ""
            return conv, _StubConversationRepo(conv)

        import personagent.adapters.api.routes.chat as chat_pkg

        monkeypatch.setattr(chat_pkg, "_load_conversation_for_decision", _empty_plan_load)
        response = client.post(
            "/plan/approve",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
            },
        )
        assert response.status_code == 400


class TestContinuePlan:
    def test_continue_returns_200_and_suggested_message(self, client):
        response = client.post(
            "/plan/continue",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "suggested_message" in body
        assert "Continue planning" in body["suggested_message"]

    def test_continue_includes_user_feedback_in_suggested_message(self, client):
        response = client.post(
            "/plan/continue",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
                "feedback": "Make it simpler.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "Make it simpler." in body["suggested_message"]


class TestCancelPlan:
    def test_cancel_returns_200(self, client):
        response = client.post(
            "/plan/cancel",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "appr-1",
            },
        )
        assert response.status_code == 200

    def test_cancel_returns_409_when_approval_id_mismatches(self, client):
        response = client.post(
            "/plan/cancel",
            json={
                "conversation_id": str(uuid4()),
                "approval_id": "wrong-id",
            },
        )
        assert response.status_code == 409

    def test_cancel_allows_without_approval_id(self, client):
        response = client.post(
            "/plan/cancel",
            json={"conversation_id": str(uuid4())},
        )
        assert response.status_code == 200


class TestRouteRegistration:
    def test_all_plan_routes_are_registered(self, app):
        route_paths = [r.path for r in app.routes]
        assert "/plan/approve" in route_paths
        assert "/plan/continue" in route_paths
        assert "/plan/cancel" in route_paths

    def test_plan_approve_requires_conversation_id(self, client):
        response = client.post("/plan/approve", json={})
        assert response.status_code == 422

    def test_plan_continue_requires_conversation_id(self, client):
        response = client.post("/plan/continue", json={})
        assert response.status_code == 422

    def test_plan_cancel_requires_conversation_id(self, client):
        response = client.post("/plan/cancel", json={})
        assert response.status_code == 422
