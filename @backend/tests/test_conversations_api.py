from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.adapters.api.routes import conversations
from personagent.domain.conversation.models import Conversation, Message, Role


class FakeConversationRepo:
    def __init__(self, source: Conversation) -> None:
        self.conversations: dict[UUID, Conversation] = {source.id: source}
        self.created: Conversation | None = None

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        self.created = conversation
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


class FakeContainer:
    def __init__(self, repo: FakeConversationRepo) -> None:
        self.repo = repo

    async def get_conversation_repo(self, _session):
        return self.repo


@pytest.mark.asyncio
async def test_conversation_fork_preserves_prefix_messages(monkeypatch):
    source = Conversation(title="Original Session", metadata={"workspace_root": "/old"})
    source.add_message(Message(role=Role.USER, content="Original prompt"))
    repo = FakeConversationRepo(source)
    monkeypatch.setattr(conversations, "get_container", lambda: FakeContainer(repo))

    app = FastAPI()
    app.dependency_overrides[conversations.get_db] = lambda: None
    app.include_router(conversations.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/conversations/{source.id}/fork",
            json={
                "title": "Original Session",
                "workspace_root": "/workspace",
                "messages": [
                    {"role": "user", "content": "First prompt"},
                    {
                        "role": "assistant",
                        "content": "First answer",
                        "metadata": {"reasoning_content": "Hidden thought"},
                    },
                ],
            },
        )

    assert response.status_code == 200
    assert repo.created is not None
    assert repo.created.id != source.id
    assert repo.created.metadata["workspace_root"] == "/workspace"
    assert [message.role for message in repo.created.messages] == [Role.USER, Role.ASSISTANT]
    assert [message.content for message in repo.created.messages] == ["First prompt", "First answer"]
    assert repo.created.messages[1].metadata["reasoning_content"] == "Hidden thought"
