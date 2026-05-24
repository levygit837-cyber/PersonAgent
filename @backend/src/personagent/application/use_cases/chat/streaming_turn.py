"""Outer streaming-turn loop for ``ChatCompletionUseCase``.

The streaming turn loop is the orchestration backbone of a chat
completion. It wires together every collaborator -- context build,
prompt assembly, memory recall, tool execution, after-turn cleanup --
into a single async iterator that emits :class:`StreamChunk` events to
the caller. Pulling it out of ``ChatCompletionUseCase`` lets the use
case file shrink to a thin facade over the executor while keeping the
exact behavior verbatim.

The executor holds no per-turn state; everything that needs to survive
across loop iterations lives on :class:`StreamingTurnState` and
:class:`AssistantStreamState`, both passed in / constructed locally.
Constructor injection is used for every collaborator plus the
plain-callable hooks (``build_context_result`` etc.) that previously
lived as private methods on the use case.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import (
    auto_finalize_plan_mode,
    plan_mode_event,
)
from personagent.application.tools import ToolOrchestrator
from personagent.application.use_cases.chat.after_turn import AfterTurnCoordinator
from personagent.application.use_cases.chat.assistant_pass import AssistantPassRunner
from personagent.application.use_cases.chat.helpers import (
    attach_plan_approval_artifact,
    context_after_turn_metadata,
    context_usage_metadata,
    optional_int,
    set_session_status,
)
from personagent.application.use_cases.chat.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.memory_recall import MemoryRecallCoordinator
from personagent.application.use_cases.chat.message_preparation import MessagePreparer
from personagent.application.use_cases.chat.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.application.use_cases.chat.prompt_package import PromptPackageBuilder
from personagent.application.use_cases.chat.prompt_surfaces import PromptSurfacePreparer
from personagent.application.use_cases.chat.state import (
    AssistantStreamState,
    StreamingTurnState,
)
from personagent.application.use_cases.chat.stream_normalization import (
    StreamChunkNormalizer,
)
from personagent.application.use_cases.chat.tool_context_builder import (
    ToolContextBuilder,
)
from personagent.application.use_cases.chat.tool_results import ToolResultHandler
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.exceptions import (
    LLMBackendError,
    ToolLoopLimitExceededError,
)
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import StreamChunk
from personagent.domain.repositories.conversation_repository import (
    ConversationRepository,
)
from personagent.domain.tools import ToolExecutionStatus

logger = structlog.get_logger(__name__)


class StreamingTurnExecutor:
    """Executes one streaming turn end-to-end, emitting ``StreamChunk`` events.

    Parameters
    ----------
    Collaborators are injected wholesale; the plain-callable hooks
    (``build_context_result`` etc.) wrap private methods that remain on
    :class:`ChatCompletionUseCase` so the executor does not need to know
    about the surrounding tool registry / runtime config plumbing.
    """

    def __init__(
        self,
        *,
        conversation_repo: ConversationRepository,
        memory_recall: MemoryRecallCoordinator,
        prompt_surfaces: PromptSurfacePreparer,
        prompt_package_builder: PromptPackageBuilder,
        media_policy: MediaPolicyHandler,
        operational_memory: OperationalMemoryCapture,
        tool_context_builder: ToolContextBuilder,
        message_preparer: MessagePreparer,
        assistant_pass_runner: AssistantPassRunner,
        stream_chunk_normalizer: StreamChunkNormalizer,
        tool_results: ToolResultHandler,
        after_turn: AfterTurnCoordinator,
        build_context_result: Callable[
            [ChatRequestDTO, Conversation], Awaitable[ContextBuildResult]
        ],
        resolve_tool_schemas: Callable[
            [ChatRequestDTO, Conversation], list[dict[str, Any]]
        ],
        new_orchestrator: Callable[[], ToolOrchestrator],
        effective_max_tool_iterations: Callable[[ChatRequestDTO], int],
        tool_iteration_limit_source: Callable[[ChatRequestDTO], str],
        schedule_background: Callable[..., None],
    ) -> None:
        self._conversation_repo = conversation_repo
        self._memory_recall = memory_recall
        self._prompt_surfaces = prompt_surfaces
        self._prompt_package_builder = prompt_package_builder
        self._media_policy = media_policy
        self._operational_memory = operational_memory
        self._tool_context_builder = tool_context_builder
        self._message_preparer = message_preparer
        self._assistant_pass_runner = assistant_pass_runner
        self._stream_chunk_normalizer = stream_chunk_normalizer
        self._tool_results = tool_results
        self._after_turn = after_turn
        self._build_context_result = build_context_result
        self._resolve_tool_schemas = resolve_tool_schemas
        self._new_orchestrator = new_orchestrator
        self._effective_max_tool_iterations = effective_max_tool_iterations
        self._tool_iteration_limit_source = tool_iteration_limit_source
        self._schedule_background = schedule_background

    async def run(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        *,
        append_user_message: bool,
        was_empty: bool,
        status: str,
    ) -> AsyncIterator[StreamChunk]:
        """Execute one streaming turn, optionally without a new user message."""
        context_result = await self._build_context_result(request, conversation)
        preparation = self._prompt_surfaces.prepare(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request, conversation)

        if append_user_message:
            user_msg = Message(
                role=Role.USER,
                content=request.message,
                metadata=self._prompt_surfaces.user_message_metadata(preparation),
            )
            conversation.add_message(user_msg)
            await self._conversation_repo.update(conversation)
            if not request.tool_context.get("permission_mode"):
                conversation.metadata.pop("permission_mode", None)

        # Emite status para o frontend saber que está montando o prompt
        yield StreamChunk(metadata={"event": "status", "status": status})

        # Recall memórias relevantes
        memory_recall = await self._memory_recall.recall(
            request, context_result, conversation
        )

        prompt_package = await self._prompt_package_builder.build(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=memory_recall.prompt_memories,
            memory_trace=memory_recall.trace,
        )
        self._media_policy.enforce_request_policy(request, prompt_package)
        if append_user_message:
            self._schedule_background(
                self._operational_memory.capture_user_message(
                    request, context_result, conversation
                ),
                task_name="operational_user_capture",
            )

        tool_context = (
            self._tool_context_builder.build(request, conversation, preparation)
            if tools
            else None
        )
        turn_state = StreamingTurnState(
            final_model=request.model,
            final_provider=request.provider,
        )
        effective_max_iterations = self._effective_max_tool_iterations(request)

        try:
            while True:
                if turn_state.iteration >= effective_max_iterations:
                    raise ToolLoopLimitExceededError(
                        f"Tool loop exceeded {effective_max_iterations} iterations",
                        metadata={
                            "limit": effective_max_iterations,
                            "conversation_id": str(conversation.id),
                            "source": self._tool_iteration_limit_source(request),
                        },
                    )
                messages, context_metadata = await self._message_preparer.prepare(
                    conversation,
                    request,
                    prompt_package,
                    tools,
                )
                turn_state.last_prompt_context_metadata = context_metadata
                yield StreamChunk(
                    metadata={
                        "event": "prompt_context",
                        **context_metadata,
                    }
                )
                assistant_state = AssistantStreamState(
                    model=request.model,
                    provider=request.provider,
                    metadata=context_usage_metadata(context_metadata),
                )

                async for forwarded_chunk in self._assistant_pass_runner.run(
                    request=request,
                    conversation_id=str(conversation.id),
                    messages=messages,
                    tools=tools,
                    seen_tool_call_ids=turn_state.seen_tool_call_ids,
                    iteration=turn_state.iteration,
                    state=assistant_state,
                ):
                    yield forwarded_chunk

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
                        assistant_state = retry_state
                    else:
                        notice = self._stream_chunk_normalizer.empty_model_response_notice(
                            provider=assistant_state.provider or request.provider,
                            model=assistant_state.model or request.model,
                        )
                        assistant_state = AssistantStreamState(
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
                            usage=assistant_state.usage,
                            metadata={
                                "event": "empty_model_response",
                                "provider": assistant_state.provider,
                                "model": assistant_state.model,
                            },
                        )

                turn_state.final_finish_reason = (
                    assistant_state.finish_reason
                    if assistant_state.finish_reason != "tool_calls"
                    else turn_state.final_finish_reason
                )
                turn_state.final_usage = (
                    assistant_state.usage or turn_state.final_usage
                )
                turn_state.final_model = (
                    assistant_state.model or turn_state.final_model
                )
                turn_state.final_provider = (
                    assistant_state.provider or turn_state.final_provider
                )
                conversation.add_message(
                    Message(
                        role=Role.ASSISTANT,
                        content=assistant_state.content,
                        tool_calls=assistant_state.tool_calls,
                        metadata={
                            "reasoning_content": assistant_state.reasoning_content
                            or None,
                            "finish_reason": assistant_state.finish_reason,
                            "usage": assistant_state.usage,
                            "model": assistant_state.model,
                            "provider": assistant_state.provider,
                            "images": [
                                image.to_dict() for image in assistant_state.images
                            ],
                            **context_usage_metadata(context_metadata),
                            **context_after_turn_metadata(
                                context_metadata, assistant_state
                            ),
                            **assistant_state.metadata,
                        },
                    )
                )

                tool_calls = self._tool_results.parse_calls(
                    assistant_state.tool_calls
                )
                if not tool_calls or not tool_context:
                    break

                orchestrator = self._new_orchestrator()
                results_by_id: dict[str, Any] = {}
                waiting_for_plan_approval = False
                waiting_for_tool_approval = False
                async for event in orchestrator.execute(tool_calls, tool_context):
                    if event.result is not None:
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
                turn_state.iteration += 1
                if waiting_for_plan_approval or waiting_for_tool_approval:
                    break

        except LLMBackendError as exc:
            logger.error("llm_backend_stream_error", error=str(exc))
            set_session_status(conversation, "error")
            conversation.metadata["last_request_error"] = str(exc)
            await self._conversation_repo.update(conversation)
            raise
        except ToolLoopLimitExceededError as exc:
            logger.warning(
                "tool_loop_limit_exceeded_stream",
                conversation_id=str(conversation.id),
                limit=effective_max_iterations,
            )
            set_session_status(conversation, "error")
            conversation.metadata["last_request_error"] = str(exc)
            await self._conversation_repo.update(conversation)
            yield StreamChunk(
                metadata={
                    "event": "tool_loop_limit_exceeded",
                    "conversation_id": str(conversation.id),
                    "limit": effective_max_iterations,
                    "source": self._tool_iteration_limit_source(request),
                    "finish_reason": "tool_loop_limit_exceeded",
                }
            )
            turn_state.final_finish_reason = "tool_loop_limit_exceeded"
            # Fall through to the post-loop cleanup so the UI receives
            # conversation_saved with the final state, instead of leaving the
            # stream half-closed.

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
        await self._operational_memory.trigger_memory_extraction(conversation, request)

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
                saved_context_metadata["context_tokens_after_turn_estimated"] = (
                    after_turn_tokens
                )

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
