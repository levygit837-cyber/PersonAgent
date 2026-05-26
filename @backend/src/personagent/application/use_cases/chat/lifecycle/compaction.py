"""Context compaction extracted from ``chat_completion.py``.

The chat completion use case asks two questions on every turn:

* "Would the next request exceed our context budget?"
  -- answered by :meth:`ConversationCompactor.should_compact`,
  which compares
  :meth:`ConversationCompactor.estimate_request_tokens` against
  :meth:`ConversationCompactor.compaction_threshold`.

* "If yes, summarize the older portion of the conversation so the
   next request fits."  -- answered by
   :meth:`ConversationCompactor.compact_conversation`, which collapses
   the older messages into a single SYSTEM continuity summary while
   preserving the last few turns and any messages carrying a plan
   approval artifact (the frontend reconstructs the plan panel from
   those, so they cannot be summarized away).

Pulling this surface out of :class:`ChatCompletionUseCase` keeps the
use case focused on turn orchestration. Tests can also exercise the
compactor in isolation -- the LLM backend is the only collaborator and
the API surface is now small and explicit.

Public surface
==============

* :class:`ConversationCompactor` -- the compactor, holding the LLM
  backend and the two token-budget knobs (``context_window_tokens``
  and ``default_output_tokens``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from personagent.application.dto import ChatRequestDTO
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.domain.prompts.compact import BASE_COMPACT_PROMPT

logger = structlog.get_logger(__name__)


# Cap the summary input so we don't bust the summarizer's own context.
# The compactor runs in the same provider/model as the user turn, so the
# limit has to be conservative even for 1M-token models -- 120k chars is
# ~30k tokens, comfortable below every supported backend.
_SUMMARY_INPUT_CHAR_LIMIT = 120_000

# Maximum output budget for the compaction summary itself.
_SUMMARY_OUTPUT_TOKENS = 2_048

# Floor for the prompt budget. We never want to push the request to a
# threshold below this regardless of what the request configuration
# says, because below this point the user prompt is more expensive than
# the conversation itself.
_PROMPT_BUDGET_FLOOR = 2_048

# Multiplier used when sizing the compaction threshold: we trigger
# compaction at 90% of the available prompt budget so the next turn has
# room to grow.
_PROMPT_BUDGET_USAGE_RATIO = 0.9

# Number of recent messages we always preserve verbatim. Tool messages
# at the boundary are pulled back into the recent window so we never
# orphan a tool result from its assistant call.
_RECENT_MESSAGE_COUNT = 8

# Per-message truncation in the summary input. Anything longer than
# this is cut to ``[truncated]`` so a single huge message can't push
# the summary past ``_SUMMARY_INPUT_CHAR_LIMIT``.
_PER_MESSAGE_CHAR_CAP = 4_000

# Excerpt length used by the deterministic fallback summary.
_FALLBACK_EXCERPT_CHAR_CAP = 500


class ConversationCompactor:
    """Decide-and-apply context compaction for a single conversation.

    The compactor is stateless except for the configuration it captures
    in :meth:`__init__`; the only mutation it ever performs is on the
    :class:`~personagent.domain.models.conversation.Conversation` it is
    handed in :meth:`compact_conversation`.
    """

    def __init__(
        self,
        llm_backend: LLMBackendRepository,
        *,
        context_window_tokens: int,
        default_output_tokens: int,
    ) -> None:
        self._llm_backend = llm_backend
        # Mirror the same flooring the use case applies so callers can
        # construct the compactor from raw settings without surprises.
        self._context_window_tokens = max(4_096, int(context_window_tokens))
        self._default_output_tokens = max(1, int(default_output_tokens))

    @property
    def context_window_tokens(self) -> int:
        return self._context_window_tokens

    @property
    def default_output_tokens(self) -> int:
        return self._default_output_tokens

    # ---- Threshold math --------------------------------------------------

    def estimate_request_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        """Rough character-based token estimate for ``messages + tools``.

        Uses the standard ``ceil(chars / 4)`` heuristic and adds a small
        per-message overhead for the role string. Cheap to call on
        every turn -- which we do twice when compaction triggers.
        """

        message_chars = 0
        for message in messages:
            message_chars += len(str(message.get("role") or "")) + 4
            message_chars += len(str(message.get("content") or ""))
            if message.get("tool_calls"):
                message_chars += len(str(message["tool_calls"]))
            if message.get("tool_call_id"):
                message_chars += len(str(message["tool_call_id"]))
        tool_chars = sum(len(str(tool)) for tool in tools)
        total_chars = message_chars + tool_chars
        return 0 if total_chars <= 0 else max(1, (total_chars + 3) // 4)

    def compaction_threshold(self, request: ChatRequestDTO) -> int:
        """Maximum prompt-token budget before compaction kicks in.

        The budget is the window minus the output reserve (the user's
        explicit ``max_tokens`` if provided, otherwise the lesser of
        the default output cap and a quarter of the window) and the
        reasoning reserve. We then trigger at 90% of that budget so the
        next turn has room to grow without immediately re-compacting.
        """

        output_reserve = (
            int(request.max_tokens)
            if request.max_tokens and request.max_tokens > 0
            else min(self._default_output_tokens, self._context_window_tokens // 4)
        )
        reasoning_reserve = max(0, int(request.reasoning_budget_tokens or 0))
        prompt_budget = max(
            _PROMPT_BUDGET_FLOOR,
            self._context_window_tokens - output_reserve - reasoning_reserve,
        )
        return max(_PROMPT_BUDGET_FLOOR, int(prompt_budget * _PROMPT_BUDGET_USAGE_RATIO))

    def should_compact(self, estimated_tokens: int, request: ChatRequestDTO) -> bool:
        return estimated_tokens > self.compaction_threshold(request)

    # ---- Mutation --------------------------------------------------------

    async def compact_conversation(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
    ) -> bool:
        """Replace the older portion of ``conversation`` with a SYSTEM summary.

        Returns ``True`` when the conversation was actually mutated.

        Three classes of messages survive verbatim:
          * The last :data:`_RECENT_MESSAGE_COUNT` messages, plus any
            adjacent TOOL messages pulled back into that window so we
            never orphan a tool result.
          * Assistant messages carrying a ``plan_approval`` artifact in
            their metadata -- the frontend reconstructs the plan panel
            from those, so they must remain intact.

        Everything else gets summarized into a single SYSTEM message
        tagged with ``context_compaction``.
        """

        if len(conversation.messages) <= _RECENT_MESSAGE_COUNT + 2:
            return False

        older = conversation.messages[: -_RECENT_MESSAGE_COUNT]
        recent = conversation.messages[-_RECENT_MESSAGE_COUNT:]
        while recent and recent[0].role == Role.TOOL and older:
            recent.insert(0, older.pop())
        if not older:
            return False

        preserved: list[Message] = []
        compactable: list[Message] = []
        for msg in older:
            if (
                msg.role == Role.ASSISTANT
                and isinstance(msg.metadata, dict)
                and msg.metadata.get("plan_approval")
            ):
                preserved.append(msg)
            else:
                compactable.append(msg)

        if not compactable and not preserved:
            return False

        summary = await self._summarize_messages(compactable or older, request)
        summary_message = Message(
            role=Role.SYSTEM,
            content=(
                "Conversation Continuity Summary\n\n"
                "Earlier conversation messages were compacted to stay within the context "
                "window. Use this summary as continuity context, then rely on the recent "
                "messages below for exact current state.\n\n"
                f"{summary}"
            ),
            metadata={
                "context_compaction": True,
                "compacted_message_count": len(older),
            },
        )
        conversation.messages = [summary_message, *preserved, *recent]
        conversation.metadata["context_compaction"] = {
            "compacted": True,
            "compacted_message_count": len(older),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return True

    # ---- Summarization ---------------------------------------------------

    async def _summarize_messages(
        self,
        messages: list[Message],
        request: ChatRequestDTO,
    ) -> str:
        """Ask the LLM to summarize ``messages``; fall back deterministically."""

        rendered = self.render_messages_for_summary(messages)
        prompt = BASE_COMPACT_PROMPT
        try:
            result = await self._llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": rendered[:_SUMMARY_INPUT_CHAR_LIMIT]},
                ],
                temperature=0.1,
                max_tokens=_SUMMARY_OUTPUT_TOKENS,
                stream=False,
                tools=None,
                tool_choice=None,
                model=request.model,
                provider=request.provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
            content = str(result.content or "").strip()
            if content:
                return content
        except Exception:
            logger.warning("context_compaction_failed", exc_info=True)
        return self.fallback_summary(messages)

    @staticmethod
    def render_messages_for_summary(messages: list[Message]) -> str:
        """Format ``messages`` as a numbered markdown transcript.

        Each message is truncated to :data:`_PER_MESSAGE_CHAR_CAP`
        chars so an absurdly long single turn can't dominate the
        summary input.
        """

        rendered: list[str] = []
        for index, message in enumerate(messages, start=1):
            content = message.content
            if len(content) > _PER_MESSAGE_CHAR_CAP:
                content = content[:_PER_MESSAGE_CHAR_CAP].rstrip() + "\n[truncated]"
            rendered.append(f"## Message {index}: {message.role.value}\n\n{content}")
            if message.tool_calls:
                rendered.append(f"Tool calls: {message.tool_calls}")
        return "\n\n".join(rendered)

    @staticmethod
    def fallback_summary(messages: list[Message]) -> str:
        """Deterministic last-resort summary when the LLM call fails.

        Picks the first and last three messages, normalizes whitespace,
        and clips each excerpt to :data:`_FALLBACK_EXCERPT_CHAR_CAP`
        chars. Always returns *something* the assistant can read so we
        never lose continuity context entirely.
        """

        excerpts: list[str] = []
        for message in messages[:3] + messages[-3:]:
            content = " ".join(message.content.split())
            excerpts.append(
                f"- {message.role.value}: {content[:_FALLBACK_EXCERPT_CHAR_CAP]}"
            )
        return (
            f"{len(messages)} earlier messages were compacted. Available excerpts:\n"
            + "\n".join(excerpts)
        )


__all__ = ["ConversationCompactor"]
