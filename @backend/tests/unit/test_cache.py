from __future__ import annotations

import pytest

from personagent.application.services.session_titles.cache import (
    SESSION_TITLE_CACHE_KEY,
    SESSION_TITLE_CACHE_VERSION,
    TitleCache,
)
from personagent.domain.models.conversation import Conversation, Message, Role


class StubConversationRepository:
    def __init__(self) -> None:
        self.updates: list[Conversation] = []

    async def update(self, conversation: Conversation) -> Conversation:
        self.updates.append(conversation)
        return conversation


def _conversation_with_messages(*contents: str) -> Conversation:
    conversation = Conversation(title="Test")
    for content in contents:
        conversation.add_message(Message(role=Role.USER, content=content))
    return conversation


@pytest.fixture
def cache() -> TitleCache:
    return TitleCache(
        primary_provider="nvidia",
        primary_model="moonshotai/kimi-k2.6",
        fallback_provider="llama",
        fallback_model="local-model",
    )


def test_history_hash_is_consistent(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    h1 = cache.history_hash(conversation)
    h2 = cache.history_hash(conversation)
    assert h1 == h2
    assert len(h1) == 64


def test_history_hash_changes_when_messages_change(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    h1 = cache.history_hash(conversation)
    conversation.add_message(Message(role=Role.ASSISTANT, content="hi"))
    h2 = cache.history_hash(conversation)
    assert h1 != h2


def test_history_hash_includes_tool_calls_and_tool_call_id(cache: TitleCache):
    c1 = Conversation(title="Test")
    c1.add_message(
        Message(role=Role.ASSISTANT, content="ok", tool_calls=[{"name": "x"}], tool_call_id="abc")
    )
    c2 = Conversation(title="Test")
    c2.add_message(
        Message(role=Role.ASSISTANT, content="ok", tool_calls=[{"name": "y"}], tool_call_id="abc")
    )
    h1 = cache.history_hash(c1)
    h2 = cache.history_hash(c2)
    assert h1 != h2


def test_cached_title_returns_none_when_no_metadata(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    assert cache.cached_title(conversation, "any_hash") is None


def test_cached_title_returns_none_when_cache_not_dict(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    conversation.metadata[SESSION_TITLE_CACHE_KEY] = "not_a_dict"
    assert cache.cached_title(conversation, "any_hash") is None


def test_cached_title_returns_none_when_version_mismatch(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
        "version": 999,
        "history_hash": "matching_hash",
        "title": "Valid Title",
    }
    assert cache.cached_title(conversation, "matching_hash") is None


def test_cached_title_returns_none_when_history_hash_mismatch(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
        "version": SESSION_TITLE_CACHE_VERSION,
        "history_hash": "old_hash",
        "title": "Valid Title",
    }
    assert cache.cached_title(conversation, "new_hash") is None


def test_cached_title_returns_none_when_title_is_generic(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
        "version": SESSION_TITLE_CACHE_VERSION,
        "history_hash": "matching_hash",
        "title": "New Chat",
    }
    assert cache.cached_title(conversation, "matching_hash") is None


def test_cached_title_returns_sanitized_title_when_valid(cache: TitleCache):
    conversation = _conversation_with_messages("hello")
    conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
        "version": SESSION_TITLE_CACHE_VERSION,
        "history_hash": "matching_hash",
        "title": "  My Title  ",
    }
    result = cache.cached_title(conversation, "matching_hash")
    assert result == "My Title"


@pytest.mark.asyncio
async def test_apply_title_returns_cached_status_for_cache_source(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    result = await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="cache",
        dry_run=True,
    )
    assert result.status == "cached"


@pytest.mark.asyncio
async def test_apply_title_returns_skipped_when_title_unchanged(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    conversation.title = "Same Title"
    result = await cache.apply_title(
        repo,
        conversation,
        "Same Title",
        history_hash="hash1",
        source="llm",
        dry_run=True,
    )
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_apply_title_returns_updated_when_title_changed(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    conversation.title = "Old Title"
    result = await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=True,
    )
    assert result.status == "updated"


@pytest.mark.asyncio
async def test_apply_title_updates_conversation_title(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    conversation.title = "Old"
    await cache.apply_title(
        repo,
        conversation,
        "New",
        history_hash="hash1",
        source="llm",
        dry_run=False,
    )
    assert conversation.title == "New"


@pytest.mark.asyncio
async def test_apply_title_writes_cache_metadata(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=False,
    )
    meta = conversation.metadata[SESSION_TITLE_CACHE_KEY]
    assert meta["version"] == SESSION_TITLE_CACHE_VERSION
    assert meta["history_hash"] == "hash1"
    assert meta["title"] == "New Title"
    assert meta["source"] == "llm"
    assert meta["provider"] == "nvidia"
    assert meta["model"] == "moonshotai/kimi-k2.6"
    assert meta["message_count"] == 1
    assert "updated_at" in meta


@pytest.mark.asyncio
async def test_apply_title_writes_fallback_provider_and_model(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm_fallback",
        dry_run=False,
    )
    meta = conversation.metadata[SESSION_TITLE_CACHE_KEY]
    assert meta["provider"] == "llama"
    assert meta["model"] == "local-model"


@pytest.mark.asyncio
async def test_apply_title_writes_none_provider_for_deterministic(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="deterministic",
        dry_run=False,
    )
    meta = conversation.metadata[SESSION_TITLE_CACHE_KEY]
    assert meta["provider"] is None
    assert meta["model"] is None


@pytest.mark.asyncio
async def test_apply_title_does_not_mutate_when_dry_run(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    conversation.title = "Original"
    old_metadata = dict(conversation.metadata)
    await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=True,
    )
    assert conversation.title == "Original"
    assert conversation.metadata == old_metadata
    assert len(repo.updates) == 0


@pytest.mark.asyncio
async def test_apply_title_calls_repo_update(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=False,
    )
    assert len(repo.updates) == 1
    assert repo.updates[0] is conversation


@pytest.mark.asyncio
async def test_apply_title_preserves_reason_in_result(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    result = await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=True,
        reason="my_reason",
    )
    assert result.reason == "my_reason"


@pytest.mark.asyncio
async def test_apply_title_result_fields(cache: TitleCache):
    repo = StubConversationRepository()
    conversation = _conversation_with_messages("hello")
    conversation.title = "Old Title"
    result = await cache.apply_title(
        repo,
        conversation,
        "New Title",
        history_hash="hash1",
        source="llm",
        dry_run=True,
    )
    assert result.conversation_id == str(conversation.id)
    assert result.old_title == "Old Title"
    assert result.new_title == "New Title"
    assert result.history_hash == "hash1"
    assert result.source == "llm"
