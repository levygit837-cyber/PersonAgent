from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import pytest

from personagent.application.services.session_titles import (
    SESSION_TITLE_CACHE_KEY,
    SessionTitleService,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.conversation.repositories import ConversationRepository
from personagent.domain.llm_backend.models import InferenceResult, StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository


@pytest.mark.asyncio
async def test_session_title_service_batches_llm_titles_and_reuses_cache():
    repo = MemoryConversationRepository()
    first = Conversation(title="Test")
    first.add_message(Message(role=Role.USER, content="hi"))
    first.add_message(
        Message(
            role=Role.ASSISTANT,
            content="I mapped the session panel and the related endpoints.",
        )
    )
    first.add_message(
        Message(role=Role.USER, content="Now adjust the session panel in Electron.")
    )
    second = Conversation(title="Test")
    second.add_message(Message(role=Role.USER, content="hi"))
    second.add_message(
        Message(
            role=Role.ASSISTANT,
            content="The failure is in the LightPanda flow over CDP.",
        )
    )
    await repo.create(first)
    await repo.create(second)
    llm = MappingTitleLLM(
        {
            str(first.id): "Electron Session Panel",
            str(second.id): "Stable LightPanda CDP",
        }
    )
    service = SessionTitleService(primary_llm_backend=llm, fallback_llm_backend=None)

    result = await service.verify_all(repo, batch_size=10)

    assert result.checked == 2
    assert result.analyzed == 2
    assert result.updated == 2
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "openai/gpt-oss-120b"
    assert first.title == "Electron Session Panel"
    assert second.title == "Stable LightPanda CDP"
    assert first.metadata[SESSION_TITLE_CACHE_KEY]["history_hash"]

    rerun = await service.verify_all(repo, batch_size=10)

    assert rerun.checked == 2
    assert rerun.cached == 2
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_session_title_service_uses_local_fallback_when_gpt_oss_fails():
    repo = MemoryConversationRepository()
    conversation = Conversation(title="New Chat")
    conversation.add_message(
        Message(role=Role.USER, content="Investigate the NVIDIA model benchmarks.")
    )
    await repo.create(conversation)
    primary = FailingTitleLLM()
    fallback = MappingTitleLLM({str(conversation.id): "Long NVIDIA Benchmarks"})
    service = SessionTitleService(
        primary_llm_backend=primary,
        fallback_llm_backend=fallback,
    )

    result = await service.verify_all(repo)

    assert result.checked == 1
    assert result.analyzed == 1
    assert result.results[0].source == "llm_fallback"
    assert fallback.calls[0]["provider"] == "llama"
    assert fallback.calls[0]["model"] == "local-model"
    assert conversation.title == "Long NVIDIA Benchmarks"


@pytest.mark.asyncio
async def test_session_title_service_repairs_duplicate_cached_titles_without_llm():
    repo = MemoryConversationRepository()
    first = Conversation(title="Debug Browser Tools")
    first.add_message(Message(role=Role.USER, content="Debug BrowserSearch in the backend."))
    second = Conversation(title="Debug Browser Tools")
    second.add_message(Message(role=Role.USER, content="Debug BrowserOpen in the backend."))
    llm = MappingTitleLLM({})
    service = SessionTitleService(primary_llm_backend=llm, fallback_llm_backend=None)
    for conversation in (first, second):
        conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
            "version": 1,
            "history_hash": service._history_hash(conversation),
            "title": "Debug Browser Tools",
        }
        await repo.create(conversation)

    result = await service.maybe_repair_duplicate_titles(repo, force=False)

    assert result.checked == 1
    assert result.cached == 1
    assert len(llm.calls) == 0
    titles = {conversation.title for conversation in repo.conversations.values()}
    assert len(titles) == 2


class MappingTitleLLM(LLMBackendRepository):
    def __init__(self, titles: dict[str, str]) -> None:
        self.titles = titles
        self.calls: list[dict] = []

    async def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> InferenceResult:
        payload = json.loads(messages[-1]["content"])
        self.calls.append({**kwargs, "session_count": len(payload["sessions"])})
        return InferenceResult(
            content=json.dumps(
                {
                    "titles": [
                        {"id": session["id"], "title": self.titles[session["id"]]}
                        for session in payload["sessions"]
                    ]
                }
            )
        )

    async def chat_completion_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {"data": []}


class FailingTitleLLM(MappingTitleLLM):
    def __init__(self) -> None:
        super().__init__({})

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        self.calls.append(kwargs)
        raise RuntimeError("primary unavailable")


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        conversations = sorted(
            self.conversations.values(),
            key=lambda conversation: conversation.updated_at,
            reverse=True,
        )
        return conversations[offset : offset + limit]

    async def list_summaries(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return [
            {
                "id": str(conversation.id),
                "title": conversation.title,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "message_count": len(conversation.messages),
            }
            for conversation in await self.list_all(limit=limit, offset=offset)
        ]

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
