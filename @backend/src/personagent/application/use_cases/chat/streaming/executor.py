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
from typing import TYPE_CHECKING, Any

import structlog

from personagent.application.dto import ChatRequestDTO
from personagent.application.tools import ToolOrchestrator
from personagent.application.use_cases.chat.evidence_gate import EvidenceGateService
from personagent.application.use_cases.chat.helpers import (
    context_after_turn_metadata,
    context_usage_metadata,
    set_session_status,
)

if TYPE_CHECKING:
    from personagent.application.use_cases.chat.lifecycle.after_turn import AfterTurnCoordinator
    from personagent.application.use_cases.chat.lifecycle.assistant_pass import AssistantPassRunner
from personagent.application.use_cases.chat.memory.memory_recall import MemoryRecallCoordinator
from personagent.application.use_cases.chat.memory.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.application.use_cases.chat.messaging.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.messaging.message_preparation import MessagePreparer
from personagent.application.use_cases.chat.messaging.state import (
    AssistantStreamState,
    InvestigationState,
    StreamingTurnState,
)
from personagent.application.use_cases.chat.prompt.prompt_package import PromptPackageBuilder
from personagent.application.use_cases.chat.prompt.prompt_surfaces import PromptSurfacePreparer
from personagent.application.use_cases.chat.streaming.normalization import (
    StreamChunkNormalizer,
)
from personagent.application.use_cases.chat.tooling.tool_context_builder import (
    ToolContextBuilder,
)
from personagent.application.use_cases.chat.tooling.tool_results import ToolResultHandler
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.conversation.repositories import (
    ConversationRepository,
)
from personagent.domain.exceptions import (
    LLMBackendError,
    ToolLoopLimitExceededError,
)
from personagent.domain.llm_backend.models import StreamChunk

from ._assistant import StreamingTurnAssistantMixin
from ._finalize import StreamingTurnFinalizeMixin
from ._tools import StreamingTurnToolMixin

logger = structlog.get_logger(__name__)


class StreamingTurnExecutor(
    StreamingTurnAssistantMixin,
    StreamingTurnToolMixin,
    StreamingTurnFinalizeMixin,
):
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
        evidence_gate: EvidenceGateService | None = None,
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
        self._evidence_gate = evidence_gate or EvidenceGateService()
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
        investigation_state = InvestigationState.classify(request)
        context_result = await self._build_context_result(request, conversation)
        preparation = self._prompt_surfaces.prepare(request, context_result)
        request = preparation.request
        if investigation_state.active:
            investigation_state.advance("discover")
            conversation.metadata["investigation_state"] = investigation_state.to_metadata()
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
        yield StreamChunk(
            metadata={
                "event": "memory_recall_started",
                "memory_status": "running",
                "memory_message": "Recalling memories...",
            }
        )
        memory_recall = await self._memory_recall.recall(
            request, context_result, conversation
        )
        yield StreamChunk(
            metadata={
                "event": "memory_recall_finished",
                "memory_status": "completed",
                "memory_count": _memory_recall_count(memory_recall.trace),
                "memory_trace": memory_recall.trace,
            }
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
        evidence_gate_reminder: str | None = None

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
                if investigation_state.active:
                    investigation_state.advance("inspect")
                    messages = self._message_preparer.with_system_reminder(
                        messages, investigation_state.reminder()
                    )
                if evidence_gate_reminder:
                    messages = self._message_preparer.with_system_reminder(
                        messages, evidence_gate_reminder
                    )
                    evidence_gate_reminder = None
                ready_for_synthesis = (
                    investigation_state.active and investigation_state.ready_for_final
                )
                pass_tools = [] if ready_for_synthesis else tools
                if ready_for_synthesis:
                    messages = self._message_preparer.with_synthesis_reminder(
                        messages, investigation_state.to_metadata()
                    )
                turn_state.last_prompt_context_metadata = context_metadata
                turn_state.coverage.record_prompt_metadata(context_metadata)
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
                    tools=pass_tools,
                    seen_tool_call_ids=turn_state.seen_tool_call_ids,
                    iteration=turn_state.iteration,
                    state=assistant_state,
                ):
                    yield forwarded_chunk

                assistant_holder: list[AssistantStreamState] = [assistant_state]
                async for chunk in self._maybe_retry_empty_response(
                    assistant_state=assistant_state,
                    turn_state=turn_state,
                    request=request,
                    conversation=conversation,
                    messages=messages,
                    result_holder=assistant_holder,
                ):
                    yield chunk
                assistant_state = assistant_holder[0]

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
                            "tool_coverage": turn_state.coverage.to_metadata(),
                        },
                    )
                )
                await self._conversation_repo.update(conversation)

                investigation_state.record_assistant_tool_calls(assistant_state.tool_calls)
                tool_calls = self._tool_results.parse_calls(
                    assistant_state.tool_calls
                )
                if not tool_calls or not tool_context:
                    investigation_state.advance("verify")
                    investigation_state.refresh_coverage()
                    conversation.metadata["investigation_state"] = investigation_state.to_metadata()
                    decision = self._evidence_gate.should_continue_investigation(
                        request,
                        conversation,
                        turn_state,
                        context_metadata,
                    )
                    if decision.should_continue and tool_context:
                        turn_state.evidence_gate_continuations += 1
                        conversation.metadata["last_evidence_gate"] = {
                            "reason": decision.reason,
                            "missing": list(decision.missing),
                            "checklist": decision.checklist,
                            "retry_count": turn_state.evidence_gate_continuations,
                        }
                        await self._conversation_repo.update(conversation)
                        yield StreamChunk(
                            metadata={
                                "event": "status",
                                "status": "continuing_evidence_investigation",
                                "evidence_gate_missing": list(decision.missing),
                                "evidence_gate_retry_count": turn_state.evidence_gate_continuations,
                            }
                        )
                        conversation.metadata["investigation_state"] = investigation_state.to_metadata()
                        evidence_gate_reminder = decision.reminder
                        continue
                    if decision.ready_for_final:
                        conversation.metadata["last_evidence_gate"] = {
                            "reason": decision.reason,
                            "missing": list(decision.missing),
                            "checklist": decision.checklist,
                            "retry_count": turn_state.evidence_gate_continuations,
                            "ready_for_final": True,
                        }
                    investigation_state.advance("synthesize")
                    investigation_state.refresh_coverage()
                    conversation.metadata["investigation_state"] = investigation_state.to_metadata()
                    break

                break_holder: list[bool] = [False]
                async for chunk in self._execute_tools(
                    tool_calls=tool_calls,
                    tool_context=tool_context,
                    conversation=conversation,
                    request=request,
                    turn_state=turn_state,
                    break_holder=break_holder,
                ):
                    yield chunk
                turn_state.iteration += 1
                investigation_state.tool_iterations = turn_state.iteration
                investigation_state.advance("verify")
                investigation_state.record_tool_messages(conversation.messages)
                conversation.metadata["investigation_state"] = investigation_state.to_metadata()
                if break_holder[0]:
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

        async for chunk in self._finalize_turn(
            conversation=conversation,
            request=request,
            context_result=context_result,
            turn_state=turn_state,
            was_empty=was_empty,
        ):
            yield chunk


def _memory_recall_count(trace: dict[str, Any] | None) -> int:
    if not isinstance(trace, dict):
        return 0
    summary = trace.get("summary")
    if isinstance(summary, dict):
        value = summary.get("total_used")
        if isinstance(value, int):
            return max(0, value)
    classic = trace.get("classic")
    operational = trace.get("operational")
    return (len(classic) if isinstance(classic, list) else 0) + (
        len(operational) if isinstance(operational, list) else 0
    )
