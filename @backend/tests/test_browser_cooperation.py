from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.application.services.browser_action_arbiter import BrowserActionArbiter
from personagent.application.services.browser_cooperation import (
    BROWSER_COOPERATION_METADATA_KEY,
    _normalize_event,
    browser_agent_context_reminder,
)
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.tools import ToolPermissionBehavior, ToolUseContext
from personagent.interfaces.api.routes import sessions


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
        return []


class FakeContainer:
    def __init__(self, repo: MemoryConversationRepository) -> None:
        self.repo = repo

    async def get_conversation_repo(self, _session):
        return self.repo


class FakeBrowserCooperationService:
    async def set_cooperation(self, conversation, *, browser_id: str, enabled: bool, mode: str | None = None):
        cooperation = {
            "enabled": enabled,
            "mode": mode or "observe_only",
            "agent_control": mode or "observe_only",
            "browser_id": browser_id,
            "recent_actions": [],
            "page_state": {},
        }
        conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {})[browser_id] = cooperation
        return {"cooperation": cooperation, "state_patch": {"cooperation": cooperation}}

    async def ingest_events(self, conversation, *, browser_id: str, events: list[dict]):
        cooperation = conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {}).setdefault(
            browser_id,
            {"enabled": True, "mode": "observe_only", "agent_control": "observe_only", "browser_id": browser_id},
        )
        cooperation["recent_actions"] = [str(event.get("semantic_label") or event.get("kind")) for event in events]
        return {
            "accepted_count": len(events),
            "dropped_count": 0,
            "state_patch": {"cooperation": cooperation},
            "notifications": cooperation["recent_actions"],
        }


def test_browser_event_normalization_redacts_sensitive_fields():
    event = _normalize_event(
        {
            "event_id": "evt-1",
            "kind": "input",
            "source": "user",
            "url": "https://example.com/login",
            "target": {
                "input_type": "password",
                "name": "password",
                "placeholder": "Password",
            },
            "payload": {
                "value": "super-secret-password",
                "page_state": {"visible_primary_buttons": ["Sign in"]},
            },
        },
        conversation_id="11111111-1111-1111-1111-111111111111",
        browser_id="browser-1",
        sequence=7,
    )

    assert event.sequence == 7
    assert event.importance == "high"
    assert event.payload["value"] == "[REDACTED]"
    assert event.payload["value_redacted"] is True
    assert event.payload["value_hash"] != "super-secret-password"
    assert "redacted value" in event.semantic_label


def test_browser_agent_context_reminder_includes_compact_event_and_action_channels():
    reminder = browser_agent_context_reminder(
        {
            BROWSER_COOPERATION_METADATA_KEY: {
                "browser-1": {
                    "enabled": True,
                    "mode": "observe_only",
                    "agent_control": "observe_only",
                    "browser_id": "browser-1",
                    "url": "https://example.com/checkout",
                    "recent_actions": ["clicked Coupon", "updated Coupon with a redacted value"],
                    "page_state": {
                        "modal_open": False,
                        "focused_field": None,
                        "visible_primary_buttons": ["Finish order", "Back"],
                    },
                }
            }
        }
    )

    assert reminder is not None
    assert "Browser Cooperation Context" in reminder
    assert "browser_to_agent" in reminder
    assert "agent_to_arbiter_to_browser" in reminder
    assert "observe_only" in reminder
    assert "Finish order" in reminder


def test_browser_action_arbiter_observe_only_requires_approval(tmp_path):
    context = _tool_context(
        tmp_path,
        metadata={
            BROWSER_COOPERATION_METADATA_KEY: {
                "browser-1": {
                    "enabled": True,
                    "mode": "observe_only",
                    "agent_control": "observe_only",
                    "browser_id": "browser-1",
                }
            }
        },
    )

    decision = BrowserActionArbiter().decide(
        tool_name="BrowserClick",
        arguments={"node_id": "pa_button"},
        context=context,
    )

    assert decision.behavior == ToolPermissionBehavior.ASK
    assert decision.decision == "observe_only_requires_approval"


def test_browser_action_arbiter_agent_control_allows_idle_non_destructive_action(tmp_path):
    context = _tool_context(
        tmp_path,
        metadata={
            BROWSER_COOPERATION_METADATA_KEY: {
                "browser-1": {
                    "enabled": True,
                    "mode": "agent_control",
                    "agent_control": "agent_control",
                    "browser_id": "browser-1",
                    "last_user_activity_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
                }
            }
        },
    )

    decision = BrowserActionArbiter().decide(
        tool_name="BrowserClick",
        arguments={"node_id": "pa_next_button"},
        context=context,
    )

    assert decision.behavior == ToolPermissionBehavior.ALLOW
    assert decision.decision == "allow"


def test_browser_action_arbiter_agent_control_requires_approval_for_recent_human_activity(tmp_path):
    context = _tool_context(
        tmp_path,
        metadata={
            BROWSER_COOPERATION_METADATA_KEY: {
                "browser-1": {
                    "enabled": True,
                    "mode": "agent_control",
                    "agent_control": "agent_control",
                    "browser_id": "browser-1",
                    "last_user_activity_at": datetime.now(UTC).isoformat(),
                }
            }
        },
    )

    decision = BrowserActionArbiter().decide(
        tool_name="BrowserType",
        arguments={"node_id": "pa_login", "text": "continue", "submit": True},
        context=context,
    )

    assert decision.behavior == ToolPermissionBehavior.ASK
    assert decision.decision == "recent_user_activity"


@pytest.mark.asyncio
async def test_browser_cooperation_api_toggles_and_ingests_events(monkeypatch):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="Browser Cooperation")
    await repo.create(conversation)
    fake_service = FakeBrowserCooperationService()

    async def fake_get_db():
        yield object()

    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))
    monkeypatch.setattr(sessions, "_browser_cooperation_service", lambda _session: fake_service)

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        toggle = await client.post(
            f"/sessions/{conversation.id}/browser/browser-1/cooperation",
            json={"enabled": True, "mode": "observe_only"},
        )
        ingest = await client.post(
            f"/sessions/{conversation.id}/browser/browser-1/events",
            json={
                "events": [
                    {
                        "event_id": "evt-1",
                        "kind": "click",
                        "semantic_label": "clicked Apply",
                    }
                ]
            },
        )

    assert toggle.status_code == 200
    assert toggle.json()["cooperation"]["enabled"] is True
    assert ingest.status_code == 200
    assert ingest.json()["accepted_count"] == 1
    assert repo.conversations[conversation.id].metadata[BROWSER_COOPERATION_METADATA_KEY]["browser-1"][
        "recent_actions"
    ] == ["clicked Apply"]


def _tool_context(
    root: Path,
    *,
    metadata: dict | None = None,
    conversation_id: str = "conversation-1",
) -> ToolUseContext:
    return ToolUseContext(
        conversation_id=conversation_id,
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        metadata=metadata or {},
    )
