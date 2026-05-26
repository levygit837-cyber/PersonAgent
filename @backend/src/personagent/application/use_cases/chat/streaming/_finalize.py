"""Post-loop finalization for the streaming turn."""

from __future__ import annotations

from collections.abc import AsyncIterator

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import (
    auto_finalize_plan_mode,
    plan_mode_event,
)
from personagent.application.use_cases.chat.helpers import (
    attach_plan_approval_artifact,
    context_usage_metadata,
    optional_int,
    set_session_status,
)
from personagent.application.use_cases.chat.messaging.state import StreamingTurnState
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.llm_backend.models import StreamChunk


class StreamingTurnFinalizeMixin:
    async def _finalize_turn(
        self,
        *,
        conversation: Conversation,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        turn_state: StreamingTurnState,
        was_empty: bool,
    ) -> AsyncIterator[StreamChunk]:
        last_assistant = next(
            (
                message
                for message in reversed(conversation.messages)
                if message.role == Role.ASSISTANT
            ),
            None,
        )
        if last_assistant is not None:
            await self._operational_memory.capture_assistant_text(
                request,
                conversation,
                context_result,
                content=last_assistant.content,
                reasoning_content=last_assistant.metadata.get("reasoning_content"),
                finish_reason=turn_state.final_finish_reason,
                provider=turn_state.final_provider,
                model=turn_state.final_model,
            )
            finalized_state = auto_finalize_plan_mode(
                conversation.metadata, last_assistant.content
            )
            if finalized_state:
                attach_plan_approval_artifact(conversation, finalized_state)
                yield StreamChunk(
                    metadata=plan_mode_event(
                        str(conversation.id),
                        finalized_state,
                        event="plan_approval_requested",
                    )
                )
                turn_state.final_finish_reason = "plan_approval_requested"

        next_step_suggestion = await self._after_turn.run_services(
            conversation,
            request,
            finish_reason=turn_state.final_finish_reason,
        )
        if next_step_suggestion:
            yield StreamChunk(
                metadata={
                    "event": "next_step_suggestion",
                    "next_step_suggestion": next_step_suggestion,
                    "conversation_id": str(conversation.id),
                }
            )

        set_session_status(conversation, "idle")
        conversation.metadata.pop("last_request_error", None)
        await self._conversation_repo.update(conversation)

        # Trigger extração de memória em background
        await self._operational_memory.trigger_memory_extraction(
            conversation, request
        )

        await self._after_turn.refresh_session_title(
            conversation, was_empty=was_empty
        )

        saved_context_metadata = context_usage_metadata(
            turn_state.last_prompt_context_metadata
        )
        if last_assistant is not None:
            saved_context_metadata.update(
                context_usage_metadata(last_assistant.metadata or {})
            )
            after_turn_tokens = optional_int(
                (last_assistant.metadata or {}).get(
                    "context_tokens_after_turn_estimated"
                )
            )
            if after_turn_tokens is not None:
                saved_context_metadata[
                    "context_tokens_after_turn_estimated"
                ] = after_turn_tokens

        yield StreamChunk(
            metadata={
                "event": "conversation_saved",
                "conversation_id": str(conversation.id),
                "title": conversation.title,
                "finish_reason": turn_state.final_finish_reason,
                "usage": turn_state.final_usage,
                "model": turn_state.final_model,
                "provider": turn_state.final_provider,
                "next_step_suggestion": next_step_suggestion,
                **saved_context_metadata,
            }
        )
