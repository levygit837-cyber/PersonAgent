import json
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.application.services import session_panel
from personagent.application.services.session_panel import SessionPanelService
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository
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


def test_session_panel_aggregates_usage_files_sources_and_todos(tmp_path):
    conversation = Conversation(title="Painel")
    conversation.add_message(
        Message(
            role=Role.ASSISTANT,
            content="final answer",
            tool_calls=[
                {"id": "call_write", "function": {"name": "Write", "arguments": "{}"}},
            ],
            metadata={
                "usage": {
                    "completion_tokens": 12,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                },
                "reasoning_content": "hidden analysis",
            },
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            tool_call_id="call_write",
            metadata={
                "tool_name": "Write",
                "data": {
                    "type": "file_write",
                    "path": str(tmp_path / "app.py"),
                    "display_path": "app.py",
                    "diff": "--- a/app.py\n+++ b/app.py\n-old\n+new",
                    "added_lines": 1,
                    "removed_lines": 1,
                },
            },
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            tool_call_id="call_web",
            metadata={
                "tool_name": "WebFetch",
                "data": {
                    "type": "web_fetch",
                    "url": "https://example.com/docs",
                    "title": "Example Docs",
                    "description": "Reference page",
                },
            },
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            tool_call_id="call_todo",
            metadata={
                "tool_name": "TodoWrite",
                "data": {"type": "todos", "todos": [{"content": "Implement", "status": "completed"}]},
            },
        )
    )

    snapshot = SessionPanelService(tmp_path).panel_snapshot(conversation)

    assert snapshot["usage"]["agent_output_tokens"] == {"value": 8, "estimated": False}
    assert snapshot["usage"]["thinking_output_tokens"] == {"value": 4, "estimated": False}
    assert snapshot["usage"]["tool_calls"]["value"] == 3
    assert snapshot["usage"]["todos_created"]["value"] == 1
    assert snapshot["changed_files"][0]["display_path"] == "app.py"
    assert snapshot["changed_files"][0]["added_lines"] == 1
    assert snapshot["sources"][0]["domain"] == "example.com"


@pytest.mark.asyncio
async def test_session_panel_api_returns_snapshot(monkeypatch, tmp_path):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="API panel")
    await repo.create(conversation)
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))

    async def fake_get_db():
        yield object()

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/sessions/{conversation.id}/panel",
            params={"workspace_root": str(tmp_path)},
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == str(conversation.id)


@pytest.mark.asyncio
async def test_session_project_detail_api_returns_detail(monkeypatch, tmp_path):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="API detail")
    await repo.create(conversation)
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))

    def fake_project_detail(self, detail_type, detail_id):
        return {
            "type": detail_type,
            "id": detail_id,
            "title": "feat: panel",
            "metadata": {"workspace": str(self.workspace_root)},
        }

    monkeypatch.setattr(SessionPanelService, "project_detail", fake_project_detail)

    async def fake_get_db():
        yield object()

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/sessions/{conversation.id}/project/details",
            params={"type": "commit", "id": "abc123", "workspace_root": str(tmp_path)},
        )

    assert response.status_code == 200
    assert response.json()["type"] == "commit"
    assert response.json()["id"] == "abc123"


def test_project_commit_detail_uses_gh_when_available(monkeypatch, tmp_path):
    def fake_run(command, cwd, timeout=5):
        if command == ["git", "remote", "get-url", "origin"]:
            return session_panel._RunResult(0, "https://github.com/acme/repo.git\n", "")
        if command == ["gh", "api", "repos/acme/repo/commits/abc123"]:
            return session_panel._RunResult(
                0,
                json.dumps(
                    {
                        "sha": "abc123",
                        "html_url": "https://github.com/acme/repo/commit/abc123",
                        "commit": {
                            "message": "feat: panel",
                            "author": {"name": "Dev", "date": "2026-04-27T00:00:00Z"},
                        },
                        "stats": {"additions": 2, "deletions": 1, "total": 3},
                        "files": [
                            {
                                "filename": "panel.tsx",
                                "status": "modified",
                                "additions": 2,
                                "deletions": 1,
                                "changes": 3,
                                "patch": "@@ patch",
                            }
                        ],
                    }
                ),
                "",
            )
        return session_panel._RunResult(1, "", "unexpected command")

    monkeypatch.setattr(session_panel, "_run", fake_run)

    detail = SessionPanelService(tmp_path).project_detail("commit", "abc123")

    assert detail["source"] == "gh"
    assert detail["title"] == "feat: panel"
    assert detail["files"][0]["filename"] == "panel.tsx"


def test_project_snapshot_uses_git_repo_fallback_when_gh_fails(monkeypatch, tmp_path):
    conversation = Conversation(title="Fallback")

    def fake_run(command, cwd, timeout=5):
        if command[:3] == ["gh", "repo", "view"]:
            return session_panel._RunResult(1, "", "gh not authenticated")
        if command == ["git", "remote", "get-url", "origin"]:
            return session_panel._RunResult(0, "https://github.com/acme/repo.git\n", "")
        if command == ["git", "symbolic-ref", "refs/remotes/origin/HEAD"]:
            return session_panel._RunResult(0, "refs/remotes/origin/main\n", "")
        if command == ["gh", "pr", "list", "--limit", "5", "--state", "all", "--json", "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName"]:
            return session_panel._RunResult(1, "", "gh failed")
        if command == ["git", "rev-parse", "--git-dir"]:
            return session_panel._RunResult(1, "", "not a git repo")
        return session_panel._RunResult(1, "", "unexpected command")

    monkeypatch.setattr(session_panel, "_run", fake_run)

    snapshot = SessionPanelService(tmp_path).panel_snapshot(conversation)

    assert snapshot["project"]["repo"]["source"] == "git"
    assert snapshot["project"]["repo"]["name_with_owner"] == "acme/repo"
    assert any("gh repo view" in error for error in snapshot["project"]["errors"])
