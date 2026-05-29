"""Tool execution phase for the streaming turn loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import plan_mode_event
from personagent.application.use_cases.chat.helpers import (
    attach_plan_approval_artifact,
    set_session_status,
)
from personagent.application.use_cases.chat.messaging.state import StreamingTurnState
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.tools import ToolExecutionStatus


class StreamingTurnToolMixin:
    async def _execute_tools(
        self,
        *,
        tool_calls: list[Any],
        tool_context: dict[str, Any] | None,
        conversation: Conversation,
        request: ChatRequestDTO,
        turn_state: StreamingTurnState,
        break_holder: list[bool],
    ) -> AsyncIterator[StreamChunk]:
        orchestrator = self._new_orchestrator()
        results_by_id: dict[str, Any] = {}
        waiting_for_plan_approval = False
        waiting_for_tool_approval = False
        turn_state.coverage.record_tool_calls(tool_calls)
        async for event in orchestrator.execute(tool_calls, tool_context):
            if event.result is not None:
                turn_state.coverage.record_tool_result(event.result)
                results_by_id[event.call.id] = event.result
                await self._operational_memory.capture_tool_result(
                    request,
                    conversation,
                    event.call,
                    event.result,
                    tool_context,
                )
            metadata = event.to_stream_metadata()
            if (
                event.result is not None
                and event.event == "permission_required"
            ):
                if self._tool_results.is_user_question(event.result):
                    set_session_status(conversation, "pending")
                    metadata.update(
                        self._tool_results.record_pending_question(
                            conversation,
                            event.call,
                            event.result,
                            request,
                        )
                    )
                    metadata["event"] = "ask_user_question"
                    waiting_for_tool_approval = True
                    turn_state.final_finish_reason = "user_input_required"
                else:
                    set_session_status(conversation, "pending")
                    metadata.update(
                        self._tool_results.record_pending_approval(
                            conversation,
                            event.call,
                            event.result,
                            request,
                        )
                    )
                    waiting_for_tool_approval = True
                    turn_state.final_finish_reason = "permission_required"
            yield StreamChunk(metadata=metadata)
            if event.result is not None and self._tool_results.is_plan_approval(
                event.result
            ):
                self._tool_results.apply_state(event.result, conversation)
                state = self._tool_results.plan_state_from(
                    event.result, conversation
                )
                attach_plan_approval_artifact(conversation, state)
                yield StreamChunk(
                    metadata=plan_mode_event(
                        str(conversation.id),
                        state,
                        event="plan_approval_requested",
                    )
                )
                waiting_for_plan_approval = True
                turn_state.final_finish_reason = "plan_approval_requested"
            elif event.result is not None and self._tool_results.is_plan_mode(
                event.result
            ):
                self._tool_results.apply_state(event.result, conversation)
                state = self._tool_results.plan_state_from(
                    event.result, conversation
                )
                yield StreamChunk(
                    metadata=plan_mode_event(str(conversation.id), state)
                )

        for call in tool_calls:
            result = results_by_id.get(call.id)
            if result is not None:
                self._tool_results.apply_state(result, conversation)
                if result.status != ToolExecutionStatus.PERMISSION_REQUIRED:
                    conversation.add_message(
                        self._tool_results.tool_message_from(result)
                    )
                    turn_state.executed_tools = True
        last_assistant = next(
            (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
            None,
        )
        if last_assistant is not None:
            last_assistant.metadata["tool_coverage"] = turn_state.coverage.to_metadata()
        break_holder[0] = waiting_for_plan_approval or waiting_for_tool_approval
