"""LLM message preparation extracted from ``chat_completion.py``.

After the prompt package is built and tools are resolved, the chat
use case still has to translate the in-memory :class:`Conversation`
into the OpenAI-shaped ``messages`` list that the provider expects.
Two responsibilities are bundled here:

* :class:`MessagePreparer.with_prompt` -- the synchronous, pure
  conversation-to-messages transform. The system prompt is prepended
  and each conversation message is rendered via ``Message.to_dict``,
  with provider-specific carry-throughs for DeepSeek / ZenMux
  reasoning fields.
* :class:`MessagePreparer.prepare` -- the async path that wraps
  :meth:`with_prompt` with the conversation compactor's token-budget
  check. If the estimated token count exceeds the configured
  compaction threshold, the conversation is compacted in-place and
  the messages are re-rendered.
* :class:`MessagePreparer.with_final_answer_reminder` -- the tiny
  fallback that injects a "the previous pass stopped without a visible
  answer; respond now" reminder into the system prompt before a
  recovery LLM call.
* :class:`MessagePreparer.with_synthesis_reminder` -- a transient
  synthesis nudge used once gathered evidence is ready for the final
  answer.

Backward compatibility: every method preserves its inputs, outputs,
and side-effects exactly. The chat use case now delegates to
``self._message_preparer.<verb>(...)``.

Concurrency: stateless. Safe to share across requests -- everything
it needs is captured at construction (:class:`ConversationCompactor`
and the static context-window budget) or passed in via the method.
"""

from __future__ import annotations

from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.lifecycle.compaction import ConversationCompactor
from personagent.application.use_cases.chat.messaging.state import PromptPackage
from personagent.application.use_cases.chat.messaging.system_reminders import (
    with_final_answer_reminder,
    with_synthesis_reminder,
    with_system_reminder,
)
from personagent.application.use_cases.chat.tooling.tool_result_budget import (
    ToolResultBudgetService,
    reconstruct_state_from_conversation,
)
from personagent.domain.conversation.models import Conversation, Role

_REASONING_CONTENT_PROVIDERS = frozenset({"deepseek", "zenmux"})
_REASONING_DETAILS_PROVIDERS = frozenset({"zenmux"})


class MessagePreparer:
    """Render the OpenAI-shaped ``messages`` list for one LLM call.

    The preparer encapsulates two things at once:

    1. *Format*: how a :class:`Conversation` and the materialized
       :class:`PromptPackage` turn into the provider message list,
       including the DeepSeek / ZenMux reasoning carry-through.
    2. *Budget*: whether the conversation needs compaction before the
       next call and, if so, applying it in-place and re-rendering.
    3. *Tool Result Budget*: caps aggregate tool result size per
       assistant-turn group before the messages reach the LLM.

    The pure-formatting helpers (:meth:`with_prompt`,
    :meth:`with_final_answer_reminder`, :meth:`with_synthesis_reminder`)
    are individually callable.
    """

    def __init__(
        self,
        *,
        compactor: ConversationCompactor,
        context_window_tokens: int,
        tool_result_budget_service: ToolResultBudgetService | None = None,
    ) -> None:
        self._compactor = compactor
        self._context_window_tokens = context_window_tokens
        self._tool_result_budget_service = tool_result_budget_service

    # ---- Public API -----------------------------------------------------

    async def prepare(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
        prompt_package: PromptPackage,
        tools: list[dict[str, Any]],
        *,
        skip_tool_names: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return the OpenAI ``messages`` list and the context metadata.

        The metadata dict carries the prompt-package metadata plus
        three context-budget fields (``context_tokens_estimated``,
        ``context_compacted``, ``context_window_tokens``). Compaction
        is applied at most once -- if the conversation is still over
        budget after the compaction attempt, the second estimate is
        reported in ``context_tokens_estimated`` but no further
        attempt is made.
        """

        messages = self.with_prompt(
            conversation,
            prompt_package,
            include_reasoning_content=request.provider in _REASONING_CONTENT_PROVIDERS,
            include_reasoning_details=request.provider in _REASONING_DETAILS_PROVIDERS,
        )

        # ---- Apply tool result budget (Layer 2) -------------------------
        if self._tool_result_budget_service is not None:
            state = reconstruct_state_from_conversation(conversation)
            messages = await self._tool_result_budget_service.apply_budget(
                messages,
                conversation,
                state,
                skip_tool_names=skip_tool_names,
            )

        estimated_tokens = self._compactor.estimate_request_tokens(messages, tools)
        metadata: dict[str, Any] = {
            **prompt_package.metadata,
            "context_tokens_estimated": estimated_tokens,
            "context_compacted": False,
            "context_window_tokens": self._context_window_tokens,
        }

        if not self._compactor.should_compact(estimated_tokens, request):
            return messages, metadata

        compacted = await self._compactor.compact_conversation(conversation, request)
        if not compacted:
            return messages, metadata

        messages = self.with_prompt(
            conversation,
            prompt_package,
            include_reasoning_content=request.provider in _REASONING_CONTENT_PROVIDERS,
            include_reasoning_details=request.provider in _REASONING_DETAILS_PROVIDERS,
        )
        estimated_tokens = self._compactor.estimate_request_tokens(messages, tools)
        metadata.update(
            {
                "context_tokens_estimated": estimated_tokens,
                "context_compacted": True,
            }
        )
        return messages, metadata

    def with_prompt(
        self,
        conversation: Conversation,
        prompt_package: PromptPackage,
        *,
        include_reasoning_content: bool = False,
        include_reasoning_details: bool = False,
    ) -> list[dict[str, Any]]:
        """Render ``conversation`` into the OpenAI ``messages`` list."""

        messages: list[dict[str, Any]] = []
        if prompt_package.system_prompt:
            messages.append(
                {"role": "system", "content": prompt_package.system_prompt}
            )
        for message in conversation.messages:
            # Skip assistant messages that were interrupted/aborted
            # (empty content and no tool calls = incomplete stream)
            if (
                message.role == Role.ASSISTANT
                and not message.content.strip()
                and not message.tool_calls
            ):
                continue
            rendered = message.to_dict()
            reasoning_content = message.metadata.get("reasoning_content")
            if (
                include_reasoning_content
                and message.role == Role.ASSISTANT
                and isinstance(reasoning_content, str)
                and reasoning_content
            ):
                rendered["reasoning_content"] = reasoning_content
            reasoning_details = message.metadata.get("zenmux_reasoning_details")
            if (
                include_reasoning_details
                and message.role == Role.ASSISTANT
                and reasoning_details
            ):
                rendered["reasoning_details"] = reasoning_details
            messages.append(rendered)
        return messages

    def with_final_answer_reminder(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Inject a "respond now, do not call more tools" recovery reminder."""

        return with_final_answer_reminder(messages)

    def with_synthesis_reminder(
        self,
        messages: list[dict[str, Any]],
        evidence_summary: Any,
    ) -> list[dict[str, Any]]:
        """Inject the final-synthesis reminder for evidence-ready turns."""

        return with_synthesis_reminder(messages, evidence_summary)

    def with_system_reminder(
        self,
        messages: list[dict[str, Any]],
        reminder: str,
    ) -> list[dict[str, Any]]:
        """Append a transient system reminder to the next model pass."""

        return with_system_reminder(messages, reminder)


__all__ = ["MessagePreparer"]
