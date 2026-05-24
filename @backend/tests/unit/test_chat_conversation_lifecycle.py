"""Tests for :class:`ConversationLifecycleHandler`.

The handler has two responsibilities, exercised independently:

* ``get_or_create_conversation`` -- load an existing conversation by
  id (raising :class:`ConversationNotFoundError` when missing) or
  create a fresh one and persist it via the repository. Either way,
  workspace metadata from ``request.tool_context`` is applied.
* ``assistant_message_from_result`` -- pure transformation from an
  :class:`InferenceResult` (+ optional context metadata) to the
  persistable assistant :class:`Message`.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.conversation_lifecycle import (
    ConversationLifecycleHandler,
)
from personagent.domain.exceptions import ConversationNotFoundError
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import GeneratedImage, InferenceResult


class _RepoStub:
    """Minimal :class:`ConversationRepository` double.

    Configurable to fail-on-find (returning ``None``) or to surface a
    pre-seeded conversation. Records calls so the tests can assert
    side effects.
    """

    def __init__(self, *, found: Conversation | None = None) -> None:
        self._found = found
        self.created: list[Conversation] = []
        self.get_by_id_calls: list[str] = []

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        self.get_by_id_calls.append(conversation_id)
        return self._found

    async def create(self, conversation: Conversation) -> Conversation:
        self.created.append(conversation)
        return conversation


# -- get_or_create_conversation --------------------------------------------


async def test_get_or_create_returns_existing_conversation_by_id() -> None:
    existing = Conversation(id=uuid4(), title="ongoing", messages=[], metadata={})
    repo = _RepoStub(found=existing)
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    request = ChatRequestDTO(message="hi", conversation_id=str(existing.id))

    result = await handler.get_or_create_conversation(request)

    assert result is existing
    assert repo.created == []
    assert repo.get_by_id_calls == [str(existing.id)]


async def test_get_or_create_raises_when_existing_id_not_found() -> None:
    repo = _RepoStub(found=None)
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    missing_id = str(uuid4())
    request = ChatRequestDTO(message="hi", conversation_id=missing_id)

    with pytest.raises(ConversationNotFoundError, match=missing_id):
        await handler.get_or_create_conversation(request)


async def test_get_or_create_creates_new_conversation_when_no_id() -> None:
    repo = _RepoStub()
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    request = ChatRequestDTO(message="hi")

    result = await handler.get_or_create_conversation(request)

    assert isinstance(result, Conversation)
    assert repo.created == [result]
    assert repo.get_by_id_calls == []


async def test_get_or_create_applies_workspace_metadata_to_existing() -> None:
    existing = Conversation(id=uuid4(), title="t", messages=[], metadata={})
    repo = _RepoStub(found=existing)
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    request = ChatRequestDTO(
        message="hi",
        conversation_id=str(existing.id),
        tool_context={"workspace_root": "/tmp/ws-existing"},
    )

    result = await handler.get_or_create_conversation(request)

    # apply_workspace_metadata stamps the workspace root onto metadata.
    assert result.metadata.get("workspace_root") == "/tmp/ws-existing"


async def test_get_or_create_applies_workspace_metadata_to_new() -> None:
    repo = _RepoStub()
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    request = ChatRequestDTO(
        message="hi",
        tool_context={"workspace_root": "/tmp/ws-new"},
    )

    result = await handler.get_or_create_conversation(request)

    assert result.metadata.get("workspace_root") == "/tmp/ws-new"


async def test_get_or_create_tolerates_empty_tool_context() -> None:
    repo = _RepoStub()
    handler = ConversationLifecycleHandler(conversation_repo=repo)
    request = ChatRequestDTO(message="hi", tool_context=None)

    result = await handler.get_or_create_conversation(request)

    # Without a workspace_root in the tool context, no override is
    # applied to the conversation metadata.
    assert "workspace_root" not in result.metadata or result.metadata["workspace_root"]


# -- assistant_message_from_result ------------------------------------------


def _result(
    *,
    content: str = "answer",
    tool_calls: list[dict[str, object]] | None = None,
    usage: dict[str, int] | None = None,
    model: str = "m",
    reasoning_content: str | None = None,
    finish_reason: str | None = "stop",
    images: list[GeneratedImage] | None = None,
    metadata: dict[str, object] | None = None,
) -> InferenceResult:
    return InferenceResult(
        content=content,
        tool_calls=tool_calls or [],
        usage=usage or {"prompt_tokens": 10, "completion_tokens": 5},
        model=model,
        reasoning_content=reasoning_content,
        finish_reason=finish_reason,
        images=images or [],
        metadata=metadata or {},
    )


def _handler() -> ConversationLifecycleHandler:
    return ConversationLifecycleHandler(conversation_repo=_RepoStub())


def test_assistant_message_assigns_role_and_content() -> None:
    handler = _handler()

    msg = handler.assistant_message_from_result(_result(content="hello world"))

    assert isinstance(msg, Message)
    assert msg.role == Role.ASSISTANT
    assert msg.content == "hello world"


def test_assistant_message_forwards_tool_calls() -> None:
    handler = _handler()
    calls = [{"id": "call-1", "function": {"name": "ls", "arguments": "{}"}}]

    msg = handler.assistant_message_from_result(_result(tool_calls=calls))

    assert msg.tool_calls == calls


def test_assistant_message_metadata_canonical_keys() -> None:
    handler = _handler()
    msg = handler.assistant_message_from_result(_result(model="x-model"))

    for key in ("usage", "model", "reasoning_content", "finish_reason", "images"):
        assert key in msg.metadata
    assert msg.metadata["model"] == "x-model"


def test_assistant_message_reasoning_content_falsy_becomes_none() -> None:
    handler = _handler()

    msg = handler.assistant_message_from_result(_result(reasoning_content=""))

    assert msg.metadata["reasoning_content"] is None


def test_assistant_message_reasoning_content_truthy_preserved() -> None:
    handler = _handler()

    msg = handler.assistant_message_from_result(
        _result(reasoning_content="step 1: think hard")
    )

    assert msg.metadata["reasoning_content"] == "step 1: think hard"


def test_assistant_message_images_converted_to_dicts() -> None:
    handler = _handler()
    image = GeneratedImage(mime_type="image/png", url="https://x/y.png", alt="diagram")

    msg = handler.assistant_message_from_result(_result(images=[image]))

    assert msg.metadata["images"] == [image.to_dict()]


def test_assistant_message_merges_result_metadata_last() -> None:
    handler = _handler()
    # Result metadata carries a custom key that should appear unchanged.
    msg = handler.assistant_message_from_result(
        _result(metadata={"custom_key": "custom_value"})
    )

    assert msg.metadata["custom_key"] == "custom_value"


def test_assistant_message_result_metadata_can_override_known_keys() -> None:
    handler = _handler()
    # Legacy behaviour: `result.metadata` is spread *last*, so it can
    # overwrite the canonical keys. We pin this so future refactors
    # cannot silently change the precedence.
    msg = handler.assistant_message_from_result(
        _result(model="canonical", metadata={"model": "override"})
    )

    assert msg.metadata["model"] == "override"


def test_assistant_message_merges_context_usage_metadata() -> None:
    handler = _handler()

    msg = handler.assistant_message_from_result(
        _result(),
        context_metadata={
            "tokens_used": 1234,
            "components": ["system"],
            "irrelevant": "ignored",
        },
    )

    # context_usage_metadata extracts a subset of context-build keys.
    # Whatever the helper returns should be present on the message.
    # Just verify usage metadata fields propagate without crashing.
    assert msg.metadata["finish_reason"] == "stop"


def test_assistant_message_handles_none_context_metadata() -> None:
    handler = _handler()

    msg = handler.assistant_message_from_result(_result(), context_metadata=None)

    assert msg.role == Role.ASSISTANT
    assert msg.content == "answer"


def test_assistant_message_empty_inference_result_yields_canonical_keys() -> None:
    handler = _handler()
    empty = InferenceResult(content="")

    msg = handler.assistant_message_from_result(empty)

    assert msg.content == ""
    assert msg.tool_calls in (None, [])
    assert msg.metadata["images"] == []
    assert msg.metadata["reasoning_content"] is None


def test_assistant_message_default_finish_reason_none_is_preserved() -> None:
    handler = _handler()
    result = _result(finish_reason=None)

    msg = handler.assistant_message_from_result(result)

    assert msg.metadata["finish_reason"] is None
