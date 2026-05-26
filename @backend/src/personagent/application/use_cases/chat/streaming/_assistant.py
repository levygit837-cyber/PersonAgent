"""Assistant-pass retry logic for empty tool responses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.state import (
    AssistantStreamState,
    StreamingTurnState,
)
from personagent.domain.conversation.models import Conversation
from personagent.domain.llm_backend.models import StreamChunk


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
        if (
            turn_state.executed_tools
            and not assistant_state.has_visible_output
            and assistant_state.tool_calls is None
            and assistant_state.finish_reason in {None, "stop"}
        ):
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
        else:
            result_holder[0] = assistant_state
