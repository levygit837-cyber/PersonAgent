import json
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from personagent.infrastructure.artifacts import store_bytes_artifact, store_text_artifact

from personagent.adapters.api.routes import artifacts, sessions
from personagent.adapters.api.routes.workspace_grants import register_workspace_grant
from personagent.application.services import session_panel
from personagent.application.services.session.session_panel import SessionPanelService
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.conversation.repositories import ConversationRepository
from personagent.infrastructure.settings.settings import reset_settings


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


class FakeBrowserWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def view_snapshot(self, **kwargs):
        self.calls.append(("view_snapshot", kwargs))
        return _browser_view(kwargs["browser_id"])

    async def view_navigate(self, **kwargs):
        self.calls.append(("view_navigate", kwargs))
        return _browser_view(kwargs["browser_id"], kwargs["url"])

    async def view_history(self, **kwargs):
        self.calls.append(("view_history", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com/back")

    async def view_reload(self, **kwargs):
        self.calls.append(("view_reload", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com")

    async def view_click(self, **kwargs):
        self.calls.append(("view_click", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com/clicked")

    async def view_key(self, **kwargs):
        self.calls.append(("view_key", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com")

    async def view_scroll(self, **kwargs):
        self.calls.append(("view_scroll", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com")

    async def view_act(self, **kwargs):
        self.calls.append(("view_act", kwargs))
        return _browser_view(kwargs["browser_id"], "https://example.com/action")


class FakeContainer:
    def __init__(
        self,
        repo: MemoryConversationRepository,
        browser_worker: FakeBrowserWorker | None = None,
    ) -> None:
        self.repo = repo
        self.browser_worker = browser_worker or FakeBrowserWorker()

    async def get_conversation_repo(self, _session):
        return self.repo

    def get_lightpanda_browser_worker(self):
        return self.browser_worker


def grant_test_workspace(monkeypatch: pytest.MonkeyPatch, workspace) -> None:
    monkeypatch.setenv("PERSONAGENT_WORKSPACE_GRANTS_PATH", str(workspace / "workspace_grants.json"))
    reset_settings()
    register_workspace_grant(workspace, source="test")


def _browser_view(browser_id: str, url: str = "about:blank") -> dict:
    return {
        "type": "browser_view",
        "browser_id": browser_id,
        "url": url,
        "title": "Example",
        "html": "<html><body>Example</body></html>",
        "document_html": "<html><body><a data-pa-node-id='pa_link' href='https://example.com'>Example</a></body></html>",
        "render_mode": "html_mirror",
        "css_fidelity": "original",
        "fallback_reason": "",
        "element_map": [
            {
                "node_id": "pa_link",
                "role": "link",
                "tag": "a",
                "text": "Example",
                "href": "https://example.com",
                "selector": "html > body > a:nth-of-type(1)",
            }
        ],
        "annotations": [],
        "timeline_events": [],
        "browser_snapshot": {
            "document_html": "<html><body><a data-pa-node-id='pa_link' href='https://example.com'>Example</a></body></html>",
            "url": url,
            "title": "Example",
            "render_mode": "html_mirror",
            "css_fidelity": "original",
            "fallback_reason": "",
            "element_map": [],
        },
        "user_agent": "Lightpanda/1.0",
        "image_data": "iVBORw0KGgo=",
        "image_mime_type": "image/png",
        "screenshot_method": "playwright_page_screenshot",
        "screenshot_error": "",
        "viewport_width": 1024,
        "viewport_height": 720,
        "can_capture": True,
    }


@pytest.mark.asyncio
async def test_session_panel_aggregates_usage_files_sources_and_todos(tmp_path):
    conversation = Conversation(title="Panel")
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

    snapshot = await SessionPanelService(tmp_path).panel_snapshot(conversation)

    assert snapshot["usage"]["agent_output_tokens"] == {"value": 8, "estimated": False}
    assert snapshot["usage"]["thinking_output_tokens"] == {"value": 4, "estimated": False}
    assert snapshot["usage"]["tool_calls"]["value"] == 3
    assert snapshot["usage"]["todos_created"]["value"] == 1
    assert snapshot["changed_files"][0]["display_path"] == "app.py"
    assert snapshot["changed_files"][0]["added_lines"] == 1
    assert snapshot["sources"][0]["domain"] == "example.com"


@pytest.mark.asyncio
async def test_session_panel_aggregates_memory_trace(tmp_path):
    conversation = Conversation(title="Memory panel")
    conversation.add_message(
        Message(
            role=Role.ASSISTANT,
            content="answer",
            metadata={
                "memory_trace": {
                    "classic": [
                        {
                            "path": "/tmp/default/memory/python_pref.md",
                            "name": "python_pref.md",
                            "snippet": "I prefer Python.",
                        }
                    ],
                    "operational": [
                        {
                            "type": "decision",
                            "summary": "Keep memory visible.",
                            "evidence": ["Trace evidence"],
                            "paths": ["@backend/src/personagent/application/use_cases/chat_completion.py"],
                            "source_ids": ["mem-1"],
                        }
                    ],
                    "summary": {
                        "total_used": 2,
                        "classic_count": 1,
                        "rag_count": 1,
                        "omitted_count": 3,
                        "budget_used": 50,
                        "budget_tokens": 1200,
                        "latency_ms": 20,
                    },
                    "filters_applied": {"workspace_root": "/tmp/default"},
                }
            },
        )
    )

    snapshot = await SessionPanelService(tmp_path).panel_snapshot(conversation)

    memory = snapshot["memory"]
    assert memory["total_recalls"] == 1
    assert memory["classic_used"] == 1
    assert memory["rag_used"] == 1
    assert memory["omitted"] == 3
    assert memory["avg_latency_ms"] == 20
    assert memory["budget_used"] == 50
    assert {item["source"] for item in memory["most_used"]} == {"classic", "rag"}


@pytest.mark.asyncio
async def test_session_panel_api_returns_snapshot(monkeypatch, tmp_path):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="API panel")
    await repo.create(conversation)
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))
    grant_test_workspace(monkeypatch, tmp_path)

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
async def test_session_browser_api_controls_lightpanda_worker(monkeypatch):
    repo = MemoryConversationRepository()
    browser_worker = FakeBrowserWorker()
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo, browser_worker))

    app = FastAPI()
    app.include_router(sessions.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sessions/browser/panel-tab/navigate",
            json={"url": "https://example.com", "width": 900, "height": 500},
        )
        click_response = await client.post(
            "/sessions/browser/panel-tab/click",
            json={"x": 120, "y": 80, "width": 900, "height": 500, "button": "left"},
        )

    assert response.status_code == 200
    assert response.json()["url"] == "https://example.com"
    assert click_response.status_code == 200
    assert browser_worker.calls[0] == (
        "view_navigate",
        {
            "browser_id": "panel-tab",
            "url": "https://example.com",
            "width": 900,
            "height": 500,
            "cache_mode": "prefer_live",
            "wait_for_styles": True,
        },
    )
    assert browser_worker.calls[1][0] == "view_click"


@pytest.mark.asyncio
async def test_conversation_browser_workspace_persists_annotations_and_timeline(monkeypatch):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="Browser workspace")
    await repo.create(conversation)
    browser_worker = FakeBrowserWorker()
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo, browser_worker))

    async def fake_get_db():
        yield object()

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        navigate = await client.post(
            f"/sessions/{conversation.id}/browser/{conversation.id}/navigate",
            json={"url": "https://example.com", "width": 900, "height": 500},
        )
        action = await client.post(
            f"/sessions/{conversation.id}/browser/{conversation.id}/action",
            json={"node_id": "pa_link", "action": "click", "width": 900, "height": 500},
        )
        annotation = await client.post(
            f"/sessions/{conversation.id}/browser/{conversation.id}/annotations",
            json={
                "node_id": "pa_link",
                "body": "Reference this link",
                "quote": "Example",
                "url": "https://example.com",
                "title": "Example",
            },
        )

    assert navigate.status_code == 200
    assert navigate.json()["element_map"][0]["node_id"] == "pa_link"
    assert action.status_code == 200
    assert action.json()["timeline_events"][-1]["event_type"] == "action"
    assert annotation.status_code == 200
    assert annotation.json()["annotation"]["body"] == "Reference this link"
    stored = repo.conversations[conversation.id].metadata["browser_workspace"]
    assert stored["annotations"][0]["node_id"] == "pa_link"
    assert stored["timeline_events"]
    assert "html" not in stored
    assert "document_html" not in stored
    assert "browser_snapshot" not in stored


@pytest.mark.asyncio
async def test_browser_tab_mentions_return_active_shared_tab(monkeypatch):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="Browser mention")
    conversation.metadata["browser_workspace"] = {
        "active_browser_id": str(conversation.id),
        "active_tab_id": "page_github",
        "current_url": "https://github.com/personagent/personagent",
        "current_title": "GitHub - PersonAgent",
        "tabs": [
            {
                "tab_id": "page_github",
                "url": "https://github.com/personagent/personagent",
                "title": "GitHub - PersonAgent",
                "active": True,
                "runtime": "lightpanda",
                "state": {"scroll": {"y": 120}},
            }
        ],
    }
    await repo.create(conversation)
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))

    async def fake_get_db():
        yield object()

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[sessions.get_db] = fake_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/sessions/{conversation.id}/browser/mentions?q=github")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["type"] == "browser_tab"
    assert payload[0]["browser_id"] == str(conversation.id)
    assert payload[0]["page_id"] == "page_github"
    assert payload[0]["url"] == "https://github.com/personagent/personagent"
    assert payload[0]["active"] is True


@pytest.mark.asyncio
async def test_session_project_detail_api_returns_detail(monkeypatch, tmp_path):
    repo = MemoryConversationRepository()
    conversation = Conversation(title="API detail")
    await repo.create(conversation)
    monkeypatch.setattr(sessions, "get_container", lambda: FakeContainer(repo))
    grant_test_workspace(monkeypatch, tmp_path)

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


@pytest.mark.asyncio
async def test_project_snapshot_uses_git_repo_fallback_when_gh_fails(monkeypatch, tmp_path):
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

    async def fake_run_async(command, cwd, timeout=5):
        return fake_run(command, cwd, timeout)

    monkeypatch.setattr(session_panel, "_run", fake_run)
    monkeypatch.setattr(session_panel, "_run_async", fake_run_async)

    snapshot = await SessionPanelService(tmp_path).panel_snapshot(conversation)

    assert snapshot["project"]["repo"]["source"] == "git"
    assert snapshot["project"]["repo"]["name_with_owner"] == "acme/repo"
    assert any("gh repo view" in error for error in snapshot["project"]["errors"])


@pytest.mark.asyncio
async def test_project_snapshot_uses_clean_branch_ids(monkeypatch, tmp_path):
    conversation = Conversation(title="Branch IDs")

    def fake_run(command, cwd, timeout=5):
        if command == ["git", "rev-parse", "--git-dir"]:
            return session_panel._RunResult(0, ".git\n", "")
        return session_panel._RunResult(1, "", f"unexpected command: {command}")

    async def fake_run_async(command, cwd, timeout=5):
        if command == ["gh", "repo", "view", "--json", "nameWithOwner,url,defaultBranchRef,pushedAt"]:
            return session_panel._RunResult(
                0,
                json.dumps(
                    {
                        "nameWithOwner": "acme/repo",
                        "url": "https://github.com/acme/repo",
                        "defaultBranchRef": {"name": "main"},
                        "pushedAt": "2026-04-27T22:12:44Z",
                    }
                ),
                "",
            )
        if command == [
            "gh",
            "pr",
            "list",
            "--limit",
            "5",
            "--state",
            "all",
            "--json",
            "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName",
        ]:
            return session_panel._RunResult(0, "[]", "")
        if command == [
            "git",
            "branch",
            "--format=%(refname:short)%1f%(objectname:short)%1f%(committerdate:iso8601)%1f%(subject)",
        ]:
            return session_panel._RunResult(
                0,
                "main\x1f6c26f40\x1f2026-04-27 22:12:44 -0300\x1fRefine chat UI and backend streaming behavior\n",
                "",
            )
        if command == ["git", "log", "-10", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%s"]:
            return session_panel._RunResult(
                0,
                "abc123\x1fabc1234\x1fDev\x1f2026-04-27T22:12:44-03:00\x1fFix bug\n",
                "",
            )
        if command == ["git", "remote", "get-url", "origin"]:
            return session_panel._RunResult(0, "https://github.com/acme/repo.git\n", "")
        if command == ["git", "branch", "--show-current"]:
            return session_panel._RunResult(0, "main\n", "")
        if command == ["gh", "api", "repos/acme/repo/events"]:
            return session_panel._RunResult(0, "[]", "")
        return session_panel._RunResult(1, "", f"unexpected command: {command}")

    monkeypatch.setattr(session_panel, "_run", fake_run)
    monkeypatch.setattr(session_panel, "_run_async", fake_run_async)

    snapshot = await SessionPanelService(tmp_path).panel_snapshot(conversation)

    assert [branch["id"] for branch in snapshot["project"]["branches"]] == ["main"]
    assert snapshot["project"]["branches"][0]["title"] == "main"
    assert snapshot["project"]["branches"][0]["active"] is True


@pytest.mark.asyncio
async def test_artifact_route_serves_whitelisted_payloads_and_blocks_invalid_ids(monkeypatch, tmp_path):
    monkeypatch.setenv("PERSONAGENT_ARTIFACT_ROOT", str(tmp_path))
    reset_settings()
    image = store_bytes_artifact(
        category="generated-images",
        conversation_id="conversation-1",
        content=b"image-bytes",
        suffix=".png",
        mime_type="image/png",
        root=tmp_path,
    )
    blocked = store_text_artifact(
        category="generated-images",
        conversation_id="conversation-1",
        content="<svg></svg>",
        suffix=".svg",
        mime_type="image/svg+xml",
        root=tmp_path,
    )
    app = FastAPI()
    app.include_router(artifacts.router)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            served = await client.get(image.url)
            assert served.status_code == 200
            assert served.content == b"image-bytes"
            assert served.headers["content-type"].startswith("image/png")
            assert served.headers["content-disposition"].startswith("inline;")

            missing = await client.get("/artifacts/conversation-1/generated-images/missing.png")
            assert missing.status_code == 404

            rejected = await client.get(blocked.url)
            assert rejected.status_code == 403
    finally:
        reset_settings()
