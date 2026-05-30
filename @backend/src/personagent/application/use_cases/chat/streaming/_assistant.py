"""Assistant-pass retry logic for empty or substanceless responses."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.state import (
    AssistantStreamState,
    StreamingTurnState,
)
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.llm_backend.models import StreamChunk

_STUB_RE = re.compile(
    r"^(done|ok|fixed|completed|resolved|looks good|finished|confirmed)[.!]?$",
    re.IGNORECASE,
)

_LENGTH_REMINDER = (
    "Your previous response was truncated. Continue from where you left off, "
    "synthesizing the tool results into a complete answer."
)

_FINAL_ANSWER_REMINDER = (
    "The previous provider pass stopped after tool results without a visible "
    "final answer. Use the tool results already present in the conversation "
    "and respond now with the final answer. Do not call more tools for this "
    "recovery pass."
)


def _is_substanceless(content: str) -> bool:
    """Return True if the assistant content is empty, a stub, or too short."""
    stripped = content.strip()
    if not stripped:
        return True
    if _STUB_RE.match(stripped):
        return True
    if len(stripped) < 30 and not any(c in stripped for c in "`./[](){"):
        return True
    return False


def _last_message_is_tool(conversation: Conversation) -> bool:
    """Return True if the most recent conversation message is a tool result."""
    if not conversation.messages:
        return False
    last = conversation.messages[-1]
    return str(getattr(last, "role", "")).lower() == "tool" or (
        hasattr(last, "role") and str(getattr(last.role, "value", last.role)).lower() == "tool"
    )


class StreamingTurnAssistantMixin:
    async def _maybe_retry_empty_response(
        self,
        *,
        assistant_state: AssistantStreamState,
        turn_state: StreamingTurnState,
        request: ChatRequestDTO,
        conversation: Conversation,
        messages: list[dict[str, Any]],
        result_holder: list[AssistantStreamState],
    ) -> AsyncIterator[StreamChunk]:
        # Determine if retry is needed
        needs_retry = False
        reminder = _FINAL_ANSWER_REMINDER

        if assistant_state.finish_reason == "length":
            needs_retry = True
            reminder = _LENGTH_REMINDER
        elif _is_substanceless(assistant_state.content):
            needs_retry = True
        elif _last_message_is_tool(conversation) and assistant_state.finish_reason in {None, "stop"}:
            # The model stopped after a tool result without synthesizing
            needs_retry = True

        if not needs_retry:
            result_holder[0] = assistant_state
            return

        # If the model claims ready_for_final but evidence is insufficient,
        # ignore the claim and force more exploration.
        if assistant_state.ready_for_final and _is_substanceless(assistant_state.content):
            assistant_state.ready_for_final = False

        retry_state = AssistantStreamState(
            reasoning_chunks=list(assistant_state.reasoning_chunks),
            model=assistant_state.model or request.model,
            provider=assistant_state.provider or request.provider,
        )
        yield StreamChunk(
            metadata={
                "event": "status",
                "status": "retrying_empty_tool_response",
                "provider": assistant_state.provider or request.provider,
                "model": assistant_state.model or request.model,
            }
        )
        async for forwarded_chunk in self._assistant_pass_runner.run(
            request=request,
            conversation_id=str(conversation.id),
            messages=self._message_preparer.with_final_answer_reminder(
                messages
            ),
            tools=[],
            seen_tool_call_ids=turn_state.seen_tool_call_ids,
            iteration=turn_state.iteration,
            state=retry_state,
        ):
            yield forwarded_chunk
        if retry_state.has_visible_output or retry_state.tool_calls:
            result_holder[0] = retry_state
        else:
            notice = self._stream_chunk_normalizer.empty_model_response_notice(
                provider=assistant_state.provider or request.provider,
                model=assistant_state.model or request.model,
            )
            result_holder[0] = AssistantStreamState(
                content_chunks=[notice],
                reasoning_chunks=list(retry_state.reasoning_chunks),
                finish_reason="empty_model_response",
                usage=retry_state.usage,
                model=retry_state.model
                or assistant_state.model
                or request.model,
                provider=retry_state.provider
                or assistant_state.provider
                or request.provider,
                metadata={
                    **assistant_state.metadata,
                    **retry_state.metadata,
                    "empty_model_response": True,
                },
            )
            yield StreamChunk(
                content=notice,
                finish_reason="empty_model_response",
                usage=result_holder[0].usage,
                metadata={
                    "event": "empty_model_response",
                    "provider": result_holder[0].provider,
                    "model": result_holder[0].model,
                },
            )
