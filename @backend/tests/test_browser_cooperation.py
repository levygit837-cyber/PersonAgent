from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from personagent.application.services.browser_action_arbiter import BrowserActionArbiter
from personagent.application.services.browser_cooperation import (
    BROWSER_COOPERATION_METADATA_KEY,
    _normalize_event,
    attach_browser_action_proposal,
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
        current = conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {}).get(browser_id, {})
        cooperation = {
            **current,
            "enabled": enabled,
            "mode": mode or "observe_only",
            "agent_control": mode or "observe_only",
            "browser_id": browser_id,
            "recent_actions": current.get("recent_actions", []),
            "useful_timeline": current.get("useful_timeline", []),
            "recent_user_events": current.get("recent_user_events", []),
            "recent_agent_events": current.get("recent_agent_events", []),
            "page_state": current.get("page_state", {}),
            "pending_action_proposals": current.get("pending_action_proposals", []),
        }
        conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {})[browser_id] = cooperation
        return {"cooperation": cooperation, "state_patch": {"cooperation": cooperation}}

    async def ingest_events(self, conversation, *, browser_id: str, events: list[dict]):
        cooperation = conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {}).setdefault(
            browser_id,
            {"enabled": True, "mode": "observe_only", "agent_control": "observe_only", "browser_id": browser_id},
        )
        cooperation["recent_actions"] = [str(event.get("semantic_label") or event.get("kind")) for event in events]
        cooperation["useful_timeline"] = [
            {"event_id": event.get("event_id"), "role": event.get("trace_role", event.get("source", "user")), "kind": event.get("kind")}
            for event in events
        ]
        return {
            "accepted_count": len(events),
            "dropped_count": 0,
            "state_patch": {"cooperation": cooperation},
            "notifications": cooperation["recent_actions"],
        }

    async def get_snapshot(self, conversation, *, browser_id: str, raw_limit: int = 80):
        cooperation = conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {}).setdefault(
            browser_id,
            {"enabled": True, "mode": "observe_only", "agent_control": "observe_only", "browser_id": browser_id},
        )
        return {
            "type": "snapshot",
            "cooperation": cooperation,
            "state_patch": {"cooperation": cooperation},
            "raw_events": [],
            "useful_timeline": cooperation.get("useful_timeline", []),
            "pending_action_proposals": cooperation.get("pending_action_proposals", []),
        }

    async def resolve_proposal(self, conversation, *, browser_id: str, proposal_id: str, status: str):
        cooperation = conversation.metadata.setdefault(BROWSER_COOPERATION_METADATA_KEY, {}).setdefault(
            browser_id,
            {"enabled": True, "mode": "observe_only", "agent_control": "observe_only", "browser_id": browser_id},
        )
        proposals = []
        resolved = None
        for proposal in cooperation.get("pending_action_proposals", []):
            if proposal.get("proposal_id") == proposal_id:
                proposal = {**proposal, "status": status}
                resolved = proposal
            proposals.append(proposal)
        cooperation["pending_action_proposals"] = proposals
        return {"type": "proposal.resolved", "proposal": resolved, "state_patch": {"cooperation": cooperation}}


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
    assert event.payload["page_state"]["visible_primary_buttons"] == ["Sign in"]
    assert "redacted value" in event.semantic_label


def test_browser_event_normalization_v2_fields_and_url_redaction():
    event = _normalize_event(
        {
            "event_id": "evt-2",
            "kind": "click",
            "raw_kind": "pointer-click",
            "source": "browser",
            "channel": "trace",
            "trace_role": "agent",
            "visibility": "useful",
            "url": "https://example.com/callback?email=user@example.com&token=abc123&ok=1",
            "target": {"node_id": "node-1", "label": "Apply", "bounds": {"x": 10, "y": 20, "width": 80, "height": 30}},
            "payload": {"text": "normal text"},
            "coordinates": {"x": 15, "y": 22},
            "duration_ms": 420,
            "trace_effect": "click",
            "correlation_id": "corr-1",
        },
        conversation_id="11111111-1111-1111-1111-111111111111",
        browser_id="browser-1",
        sequence=8,
    )

    assert event.channel == "trace"
    assert event.trace_role == "agent"
    assert event.visibility == "useful"
    assert event.raw_kind == "pointer-click"
    assert "email=%5BREDACTED%5D" in event.url
    assert "token=%5BREDACTED%5D" in event.url
    assert "ok=1" in event.url
    assert event.coordinates["x"] == 15
    assert event.duration_ms == 420
    assert event.trace_effect == "click"
    assert event.correlation_id == "corr-1"


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
                    "useful_timeline": [{"label": "clicked Apply", "role": "user"}],
                    "recent_user_events": [{"label": "clicked Apply", "kind": "click"}],
                    "recent_agent_events": [{"label": "agent highlighted Apply", "kind": "click"}],
                    "page_state": {
                        "modal_open": False,
                        "focused_field": None,
                        "visible_primary_buttons": ["Finish order", "Back"],
                        "selected_element": {"node_id": "node-1"},
                        "active_proposal_id": "proposal-1",
                    },
                    "pending_action_proposals": [{"proposal_id": "proposal-1", "status": "awaiting_approval"}],
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
    assert "useful_timeline" in reminder
    assert "recent_agent_events" in reminder
    assert "proposal-1" in reminder


def test_attach_browser_action_proposal_persists_browser_visible_metadata():
    metadata = {
        BROWSER_COOPERATION_METADATA_KEY: {
            "browser-1": {
                "enabled": True,
                "mode": "suggest_before_action",
                "agent_control": "suggest_before_action",
                "browser_id": "browser-1",
            }
        }
    }
    proposal = attach_browser_action_proposal(
        metadata,
        pending={
            "approval_id": "approval-1",
            "tool_call_id": "tool-call-1",
            "tool_name": "BrowserClick",
            "arguments": {"node_id": "node-1", "text": "normal"},
        },
        arbiter_metadata={
            "browser_id": "browser-1",
            "url": "https://example.com",
            "mode": "suggest_before_action",
            "target": {"node_id": "node-1", "bounds": {"x": 10, "y": 20, "width": 30, "height": 10}},
        },
        message="Approve BrowserClick.",
    )

    assert proposal is not None
    state = metadata[BROWSER_COOPERATION_METADATA_KEY]["browser-1"]
    assert state["pending_action_proposals"][0]["approval_id"] == "approval-1"
    assert state["page_state"]["active_proposal_id"] == proposal["proposal_id"]


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


def test_browser_cooperation_websocket_snapshot_ingest_mode_and_proposal(monkeypatch):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="Browser Cooperation WS")
    conversation.metadata[BROWSER_COOPERATION_METADATA_KEY] = {
        "browser-1": {
            "enabled": True,
            "mode": "observe_only",
            "agent_control": "observe_only",
            "browser_id": "browser-1",
            "pending_action_proposals": [{"proposal_id": "proposal-1", "status": "awaiting_approval"}],
        }
    }
    repo.conversations[conversation.id] = conversation
    fake_service = FakeBrowserCooperationService()

    async def fake_get_db():
        yield object()

    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))
    monkeypatch.setattr(sessions, "_browser_cooperation_service", lambda _session: fake_service)

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/sessions/{conversation.id}/browser/browser-1/cooperation/ws") as ws,
    ):
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["cooperation"]["mode"] == "observe_only"

        ws.send_json(
            {
                "type": "event_batch",
                "events": [
                    {
                        "event_id": "evt-ws",
                        "kind": "click",
                        "source": "user",
                        "trace_role": "user",
                        "semantic_label": "clicked Apply",
                    }
                ],
            }
        )
        accepted = ws.receive_json()
        timeline = ws.receive_json()
        assert accepted["type"] == "event_batch.accepted"
        assert accepted["accepted_count"] == 1
        assert timeline["type"] == "timeline.patch"

        ws.send_json({"type": "mode.set", "enabled": True, "mode": "agent_control"})
        changed = ws.receive_json()
        assert changed["type"] == "mode.changed"
        assert changed["cooperation"]["mode"] == "agent_control"

        ws.send_json({"type": "proposal.approve", "proposal_id": "proposal-1"})
        resolved = ws.receive_json()
        assert resolved["type"] == "proposal.resolved"
        assert resolved["proposal"]["status"] == "approved"


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
