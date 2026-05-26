"""Conversation lifecycle helpers extracted from ``chat_completion.py``.

Two tiny, orthogonal responsibilities that historically lived as
private methods on :class:`ChatCompletionUseCase`:

* ``_get_or_create_conversation`` -- resolve the
  :class:`Conversation` for one chat turn. Either load it from the
  :class:`ConversationRepository` (when the request carries a
  ``conversation_id``) or create a fresh one and persist it. Either
  way, propagate the workspace metadata from
  ``request.tool_context``.
* ``_assistant_message_from_result`` -- pure transformation that
  converts an :class:`InferenceResult` plus the optional
  context-build metadata into the persistable assistant
  :class:`Message`, attaching the canonical metadata payload
  (``usage``, ``model``, ``reasoning_content``, ``finish_reason``,
  images, context usage, plus any extra result metadata).

Both helpers are called from the non-streaming ``execute`` and the
streaming entry points. Bundling them under
:class:`ConversationLifecycleHandler` removes them from the god file
without changing any side effect or output shape.

Backward compatibility: same load-vs-create semantics, same
:class:`ConversationNotFoundError` message, same workspace-metadata
propagation, same assistant message metadata keys (in the same
order, with the same default values).
"""

from __future__ import annotations

from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.helpers import (
    apply_workspace_metadata,
    context_usage_metadata,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.conversation.repositories import (
    ConversationRepository,
)
from personagent.domain.exceptions import ConversationNotFoundError
from personagent.domain.llm_backend.models import InferenceResult


class ConversationLifecycleHandler:
    """Encapsulate per-turn conversation load/create + assistant-message assembly."""

    def __init__(self, *, conversation_repo: ConversationRepository) -> None:
        self._conversation_repo = conversation_repo

    async def get_or_create_conversation(
        self,
        request: ChatRequestDTO,
    ) -> Conversation:
        """Load a conversation by id or create a fresh one and persist it."""

        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(
                request.conversation_id
            )
            if not conversation:
                raise ConversationNotFoundError(
                    f"Conversation {request.conversation_id} not found"
                )
            apply_workspace_metadata(conversation, request.tool_context)
            return conversation

        conversation = Conversation()
        apply_workspace_metadata(conversation, request.tool_context)
        await self._conversation_repo.create(conversation)
        return conversation

    def assistant_message_from_result(
        self,
        result: InferenceResult,
        context_metadata: dict[str, Any] | None = None,
    ) -> Message:
        """Convert an :class:`InferenceResult` into the persistable assistant message."""

        return Message(
            role=Role.ASSISTANT,
            content=result.content,
            tool_calls=result.tool_calls,
            metadata={
                "usage": result.usage,
                "model": result.model,
                "reasoning_content": result.reasoning_content or None,
                "finish_reason": result.finish_reason,
                "images": [image.to_dict() for image in result.images],
                **context_usage_metadata(context_metadata or {}),
                **result.metadata,
            },
        )


__all__ = ["ConversationLifecycleHandler"]
