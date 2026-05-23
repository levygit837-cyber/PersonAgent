"""In-flight state carriers for the chat completion pipeline.

These dataclasses are private to the chat completion use case in the
sense that no external caller should construct them, but they are
exposed publicly (no leading underscore) so that:

* Unit tests can assemble fixtures without going through the full
  ``ChatCompletionUseCase`` boot path.
* Future extraction of helper services (prompt-package assembly,
  context-after-turn metadata, etc.) can take a typed argument instead
  of a raw ``dict[str, Any]``.

Each type is :func:`dataclass(slots=True)` so that constructing one is
cheap and stray attribute writes raise loudly -- the original god-file
relied on dicts and we want to avoid silently growing keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.domain.models.inference_result import GeneratedImage


@dataclass(slots=True)
class PromptPackage:
    """Materialized system+user prompt pair ready to hand to the LLM.

    ``user_context_message`` is optional because some turns inject
    context only into the system prompt; ``metadata`` carries the
    bookkeeping (token estimates, memory trace, etc.) that the use case
    later forwards to the assistant message.
    """

    system_prompt: str | None
    user_context_message: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class MemoryRecallResult:
    """Output of the memory-recall step.

    Empty by default so callers that disable RAG don't need to think
    about the trace dict at all.
    """

    prompt_memories: list[str] = field(default_factory=list)
    trace: dict[str, Any] | None = None


@dataclass(slots=True)
class PromptPreparation:
    """Resolved prompt-surface state for a single user turn.

    Captures everything that varies between turns *before* the LLM call:
    the original :class:`ChatRequestDTO`, any reminders injected by
    slash commands or context attachments, the cooperation-shared
    Browser target, etc.
    """

    request: ChatRequestDTO
    slash_reminder: str | None = None
    slash_metadata: dict[str, Any] | None = None
    context_reminders: list[str] = field(default_factory=list)
    context_attachment_metadata: list[dict[str, Any]] = field(default_factory=list)
    browser_target: dict[str, Any] | None = None


@dataclass(slots=True)
class AssistantStreamState:
    """Accumulator for the assistant pass of a single streaming turn.

    The chat loop appends chunks here as they arrive from the provider
    so that, once the stream completes, the final assistant message can
    be assembled from a single mutable object. Tool calls, images,
    usage stats, and provider/model identifiers all live here too so
    that the post-stream cleanup path has one place to look.
    """

    content_chunks: list[str] = field(default_factory=list)
    reasoning_chunks: list[str] = field(default_factory=list)
    images: list[GeneratedImage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    model: str = ""
    provider: str = ""

    @property
    def content(self) -> str:
        return "".join(self.content_chunks)

    @property
    def reasoning_content(self) -> str:
        return "".join(self.reasoning_chunks)

    @property
    def has_visible_output(self) -> bool:
        return bool(self.content or self.images)


__all__ = [
    "AssistantStreamState",
    "MemoryRecallResult",
    "PromptPackage",
    "PromptPreparation",
]
