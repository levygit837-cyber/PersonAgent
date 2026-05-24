"""Caso de uso: Chat Completion."""

import asyncio
from collections.abc import AsyncIterator, Awaitable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

from personagent.application.dto.chat_dto import ChatRequestDTO, ChatResponseDTO
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.plan_mode import (
    activate_plan_mode_if_requested,
    auto_finalize_plan_mode,
    is_plan_mode_active,
    plan_mode_event,
)
from personagent.application.services import (
    NextStepSuggestionService,
    OperationalMemoryService,
    SessionMemoryService,
    SessionTitleService,
)
from personagent.application.tools import (
    ToolOrchestrator,
    ToolRegistry,
    ToolRuntimeConfig,
)
from personagent.application.tools.runtime_config import resolve_effective_tool_iterations
from personagent.application.use_cases.chat.after_turn import AfterTurnCoordinator
from personagent.application.use_cases.chat.compaction import ConversationCompactor
from personagent.application.use_cases.chat.conversation_lifecycle import (
    ConversationLifecycleHandler,
)
from personagent.application.use_cases.chat.helpers import (
    attach_plan_approval_artifact as _attach_plan_approval_artifact,
)
from personagent.application.use_cases.chat.helpers import (
    context_after_turn_metadata as _context_after_turn_metadata,
)
from personagent.application.use_cases.chat.helpers import (
    context_usage_metadata as _context_usage_metadata,
)
from personagent.application.use_cases.chat.helpers import (
    optional_int as _optional_int,
)
from personagent.application.use_cases.chat.helpers import (
    set_session_status as _set_session_status,
)
from personagent.application.use_cases.chat.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.memory_recall import MemoryRecallCoordinator
from personagent.application.use_cases.chat.message_preparation import MessagePreparer
from personagent.application.use_cases.chat.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.application.use_cases.chat.prompt_package import (
    PromptPackageBuilder,
)
from personagent.application.use_cases.chat.prompt_surfaces import (
    PromptSurfacePreparer,
)
from personagent.application.use_cases.chat.state import (
    AssistantStreamState as _AssistantStreamState,
)
from personagent.application.use_cases.chat.stream_normalization import (
    StreamChunkNormalizer,
)
from personagent.application.use_cases.chat.tool_context_builder import (
    ToolContextBuilder,
)
from personagent.application.use_cases.chat.tool_results import ToolResultHandler
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
from personagent.domain.context.models import ContextBuildResult, SystemContext, UserContext
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    LLMBackendError,
    ToolLoopLimitExceededError,
)
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.prompts.commands import (
    CommandRegistry,
    CommandService,
)
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.prompts.services.agent_state_resolver import AgentStateResolver
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import (
    ToolExecutionStatus,
    ToolResult,
)

logger = structlog.get_logger(__name__)

class ChatCompletionUseCase:
    """Orchestrates one chat interaction with the LLM."""

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        llm_backend: LLMBackendRepository,
        tool_registry: ToolRegistry | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
        build_context_use_case: BuildContextUseCase | None = None,
        prompt_builder: PromptBuilder | None = None,
        prompt_context_analyzer: PromptContextAnalyzer | None = None,
        agent_state_resolver: AgentStateResolver | None = None,
        command_registry: CommandRegistry | None = None,
        session_memory_service: SessionMemoryService | None = None,
        next_step_suggestion_service: NextStepSuggestionService | None = None,
        session_title_service: SessionTitleService | None = None,
        recall_memory_use_case: RecallMemoryUseCase | None = None,
        memory_job_scheduler: MemoryJobScheduler | None = None,
        memory_repository: MemoryRepository | None = None,
        operational_memory_service: OperationalMemoryService | None = None,
        context_window_tokens: int = 262_144,
        default_output_tokens: int = 65_536,
        artifact_root: str | Path | None = None,
        artifact_ttl_seconds: int | None = None,
    ):
        self._conversation_repo = conversation_repo
        self._llm_backend = llm_backend
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config
        self._build_context_use_case = build_context_use_case
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._prompt_context_analyzer = prompt_context_analyzer
        self._agent_state_resolver = agent_state_resolver or AgentStateResolver()
        self._command_registry = command_registry or CommandRegistry()
        self._command_service = CommandService(self._command_registry)
        self._session_memory_service = session_memory_service
        self._next_step_suggestion_service = next_step_suggestion_service
        self._session_title_service = session_title_service
        self._recall_memory_use_case = recall_memory_use_case
        self._memory_job_scheduler = memory_job_scheduler
        self._memory_repository = memory_repository
        self._operational_memory_service = operational_memory_service
        self._context_window_tokens = max(4_096, int(context_window_tokens))
        self._default_output_tokens = max(1, int(default_output_tokens))
        self._compactor = ConversationCompactor(
            llm_backend,
            context_window_tokens=self._context_window_tokens,
            default_output_tokens=self._default_output_tokens,
        )
        self._operational_memory = OperationalMemoryCapture(
            memory_service=operational_memory_service,
            job_scheduler=memory_job_scheduler,
            tool_runtime_config=tool_runtime_config,
        )
        self._memory_recall = MemoryRecallCoordinator(
            recall_memory_use_case=recall_memory_use_case,
            memory_repository=memory_repository,
            operational_memory_service=operational_memory_service,
            context_window_tokens=self._context_window_tokens,
        )
        self._prompt_surfaces = PromptSurfacePreparer(
            command_service=self._command_service,
            skill_roots_provider=self._skill_roots,
        )
        self._prompt_package_builder = PromptPackageBuilder(
            prompt_builder=self._prompt_builder,
            prompt_context_analyzer=self._prompt_context_analyzer,
            agent_state_resolver=self._agent_state_resolver,
            command_registry=self._command_registry,
            tool_registry=self._tool_registry,
            session_memory_service=self._session_memory_service,
            skill_roots_provider=self._skill_roots,
        )
        self._tool_results = ToolResultHandler(
            orchestrator_factory=self._new_orchestrator,
            operational_memory=self._operational_memory,
        )
        self._message_preparer = MessagePreparer(
            compactor=self._compactor,
            context_window_tokens=self._context_window_tokens,
        )
        self._tool_context_builder = ToolContextBuilder(
            tool_runtime_config=self._tool_runtime_config,
        )
        self._after_turn = AfterTurnCoordinator(
            conversation_repo=self._conversation_repo,
            next_step_suggestion_service=self._next_step_suggestion_service,
            session_memory_service=self._session_memory_service,
            session_title_service=self._session_title_service,
        )
        self._artifact_root = Path(artifact_root).expanduser() if artifact_root else None
        self._artifact_ttl_seconds = artifact_ttl_seconds if artifact_ttl_seconds and artifact_ttl_seconds > 0 else None
        self._media_policy = MediaPolicyHandler(
            artifact_root=self._artifact_root,
            artifact_ttl_seconds=self._artifact_ttl_seconds,
        )
        self._conversation_lifecycle = ConversationLifecycleHandler(
            conversation_repo=self._conversation_repo,
        )
        self._stream_chunk_normalizer = StreamChunkNormalizer()

    async def execute(self, request: ChatRequestDTO) -> ChatResponseDTO:
        """Execute a synchronous chat completion."""
        conversation = await self._conversation_lifecycle.get_or_create_conversation(request)
        was_empty = len(conversation.messages) == 0

        # Activate plan mode if requested by the frontend (/plan command)
        if request.plan_mode_requested:
            activate_plan_mode_if_requested(conversation.metadata, requested=True)

        context_result = await self._build_context_result(request, conversation)
        preparation = self._prompt_surfaces.prepare(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request, conversation)

        # Adiciona mensagem do usuário
        user_msg = Message(
            role=Role.USER,
            content=request.message,
            metadata=self._prompt_surfaces.user_message_metadata(preparation),
        )
        conversation.add_message(user_msg)

        if not request.tool_context.get("permission_mode"):
            conversation.metadata.pop("permission_mode", None)

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
        await self._operational_memory.capture_user_message(request, context_result, conversation)

        tool_context = self._tool_context_builder.build(request, conversation, preparation) if tools else None
        result = InferenceResult(content="")
        seen_tool_call_ids: set[str] = set()
        effective_max_iterations = self._effective_max_tool_iterations(request)

        try:
            iteration = 0
            while True:
                if iteration >= effective_max_iterations:
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
                result = await self._llm_backend.chat_completion(
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    stream=False,
                    tools=tools,
                    tool_choice="auto" if tools else None,
                    model=request.model,
                    provider=request.provider,
                    reasoning_level=request.reasoning_level,
                    reasoning_budget_tokens=request.reasoning_budget_tokens,
                )
                result = replace(
                    result,
                    images=self._media_policy.store_generated_images(str(conversation.id), result.images),
                )

                assistant_msg = self._conversation_lifecycle.assistant_message_from_result(result, context_metadata)
                if assistant_msg.tool_calls:
                    assistant_msg = Message(
                        role=assistant_msg.role,
                        content=assistant_msg.content,
                        timestamp=assistant_msg.timestamp,
                        tool_calls=self._tool_results.unique_call_ids(
                            assistant_msg.tool_calls,
                            seen_tool_call_ids,
                            iteration,
                        ),
                        tool_call_id=assistant_msg.tool_call_id,
                        metadata=assistant_msg.metadata,
                    )
                conversation.add_message(assistant_msg)

                tool_calls = self._tool_results.parse_calls(assistant_msg.tool_calls)
                if not tool_calls or not tool_context:
                    break

                await self._tool_results.execute(
                    tool_calls,
                    tool_context,
                    conversation,
                )
                iteration += 1
        except LLMBackendError as exc:
            logger.error("llm_backend_error", error=str(exc))
            raise
        except ToolLoopLimitExceededError as exc:
            logger.warning(
                "tool_loop_limit_exceeded",
                conversation_id=str(conversation.id),
                limit=effective_max_iterations,
            )
            conversation.metadata["last_request_error"] = str(exc)
            await self._conversation_repo.update(conversation)
            raise

        # Persiste conversa atualizada
        await self._conversation_repo.update(conversation)

        assistant_msg = conversation.messages[-1]
        await self._operational_memory.capture_assistant_message(
            request,
            context_result,
            conversation,
            result,
        )
        finalized_state = auto_finalize_plan_mode(conversation.metadata, result.content)
        if finalized_state:
            _attach_plan_approval_artifact(conversation, finalized_state)
        await self._after_turn.run_services(
            conversation,
            request,
            finish_reason=result.finish_reason,
        )
        await self._after_turn.refresh_session_title(conversation, was_empty=was_empty)
        # Trigger extração de memória em background
        await self._operational_memory.trigger_memory_extraction(conversation, request)

        await self._conversation_repo.update(conversation)
        return ChatResponseDTO(
            conversation_id=conversation.id,
            message_id=str(assistant_msg.timestamp.timestamp()),
            content=result.content,
            reasoning_content=result.reasoning_content,
            finish_reason=result.finish_reason,
            usage=result.usage,
            model=result.model,
            provider=str(result.metadata.get("provider") or request.provider),
            images=result.images,
            is_streaming=False,
        )

    async def execute_stream(self, request: ChatRequestDTO) -> AsyncIterator[StreamChunk]:
        """Execute a streaming chat completion."""
        conversation = await self._conversation_lifecycle.get_or_create_conversation(request)
        _set_session_status(conversation, "running")
        was_empty = len(conversation.messages) == 0

        # Activate plan mode if requested by the frontend (/plan command)
        if request.plan_mode_requested:
            state = activate_plan_mode_if_requested(conversation.metadata, requested=True)
            if state:
                yield StreamChunk(
                    metadata=plan_mode_event(str(conversation.id), state)
                )

        yield StreamChunk(
            metadata={
                "event": "conversation",
                "conversation_id": str(conversation.id),
                "title": conversation.title,
            }
        )

        async for chunk in self._stream_completion_turn(
            request,
            conversation,
            append_user_message=True,
            was_empty=was_empty,
            status="building_prompt",
        ):
            yield chunk

    async def preview_prompt(self, request: ChatRequestDTO) -> dict[str, Any]:
        """Build the prompt package without creating messages or calling tools."""

        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(request.conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(
                    f"Conversation {request.conversation_id} not found"
                )
        else:
            conversation = Conversation()

        context_result = await self._build_context_result(request, conversation)
        preparation = self._prompt_surfaces.prepare(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request, conversation)
        prompt_package = await self._prompt_package_builder.build(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=[],
        )
        system_prompt = prompt_package.system_prompt or ""
        return {
            "system_prompt": system_prompt,
            "user_context_message": prompt_package.user_context_message,
            "sections": prompt_package.metadata.get("prompt_sections_used") or [],
            "surfaces": prompt_package.metadata.get("prompt_surfaces_used") or [],
            "dynamic_sections": prompt_package.metadata.get("dynamic_sections_used") or [],
            "agent_states": prompt_package.metadata.get("agent_states") or [],
            "agent_state_source": prompt_package.metadata.get("agent_state_source"),
            "agent_state_reason": prompt_package.metadata.get("agent_state_reason"),
            "state_sections_used": prompt_package.metadata.get("state_sections_used") or [],
            "mode": prompt_package.metadata.get("prompt_mode"),
            "requested_mode": prompt_package.metadata.get("requested_prompt_mode"),
            "analysis_source": prompt_package.metadata.get("prompt_analysis_source"),
            "analysis_confidence": prompt_package.metadata.get("prompt_analysis_confidence"),
            "line_count": len(system_prompt.splitlines()),
            "char_count": len(system_prompt),
            "estimated_tokens": prompt_package.metadata.get("prompt_tokens_estimated"),
            "provider_data_boundary": prompt_package.metadata.get("provider_data_boundary"),
            "provider": request.provider,
            "model": request.model,
        }

    async def resume_after_tool_result_stream(
        self,
        request: ChatRequestDTO,
    ) -> AsyncIterator[StreamChunk]:
        """Retoma o loop do modelo depois que um tool_result foi persistido."""
        if request.conversation_id is None:
            raise ConversationNotFoundError("conversation_id is required to resume a tool")
        conversation = await self._conversation_lifecycle.get_or_create_conversation(request)
        _set_session_status(conversation, "running")
        yield StreamChunk(
            metadata={
                "event": "conversation",
                "conversation_id": str(conversation.id),
                "title": conversation.title,
            }
        )

        async for chunk in self._stream_completion_turn(
            request,
            conversation,
            append_user_message=False,
            was_empty=False,
            status="resuming_after_tool_approval",
        ):
            yield chunk

    async def _stream_completion_turn(
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
                self._operational_memory.capture_user_message(request, context_result, conversation),
                task_name="operational_user_capture",
            )

        tool_context = self._tool_context_builder.build(request, conversation, preparation) if tools else None
        final_finish_reason = None
        final_usage = None
        final_model = request.model
        final_provider = request.provider
        seen_tool_call_ids: set[str] = set()
        effective_max_iterations = self._effective_max_tool_iterations(request)

        try:
            iteration = 0
            executed_tools = False
            last_prompt_context_metadata: dict[str, Any] = {}
            while True:
                if iteration >= effective_max_iterations:
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
                last_prompt_context_metadata = context_metadata
                yield StreamChunk(
                    metadata={
                        "event": "prompt_context",
                        **context_metadata,
                    }
                )
                assistant_state = _AssistantStreamState(
                    model=request.model,
                    provider=request.provider,
                    metadata=_context_usage_metadata(context_metadata),
                )

                async for forwarded_chunk in self._stream_assistant_pass(
                    request=request,
                    conversation_id=str(conversation.id),
                    messages=messages,
                    tools=tools,
                    seen_tool_call_ids=seen_tool_call_ids,
                    iteration=iteration,
                    state=assistant_state,
                ):
                    yield forwarded_chunk

                if (
                    executed_tools
                    and not assistant_state.has_visible_output
                    and assistant_state.tool_calls is None
                    and assistant_state.finish_reason in {None, "stop"}
                ):
                    retry_state = _AssistantStreamState(
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
                    async for forwarded_chunk in self._stream_assistant_pass(
                        request=request,
                        conversation_id=str(conversation.id),
                        messages=self._message_preparer.with_final_answer_reminder(messages),
                        tools=[],
                        seen_tool_call_ids=seen_tool_call_ids,
                        iteration=iteration,
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
                        assistant_state = _AssistantStreamState(
                            content_chunks=[notice],
                            reasoning_chunks=list(retry_state.reasoning_chunks),
                            finish_reason="empty_model_response",
                            usage=retry_state.usage,
                            model=retry_state.model or assistant_state.model or request.model,
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

                final_finish_reason = (
                    assistant_state.finish_reason
                    if assistant_state.finish_reason != "tool_calls"
                    else final_finish_reason
                )
                final_usage = assistant_state.usage or final_usage
                final_model = assistant_state.model or final_model
                final_provider = assistant_state.provider or final_provider
                conversation.add_message(
                    Message(
                        role=Role.ASSISTANT,
                        content=assistant_state.content,
                        tool_calls=assistant_state.tool_calls,
                        metadata={
                            "reasoning_content": assistant_state.reasoning_content or None,
                            "finish_reason": assistant_state.finish_reason,
                            "usage": assistant_state.usage,
                            "model": assistant_state.model,
                            "provider": assistant_state.provider,
                            "images": [image.to_dict() for image in assistant_state.images],
                            **_context_usage_metadata(context_metadata),
                            **_context_after_turn_metadata(context_metadata, assistant_state),
                            **assistant_state.metadata,
                        },
                    )
                )

                tool_calls = self._tool_results.parse_calls(assistant_state.tool_calls)
                if not tool_calls or not tool_context:
                    break

                orchestrator = self._new_orchestrator()
                results_by_id: dict[str, ToolResult] = {}
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
                    if event.result is not None and event.event == "permission_required":
                        if self._tool_results.is_user_question(event.result):
                            _set_session_status(conversation, "pending")
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
                            final_finish_reason = "user_input_required"
                        else:
                            _set_session_status(conversation, "pending")
                            metadata.update(
                                self._tool_results.record_pending_approval(
                                    conversation,
                                    event.call,
                                    event.result,
                                    request,
                                )
                            )
                            waiting_for_tool_approval = True
                            final_finish_reason = "permission_required"
                    yield StreamChunk(metadata=metadata)
                    if event.result is not None and self._tool_results.is_plan_approval(event.result):
                        self._tool_results.apply_state(event.result, conversation)
                        state = self._tool_results.plan_state_from(event.result, conversation)
                        _attach_plan_approval_artifact(conversation, state)
                        yield StreamChunk(
                            metadata=plan_mode_event(
                                str(conversation.id),
                                state,
                                event="plan_approval_requested",
                            )
                        )
                        waiting_for_plan_approval = True
                        final_finish_reason = "plan_approval_requested"
                    elif event.result is not None and self._tool_results.is_plan_mode(event.result):
                        self._tool_results.apply_state(event.result, conversation)
                        state = self._tool_results.plan_state_from(event.result, conversation)
                        yield StreamChunk(
                            metadata=plan_mode_event(str(conversation.id), state)
                        )

                for call in tool_calls:
                    result = results_by_id.get(call.id)
                    if result is not None:
                        self._tool_results.apply_state(result, conversation)
                        if result.status != ToolExecutionStatus.PERMISSION_REQUIRED:
                            conversation.add_message(self._tool_results.tool_message_from(result))
                            executed_tools = True
                iteration += 1
                if waiting_for_plan_approval or waiting_for_tool_approval:
                    break

        except LLMBackendError as exc:
            logger.error("llm_backend_stream_error", error=str(exc))
            _set_session_status(conversation, "error")
            conversation.metadata["last_request_error"] = str(exc)
            await self._conversation_repo.update(conversation)
            raise
        except ToolLoopLimitExceededError as exc:
            logger.warning(
                "tool_loop_limit_exceeded_stream",
                conversation_id=str(conversation.id),
                limit=effective_max_iterations,
            )
            _set_session_status(conversation, "error")
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
            final_finish_reason = "tool_loop_limit_exceeded"
            # Fall through to the post-loop cleanup so the UI receives
            # conversation_saved with the final state, instead of leaving the
            # stream half-closed.

        last_assistant = next(
            (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
            None,
        )
        if last_assistant is not None:
            await self._operational_memory.capture_assistant_text(
                request,
                conversation,
                context_result,
                content=last_assistant.content,
                reasoning_content=last_assistant.metadata.get("reasoning_content"),
                finish_reason=final_finish_reason,
                provider=final_provider,
                model=final_model,
            )
            finalized_state = auto_finalize_plan_mode(conversation.metadata, last_assistant.content)
            if finalized_state:
                _attach_plan_approval_artifact(conversation, finalized_state)
                yield StreamChunk(
                    metadata=plan_mode_event(
                        str(conversation.id),
                        finalized_state,
                        event="plan_approval_requested",
                    )
                )
                final_finish_reason = "plan_approval_requested"

        next_step_suggestion = await self._after_turn.run_services(
            conversation,
            request,
            finish_reason=final_finish_reason,
        )
        if next_step_suggestion:
            yield StreamChunk(
                metadata={
                    "event": "next_step_suggestion",
                    "next_step_suggestion": next_step_suggestion,
                    "conversation_id": str(conversation.id),
                }
            )

        _set_session_status(conversation, "idle")
        conversation.metadata.pop("last_request_error", None)
        await self._conversation_repo.update(conversation)

        # Trigger extração de memória em background
        await self._operational_memory.trigger_memory_extraction(conversation, request)

        await self._after_turn.refresh_session_title(conversation, was_empty=was_empty)

        saved_context_metadata = _context_usage_metadata(last_prompt_context_metadata)
        if last_assistant is not None:
            saved_context_metadata.update(
                _context_usage_metadata(last_assistant.metadata or {})
            )
            after_turn_tokens = _optional_int(
                (last_assistant.metadata or {}).get("context_tokens_after_turn_estimated")
            )
            if after_turn_tokens is not None:
                saved_context_metadata["context_tokens_after_turn_estimated"] = after_turn_tokens

        yield StreamChunk(
            metadata={
                "event": "conversation_saved",
                "conversation_id": str(conversation.id),
                "title": conversation.title,
                "finish_reason": final_finish_reason,
                "usage": final_usage,
                "model": final_model,
                "provider": final_provider,
                "next_step_suggestion": next_step_suggestion,
                **saved_context_metadata,
            }
        )



    async def _stream_assistant_pass(
        self,
        *,
        request: ChatRequestDTO,
        conversation_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        seen_tool_call_ids: set[str],
        iteration: int,
        state: _AssistantStreamState,
    ) -> AsyncIterator[StreamChunk]:
        async for chunk in self._llm_backend.chat_completion_stream(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=tools,
            tool_choice="auto" if tools else None,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
        ):
            chunk = self._stream_chunk_normalizer.normalize_provider_stream_chunk(request, state, chunk)
            if chunk.images:
                chunk = replace(
                    chunk,
                    images=self._media_policy.store_generated_images(conversation_id, chunk.images),
                )
            chunk_metadata = {
                "provider": request.provider,
                "model": request.model,
                **chunk.metadata,
            }
            if chunk.content:
                state.content_chunks.append(chunk.content)
            if chunk.reasoning_content:
                state.reasoning_chunks.append(chunk.reasoning_content)
            if chunk.images:
                state.images.extend(chunk.images)
            if chunk.tool_calls:
                state.tool_calls = self._tool_results.unique_call_ids(
                    chunk.tool_calls,
                    seen_tool_call_ids,
                    iteration,
                )
                state.finish_reason = "tool_calls"
            state.metadata.update(
                {
                    key: value
                    for key, value in chunk_metadata.items()
                    if key.startswith(("vertex_", "kimi_", "zenmux_", "deepseek_"))
                }
            )
            if chunk.finish_reason:
                internal_tool_stop = (
                    state.tool_calls is not None
                    and chunk.finish_reason != "tool_calls"
                    and not chunk.content
                    and not chunk.reasoning_content
                    and not chunk.images
                )
                if not internal_tool_stop:
                    state.finish_reason = chunk.finish_reason
            if chunk.usage:
                state.usage = chunk.usage
            state.model = str(chunk_metadata.get("model") or request.model)
            state.provider = str(chunk_metadata.get("provider") or request.provider)
            forwarded_finish_reason = self._tool_results.forwarded_finish_reason(
                chunk,
                has_pending_tool_calls=state.tool_calls is not None,
            )
            if (
                chunk.content
                or chunk.reasoning_content
                or chunk.images
                or forwarded_finish_reason
            ):
                yield StreamChunk(
                    content=chunk.content,
                    reasoning_content=chunk.reasoning_content,
                    finish_reason=forwarded_finish_reason,
                    usage=chunk.usage,
                    images=chunk.images,
                    is_thinking=chunk.is_thinking,
                    metadata=chunk_metadata,
                )

    def _resolve_tool_schemas(
        self,
        request: ChatRequestDTO,
        conversation: Conversation | None = None,
    ) -> list[dict[str, Any]]:
        if not request.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        schemas = cast(
            list[dict[str, Any]],
            self._tool_registry.openai_schemas(
                allowed_tools=allowed_tools,
                cache_scope=f"{request.provider}:{request.model}",
            ),
        )
        # Conditionally filter planning tools based on conversation plan mode state
        if conversation is not None:
            plan_active = is_plan_mode_active(conversation.metadata)
            filtered: list[dict[str, Any]] = []
            for schema in schemas:
                function = schema.get("function") if isinstance(schema, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                if name == "ExitPlanMode" and not plan_active:
                    continue
                if name == "EnterPlanMode" and plan_active:
                    continue
                filtered.append(schema)
            return filtered
        return schemas

    def _skill_roots(self) -> tuple[str | Path, ...]:
        if self._tool_runtime_config is None:
            return ()
        return tuple(str(path) for path in self._tool_runtime_config.skill_roots)

    def _new_orchestrator(self) -> ToolOrchestrator:
        if self._tool_registry is None or self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")
        return ToolOrchestrator(self._tool_registry, self._tool_runtime_config)

    def _effective_max_tool_iterations(self, request: ChatRequestDTO) -> int:
        """Return the bounded tool-iteration cap for the current chat turn.

        See ``resolve_effective_tool_iterations`` for the precedence rules.
        """

        config_max = (
            self._tool_runtime_config.max_tool_iterations
            if self._tool_runtime_config is not None
            else None
        )
        return int(
            resolve_effective_tool_iterations(
                request_max=request.max_tool_iterations,
                config_max=config_max,
            )
        )

    def _tool_iteration_limit_source(self, request: ChatRequestDTO) -> str:
        """Describe which input determined the active tool-iteration cap."""

        if request.max_tool_iterations is not None:
            return "request"
        config_max = (
            self._tool_runtime_config.max_tool_iterations
            if self._tool_runtime_config is not None
            else None
        )
        if config_max is not None:
            return "runtime_config"
        return "safety_ceiling"

    def _schedule_background(self, coro: Awaitable[Any], *, task_name: str) -> None:
        task = asyncio.create_task(coro, name=task_name)

        def _log_failure(done: asyncio.Task) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("background_task_failed", task_name=task_name, exc_info=True)

        task.add_done_callback(_log_failure)

    async def _build_context_result(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
    ) -> ContextBuildResult:
        if self._build_context_use_case:
            try:
                return await self._build_context_use_case.execute(
                    conversation_id=str(conversation.id),
                    use_cache=True,
                )
            except Exception:
                logger.warning("context_build_failed", exc_info=True)

        workspace_root = self._operational_memory.resolve_workspace_root(request)
        return ContextBuildResult(
            system_context=SystemContext(
                workspace_root=str(workspace_root),
                cwd=str(workspace_root),
            ),
            user_context=UserContext(current_date=datetime.now(UTC).strftime("%Y-%m-%d")),
            build_duration_ms=0,
            metadata={"source": "fallback"},
        )




