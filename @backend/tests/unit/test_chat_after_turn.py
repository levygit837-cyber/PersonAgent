"""Tests for :class:`AfterTurnCoordinator`.

The coordinator runs three independent post-turn side effects:

* next-step suggestion (suppressed in plan mode),
* session-memory file refresh (timestamps metadata on update),
* session title refresh (LLM-backed when wired, fallback otherwise).

Each step tolerates a missing collaborator (``None`` => no-op). The
tests pin every branch by injecting stub doubles for each service.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.after_turn import AfterTurnCoordinator
from personagent.domain.models.conversation import Conversation, Message, Role


class _RepoStub:
    """Minimal :class:`ConversationRepository` double recording ``update`` calls."""

    def __init__(self) -> None:
        self.updated: list[Conversation] = []

    async def update(self, conversation: Conversation) -> Conversation:
        self.updated.append(conversation)
        return conversation


class _NextStepStub:
    """Stub :class:`NextStepSuggestionService` with configurable return."""

    def __init__(self, suggestion: str | None = "next") -> None:
        self._suggestion = suggestion
        self.calls: list[dict[str, Any]] = []

    async def suggest(
        self,
        conversation: Conversation,
        *,
        model: str | None,
        provider: str | None,
        finish_reason: str | None,
        suppressed: bool,
    ) -> str | None:
        self.calls.append(
            {
                "conversation_id": conversation.id,
                "model": model,
                "provider": provider,
                "finish_reason": finish_reason,
                "suppressed": suppressed,
            }
        )
        if suppressed:
            return None
        return self._suggestion


class _MemoryStub:
    """Stub :class:`SessionMemoryService` recording ``update`` calls."""

    def __init__(self, *, returns_true: bool = True) -> None:
        self._returns_true = returns_true
        self.calls: list[dict[str, Any]] = []

    async def update(
        self,
        conversation: Conversation,
        *,
        model: str | None,
        provider: str | None,
    ) -> bool:
        self.calls.append(
            {
                "conversation_id": conversation.id,
                "model": model,
                "provider": provider,
            }
        )
        return self._returns_true


def _conversation(metadata: dict[str, Any] | None = None, *, title: str = "") -> Conversation:
    return Conversation(
        id=uuid4(),
        title=title,
        messages=[
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="hello"),
        ],
        metadata=dict(metadata or {}),
    )


def _request() -> ChatRequestDTO:
    return ChatRequestDTO(message="hi", model="m", provider="p")


@pytest.fixture()
def repo() -> _RepoStub:
    return _RepoStub()


# -- run_services -----------------------------------------------------------


async def test_run_services_returns_none_when_all_collaborators_missing(repo: _RepoStub) -> None:
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=None,
    )

    result = await coordinator.run_services(_conversation(), _request(), finish_reason="stop")

    assert result is None


async def test_run_services_writes_suggestion_to_metadata(repo: _RepoStub) -> None:
    next_step = _NextStepStub(suggestion="try /help")
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation()

    result = await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert result == "try /help"
    assert conv.metadata["next_step_suggestion"] == "try /help"


async def test_run_services_skips_metadata_when_suggestion_empty(repo: _RepoStub) -> None:
    next_step = _NextStepStub(suggestion=None)
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation()

    result = await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert result is None
    assert "next_step_suggestion" not in conv.metadata


async def test_run_services_skips_metadata_when_suggestion_empty_string(repo: _RepoStub) -> None:
    next_step = _NextStepStub(suggestion="")
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation()

    result = await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert result == ""
    assert "next_step_suggestion" not in conv.metadata


async def test_run_services_passes_plan_active_as_suppressed(repo: _RepoStub) -> None:
    next_step = _NextStepStub(suggestion="never returned")
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation(metadata={"plan_mode": {"active": True, "status": "draft"}})

    result = await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert result is None
    assert next_step.calls[0]["suppressed"] is True


async def test_run_services_forwards_request_and_finish_reason(repo: _RepoStub) -> None:
    next_step = _NextStepStub()
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=None,
        session_title_service=None,
    )
    req = ChatRequestDTO(message="hi", model="gpt", provider="openai")

    await coordinator.run_services(_conversation(), req, finish_reason="length")

    call = next_step.calls[0]
    assert call["model"] == "gpt"
    assert call["provider"] == "openai"
    assert call["finish_reason"] == "length"


async def test_run_services_updates_memory_timestamp_when_changed(repo: _RepoStub) -> None:
    memory = _MemoryStub(returns_true=True)
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=memory,
        session_title_service=None,
    )
    conv = _conversation()

    await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert "session_memory_updated_at" in conv.metadata
    timestamp = conv.metadata["session_memory_updated_at"]
    assert isinstance(timestamp, str)
    assert timestamp.endswith("+00:00")


async def test_run_services_omits_timestamp_when_memory_unchanged(repo: _RepoStub) -> None:
    memory = _MemoryStub(returns_true=False)
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=memory,
        session_title_service=None,
    )
    conv = _conversation()

    await coordinator.run_services(conv, _request(), finish_reason="stop")

    assert "session_memory_updated_at" not in conv.metadata


async def test_run_services_runs_both_steps_in_order(repo: _RepoStub) -> None:
    order: list[str] = []
    next_step = _NextStepStub(suggestion="x")

    async def _suggest(*a: Any, **kw: Any) -> str:
        order.append("suggest")
        return await _NextStepStub.suggest(next_step, *a, **kw)

    memory = _MemoryStub(returns_true=True)

    async def _update(*a: Any, **kw: Any) -> bool:
        order.append("memory")
        return await _MemoryStub.update(memory, *a, **kw)

    next_step.suggest = _suggest  # type: ignore[method-assign]
    memory.update = _update  # type: ignore[method-assign]

    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=next_step,
        session_memory_service=memory,
        session_title_service=None,
    )

    await coordinator.run_services(_conversation(), _request(), finish_reason="stop")

    assert order == ["suggest", "memory"]


# -- refresh_session_title --------------------------------------------------


async def test_refresh_session_title_delegates_to_service_when_present(repo: _RepoStub) -> None:
    service = AsyncMock()
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=service,
    )
    conv = _conversation()

    await coordinator.refresh_session_title(conv, was_empty=True)

    service.refresh_title.assert_awaited_once_with(repo, conv)
    assert repo.updated == []


async def test_refresh_session_title_delegates_even_when_not_empty(repo: _RepoStub) -> None:
    service = AsyncMock()
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=service,
    )

    await coordinator.refresh_session_title(_conversation(title="kept"), was_empty=False)

    service.refresh_title.assert_awaited_once()


async def test_refresh_session_title_fallback_when_empty_and_no_service(repo: _RepoStub) -> None:
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation(title="")

    await coordinator.refresh_session_title(conv, was_empty=True)

    assert conv.title == conv.generate_title()
    assert repo.updated == [conv]


async def test_refresh_session_title_noop_when_not_empty_and_no_service(repo: _RepoStub) -> None:
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = _conversation(title="existing-title")
    original_title = conv.title

    await coordinator.refresh_session_title(conv, was_empty=False)

    assert conv.title == original_title
    assert repo.updated == []


async def test_refresh_session_title_fallback_uses_generate_title_helper(repo: _RepoStub) -> None:
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=None,
    )
    conv = Conversation(
        id=uuid4(),
        title="",
        messages=[Message(role=Role.USER, content="Pergunta sobre Python")],
        metadata={},
    )

    await coordinator.refresh_session_title(conv, was_empty=True)

    assert conv.title  # generate_title produces a non-empty string
    assert conv.title == conv.generate_title()


async def test_refresh_session_title_service_takes_priority_over_fallback(repo: _RepoStub) -> None:
    service = AsyncMock()
    coordinator = AfterTurnCoordinator(
        conversation_repo=repo,
        next_step_suggestion_service=None,
        session_memory_service=None,
        session_title_service=service,
    )
    conv = _conversation(title="keep-me")
    original_title = conv.title

    await coordinator.refresh_session_title(conv, was_empty=True)

    service.refresh_title.assert_awaited_once_with(repo, conv)
    assert conv.title == original_title
    assert repo.updated == []
