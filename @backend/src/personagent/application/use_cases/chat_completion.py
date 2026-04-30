"""Caso de uso: Chat Completion."""

import asyncio
import base64
import binascii
import json
import re
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

from personagent.application.dto.chat_dto import ChatRequestDTO, ChatResponseDTO
from personagent.application.jobs.memory_job import JobType, MemoryJob
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
    is_plan_mode_active,
    new_tool_approval_id,
    normalize_plan_state,
    now_iso,
    plan_mode_event,
    write_plan_state,
)
from personagent.application.security.provider_data_policy import enforce_provider_data_policy
from personagent.application.services import (
    NextStepSuggestionService,
    OperationalMemoryService,
    SessionMemoryService,
    SessionTitleService,
)
from personagent.application.services.browser_cooperation import (
    attach_browser_action_proposal,
    browser_agent_context_reminder,
    shared_browser_workspace_reminder,
)
from personagent.application.services.operational_memory import project_slug_from_workspace
from personagent.application.state.services import StateManager
from personagent.application.tools import (
    ToolOrchestrator,
    ToolRegistry,
    ToolRuntimeConfig,
)
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
from personagent.domain.context.models import ContextBuildResult, SystemContext, UserContext
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    LLMBackendError,
)
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_formatter import MemoryFormatter
from personagent.domain.memory.services.memory_trace import MemoryTraceBuilder
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import GeneratedImage, InferenceResult, StreamChunk
from personagent.domain.prompts.commands import (
    CommandRegistry,
    CommandService,
    SlashCommandResolution,
    parse_slash_invocation,
)
from personagent.domain.prompts.compact import BASE_COMPACT_PROMPT
from personagent.domain.prompts.context_attachments import resolve_context_attachments
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.prompts.services.agent_state_resolver import AgentStateResolver
from personagent.domain.prompts.services.prompt_builder import estimate_text_tokens
from personagent.domain.prompts.skills import (
    SkillDefinition,
    discover_enabled_skills,
    find_skill,
    is_skill_enabled,
)
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolResult,
    ToolUseContext,
)
from personagent.infrastructure.artifacts import store_bytes_artifact
from personagent.interfaces.api.action_approvals import canonical_args_hash

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class _PromptPackage:
    system_prompt: str | None
    user_context_message: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class _MemoryRecallResult:
    prompt_memories: list[str] = field(default_factory=list)
    trace: dict[str, Any] | None = None


@dataclass(slots=True)
class _PromptPreparation:
    request: ChatRequestDTO
    slash_reminder: str | None = None
    slash_metadata: dict[str, Any] | None = None
    context_reminders: list[str] = field(default_factory=list)
    context_attachment_metadata: list[dict[str, Any]] = field(default_factory=list)
    browser_target: dict[str, Any] | None = None


@dataclass(slots=True)
class _AssistantStreamState:
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
        self._artifact_root = Path(artifact_root).expanduser() if artifact_root else None
        self._artifact_ttl_seconds = artifact_ttl_seconds if artifact_ttl_seconds and artifact_ttl_seconds > 0 else None
        self._state_manager = StateManager.get_instance()

    async def execute(self, request: ChatRequestDTO) -> ChatResponseDTO:
        """Execute a synchronous chat completion."""
        conversation = await self._get_or_create_conversation(request)
        was_empty = len(conversation.messages) == 0

        context_result = await self._build_context_result(request, conversation)
        preparation = self._prepare_prompt_surfaces(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request)

        # Adiciona mensagem do usuário
        user_msg = Message(
            role=Role.USER,
            content=request.message,
            metadata=self._user_message_metadata(preparation),
        )
        conversation.add_message(user_msg)

        # Recall memórias relevantes
        memory_recall = await self._recall_relevant_memories(
            request, context_result, conversation
        )

        prompt_package = await self._build_prompt_package(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=memory_recall.prompt_memories,
            memory_trace=memory_recall.trace,
        )
        self._enforce_provider_data_policy(request, prompt_package)
        await self._capture_operational_user_message(request, context_result, conversation)

        tool_context = self._build_tool_context(request, conversation, preparation) if tools else None
        result = InferenceResult(content="")
        seen_tool_call_ids: set[str] = set()

        try:
            iteration = 0
            while True:
                messages, context_metadata = await self._prepare_messages_for_llm(
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
                    images=self._store_generated_images(str(conversation.id), result.images),
                )

                assistant_msg = self._assistant_message_from_result(result, context_metadata)
                if assistant_msg.tool_calls:
                    assistant_msg = Message(
                        role=assistant_msg.role,
                        content=assistant_msg.content,
                        timestamp=assistant_msg.timestamp,
                        tool_calls=self._unique_tool_call_ids(
                            assistant_msg.tool_calls,
                            seen_tool_call_ids,
                            iteration,
                        ),
                        tool_call_id=assistant_msg.tool_call_id,
                        metadata=assistant_msg.metadata,
                    )
                conversation.add_message(assistant_msg)

                tool_calls = self._parse_tool_calls(assistant_msg.tool_calls)
                if not tool_calls or not tool_context:
                    break

                await self._execute_tools_into_conversation(
                    tool_calls,
                    tool_context,
                    conversation,
                )
                iteration += 1
        except LLMBackendError as exc:
            logger.error("llm_backend_error", error=str(exc))
            raise

        # Persiste conversa atualizada
        await self._conversation_repo.update(conversation)

        assistant_msg = conversation.messages[-1]
        await self._capture_operational_assistant_message(
            request,
            context_result,
            conversation,
            result,
        )
        await self._after_turn_services(
            conversation,
            request,
            finish_reason=result.finish_reason,
        )
        await self._refresh_session_title(conversation, was_empty=was_empty)
        # Trigger extração de memória em background
        await self._trigger_memory_extraction(conversation, request)

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
        conversation = await self._get_or_create_conversation(request)
        _set_session_status(conversation, "running")
        was_empty = len(conversation.messages) == 0
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
        preparation = self._prepare_prompt_surfaces(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request)
        prompt_package = await self._build_prompt_package(
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
        conversation = await self._get_or_create_conversation(request)
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
        preparation = self._prepare_prompt_surfaces(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request)

        if append_user_message:
            user_msg = Message(
                role=Role.USER,
                content=request.message,
                metadata=self._user_message_metadata(preparation),
            )
            conversation.add_message(user_msg)

        # Emite status para o frontend saber que está montando o prompt
        yield StreamChunk(metadata={"event": "status", "status": status})

        # Recall memórias relevantes
        memory_recall = await self._recall_relevant_memories(
            request, context_result, conversation
        )

        prompt_package = await self._build_prompt_package(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=memory_recall.prompt_memories,
            memory_trace=memory_recall.trace,
        )
        self._enforce_provider_data_policy(request, prompt_package)
        if append_user_message:
            self._schedule_background(
                self._capture_operational_user_message(request, context_result, conversation),
                task_name="operational_user_capture",
            )

        tool_context = self._build_tool_context(request, conversation, preparation) if tools else None
        final_finish_reason = None
        final_usage = None
        final_model = request.model
        final_provider = request.provider
        seen_tool_call_ids: set[str] = set()

        try:
            iteration = 0
            executed_tools = False
            last_prompt_context_metadata: dict[str, Any] = {}
            while True:
                messages, context_metadata = await self._prepare_messages_for_llm(
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
                        messages=self._messages_with_final_answer_reminder(messages),
                        tools=[],
                        seen_tool_call_ids=seen_tool_call_ids,
                        iteration=iteration,
                        state=retry_state,
                    ):
                        yield forwarded_chunk
                    if retry_state.has_visible_output or retry_state.tool_calls:
                        assistant_state = retry_state
                    else:
                        notice = self._empty_model_response_notice(
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

                tool_calls = self._parse_tool_calls(assistant_state.tool_calls)
                if not tool_calls or not tool_context:
                    break

                orchestrator = self._new_orchestrator()
                results_by_id: dict[str, ToolResult] = {}
                waiting_for_plan_approval = False
                waiting_for_tool_approval = False
                async for event in orchestrator.execute(tool_calls, tool_context):
                    if event.result is not None:
                        results_by_id[event.call.id] = event.result
                        await self._capture_operational_tool_result(
                            request,
                            conversation,
                            event.call,
                            event.result,
                            tool_context,
                        )
                    metadata = event.to_stream_metadata()
                    if event.result is not None and event.event == "permission_required":
                        if self._is_user_question_result(event.result):
                            _set_session_status(conversation, "pending")
                            metadata.update(
                                self._record_pending_user_question(
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
                                self._record_pending_tool_approval(
                                    conversation,
                                    event.call,
                                    event.result,
                                    request,
                                )
                            )
                            waiting_for_tool_approval = True
                            final_finish_reason = "permission_required"
                    yield StreamChunk(metadata=metadata)
                    if event.result is not None and self._is_plan_approval_result(event.result):
                        self._apply_tool_state_result(event.result, conversation)
                        state = self._plan_state_from_result(event.result, conversation)
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
                    elif event.result is not None and self._is_plan_mode_result(event.result):
                        self._apply_tool_state_result(event.result, conversation)
                        state = self._plan_state_from_result(event.result, conversation)
                        yield StreamChunk(
                            metadata=plan_mode_event(str(conversation.id), state)
                        )

                for call in tool_calls:
                    result = results_by_id.get(call.id)
                    if result is not None:
                        self._apply_tool_state_result(result, conversation)
                        if result.status != ToolExecutionStatus.PERMISSION_REQUIRED:
                            conversation.add_message(self._tool_message_from_result(result))
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

        next_step_suggestion = await self._after_turn_services(
            conversation,
            request,
            finish_reason=final_finish_reason,
        )
        last_assistant = next(
            (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
            None,
        )
        if last_assistant is not None:
            await self._capture_operational_assistant_text(
                request,
                conversation,
                context_result,
                content=last_assistant.content,
                reasoning_content=last_assistant.metadata.get("reasoning_content"),
                finish_reason=final_finish_reason,
                provider=final_provider,
                model=final_model,
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
        await self._trigger_memory_extraction(conversation, request)

        await self._refresh_session_title(conversation, was_empty=was_empty)

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

    async def _get_or_create_conversation(self, request: ChatRequestDTO) -> Conversation:
        """Retrieve or create a conversation from the request."""
        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(request.conversation_id)
            if not conversation:
                raise ConversationNotFoundError(
                    f"Conversation {request.conversation_id} not found"
                )
            _apply_workspace_metadata(conversation, request.tool_context)
            return conversation

        # Create a new conversation
        conversation = Conversation()
        _apply_workspace_metadata(conversation, request.tool_context)
        await self._conversation_repo.create(conversation)
        return conversation

    def _assistant_message_from_result(
        self,
        result: InferenceResult,
        context_metadata: dict[str, Any] | None = None,
    ) -> Message:
        return Message(
            role=Role.ASSISTANT,
            content=result.content,
            tool_calls=result.tool_calls,
            metadata={
                "usage": result.usage,
                "model": result.model,
                "reasoning_content": result.reasoning_content or None,
                "finish_reason": result.finish_reason,
                "images": [image.to_dict() for image in result.images],
                **_context_usage_metadata(context_metadata or {}),
                **result.metadata,
            },
        )

    def _enforce_provider_data_policy(
        self,
        request: ChatRequestDTO,
        prompt_package: _PromptPackage,
    ) -> None:
        result = enforce_provider_data_policy(
            request=request,
            system_prompt=prompt_package.system_prompt,
            user_context_message=prompt_package.user_context_message,
        )
        prompt_package.metadata["provider_data_policy"] = result.policy
        prompt_package.metadata["provider_data_policy_findings"] = result.findings

    def _store_generated_images(
        self,
        conversation_id: str,
        images: list[GeneratedImage],
    ) -> list[GeneratedImage]:
        stored: list[GeneratedImage] = []
        for image in images:
            if image.url or image.artifact_id or not image.data:
                stored.append(image)
                continue
            try:
                raw = base64.b64decode(image.data, validate=True)
            except (binascii.Error, ValueError):
                stored.append(image)
                continue
            mime_type = image.mime_type or "image/png"
            artifact = store_bytes_artifact(
                category="generated-images",
                conversation_id=conversation_id,
                content=raw,
                suffix=_image_suffix(mime_type),
                mime_type=mime_type,
                root=self._artifact_root,
                ttl_seconds=self._artifact_ttl_seconds,
            )
            stored.append(
                GeneratedImage(
                    mime_type=mime_type,
                    alt=image.alt,
                    artifact_id=artifact.artifact_id,
                    url=artifact.url,
                    size_bytes=artifact.size_bytes,
                    sha256=artifact.sha256,
                )
            )
        return stored

    def _tool_message_from_result(self, result: ToolResult) -> Message:
        return Message(
            role=Role.TOOL,
            content=result.content,
            tool_call_id=result.tool_call_id,
            metadata={
                "tool_name": result.tool_name,
                "status": result.status.value,
                "is_error": result.is_error,
                "data": result.data,
                **result.metadata,
            },
        )

    async def _execute_tools_into_conversation(
        self,
        tool_calls: list[ToolCall],
        tool_context: ToolUseContext,
        conversation: Conversation,
    ) -> None:
        orchestrator = self._new_orchestrator()
        results = await orchestrator.execute_collect(tool_calls, tool_context)
        calls_by_id = {call.id: call for call in tool_calls}
        for result in results:
            call = calls_by_id.get(result.tool_call_id)
            if call is not None:
                await self._capture_operational_tool_result(
                    None,
                    conversation,
                    call,
                    result,
                    tool_context,
                )
            self._apply_tool_state_result(result, conversation)
            if result.status != ToolExecutionStatus.PERMISSION_REQUIRED:
                conversation.add_message(self._tool_message_from_result(result))

    def _apply_tool_state_result(self, result: ToolResult, conversation: Conversation) -> None:
        result_type = result.data.get("type")
        if result_type == "plan_mode":
            state = result.data.get("state")
            if not isinstance(state, dict):
                state = normalize_plan_state(conversation.metadata)
                state.update(
                    {
                        "active": bool(result.data.get("active")),
                        "status": result.data.get("status")
                        or ("draft" if result.data.get("active") else "inactive"),
                        "plan_id": result.data.get("plan_id") or state.get("plan_id"),
                        "plan_content": result.data.get("plan_content")
                        or state.get("plan_content")
                        or "",
                        "approval_id": result.data.get("approval_id"),
                        "feedback": result.data.get("feedback"),
                        "cancelled": bool(result.data.get("cancelled", False)),
                    }
                )
            write_plan_state(conversation.metadata, state)
        if result_type == "todos":
            conversation.metadata["todos"] = result.data.get("todos", [])

    def _is_plan_mode_result(self, result: ToolResult) -> bool:
        return result.data.get("type") == "plan_mode"

    def _is_plan_approval_result(self, result: ToolResult) -> bool:
        return (
            self._is_plan_mode_result(result)
            and result.data.get("action") == "request_approval"
        )

    def _is_user_question_result(self, result: ToolResult) -> bool:
        return result.data.get("type") == "ask_user_question"

    def _plan_state_from_result(
        self,
        result: ToolResult,
        conversation: Conversation,
    ) -> dict[str, Any]:
        state = result.data.get("state")
        if isinstance(state, dict):
            return normalize_plan_state({"plan_mode": state})
        return normalize_plan_state(conversation.metadata)

    def _record_pending_tool_approval(
        self,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        request: ChatRequestDTO,
    ) -> dict[str, Any]:
        existing = conversation.metadata.get(PENDING_TOOL_APPROVAL_KEY)
        approval_id = (
            str(existing.get("approval_id"))
            if isinstance(existing, dict) and existing.get("tool_call_id") == call.id
            else new_tool_approval_id()
        )
        args_hash = canonical_args_hash(
            "chat.tool_approval",
            {
                "tool_call_id": call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
            },
        )
        pending = {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
            "args_hash": args_hash,
            "status": "awaiting_approval",
            "tool_call_id": call.id,
            "tool_name": call.name,
            "arguments": call.arguments,
            "message": result.content,
            "tool_context": request.tool_context,
            "resume_request": {
                "message": request.message,
                "system_prompt": request.system_prompt,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "provider": request.provider,
                "model": request.model,
                "prompt_mode": request.prompt_mode,
                "reasoning_level": request.reasoning_level,
                "reasoning_budget_tokens": request.reasoning_budget_tokens,
                "tools_enabled": request.tools_enabled,
                "allowed_tools": request.allowed_tools,
                "tool_context": request.tool_context,
                "max_tool_iterations": request.max_tool_iterations,
                "context_attachments": request.context_attachments,
            },
            "created_at": now_iso(),
        }
        conversation.metadata[PENDING_TOOL_APPROVAL_KEY] = pending
        arbiter_metadata = result.metadata.get("browser_action_arbiter") if isinstance(result.metadata, dict) else None
        if isinstance(arbiter_metadata, dict):
            attach_browser_action_proposal(
                conversation.metadata,
                pending=pending,
                arbiter_metadata=arbiter_metadata,
                message=result.content,
            )
        return {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
            "args_hash": args_hash,
            "tool_approval": pending,
        }

    def _record_pending_user_question(
        self,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        request: ChatRequestDTO,
    ) -> dict[str, Any]:
        approval_id = str(result.data.get("approval_id") or new_tool_approval_id())
        pending = {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
            "status": "awaiting_answer",
            "tool_call_id": call.id,
            "tool_name": call.name,
            "arguments": call.arguments,
            "questions": result.data.get("questions") or [],
            "title": result.data.get("title") or "User input requested",
            "resume_request": {
                "message": request.message,
                "system_prompt": request.system_prompt,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "provider": request.provider,
                "model": request.model,
                "prompt_mode": request.prompt_mode,
                "reasoning_level": request.reasoning_level,
                "reasoning_budget_tokens": request.reasoning_budget_tokens,
                "tools_enabled": request.tools_enabled,
                "allowed_tools": request.allowed_tools,
                "tool_context": request.tool_context,
                "max_tool_iterations": request.max_tool_iterations,
                "context_attachments": request.context_attachments,
            },
            "created_at": now_iso(),
        }
        conversation.metadata[PENDING_USER_QUESTION_KEY] = pending
        return {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
            "user_question": pending,
            "questions": pending["questions"],
            "question_title": pending["title"],
        }

    def _parse_tool_calls(self, tool_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
        if not tool_calls:
            return []
        calls = [ToolCall.from_openai(call) for call in tool_calls]
        return [call for call in calls if call.id and call.name]

    def _unique_tool_call_ids(
        self,
        tool_calls: list[dict[str, Any]],
        seen_ids: set[str],
        iteration: int,
    ) -> list[dict[str, Any]]:
        """Keep provider-emitted tool ids stable enough for UI and tool responses."""
        unique_calls: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls):
            original_id = str(tool_call.get("id") or "").strip()
            candidate = original_id or f"tool-call-{iteration}-{index}"
            if candidate in seen_ids:
                base = candidate
                suffix = 2
                candidate = f"{base}-{iteration}-{index}"
                while candidate in seen_ids:
                    suffix += 1
                    candidate = f"{base}-{iteration}-{index}-{suffix}"
            seen_ids.add(candidate)
            if candidate == original_id:
                unique_calls.append(tool_call)
                continue
            next_call = dict(tool_call)
            next_call["id"] = candidate
            extra = next_call.get("extra_content")
            next_extra = dict(extra) if isinstance(extra, dict) else {}
            next_extra["original_tool_call_id"] = original_id or None
            next_call["extra_content"] = next_extra
            unique_calls.append(next_call)
        return unique_calls

    def _forwarded_finish_reason(
        self,
        chunk: StreamChunk,
        *,
        has_pending_tool_calls: bool,
    ) -> str | None:
        if chunk.finish_reason == "tool_calls":
            return None
        if (
            has_pending_tool_calls
            and chunk.finish_reason
            and not chunk.content
            and not chunk.reasoning_content
            and not chunk.images
        ):
            return None
        return chunk.finish_reason

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
            chunk = self._normalize_provider_stream_chunk(request, state, chunk)
            if chunk.images:
                chunk = replace(
                    chunk,
                    images=self._store_generated_images(conversation_id, chunk.images),
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
                state.tool_calls = self._unique_tool_call_ids(
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
            forwarded_finish_reason = self._forwarded_finish_reason(
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

    def _normalize_provider_stream_chunk(
        self,
        request: ChatRequestDTO,
        state: _AssistantStreamState,
        chunk: StreamChunk,
    ) -> StreamChunk:
        if (
            request.provider != "deepseek"
            or not state.content
            or not chunk.reasoning_content
            or chunk.content
            or chunk.tool_calls
            or chunk.images
        ):
            return chunk
        return replace(
            chunk,
            content=chunk.reasoning_content,
            reasoning_content="",
            is_thinking=False,
            metadata={
                **chunk.metadata,
                "deepseek_reasoning_rerouted_to_content": True,
            },
        )

    def _messages_with_final_answer_reminder(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        reminder = (
            "The previous provider pass stopped after tool results without a visible "
            "final answer. Use the tool results already present in the conversation "
            "and respond now with the final answer. Do not call more tools for this "
            "recovery pass."
        )
        if messages and messages[0].get("role") == "system":
            updated = dict(messages[0])
            updated["content"] = f"{updated.get('content') or ''}\n\n{reminder}"
            return [updated, *messages[1:]]
        return [
            {"role": "system", "content": reminder},
            *messages,
        ]

    def _empty_model_response_notice(self, *, provider: str, model: str) -> str:
        return (
            "The model stopped after tool execution without producing a visible final "
            f"answer. Provider: {provider}; model: {model}. The tool results were preserved, "
            "but the provider returned an empty terminal response."
        )

    def _prepare_prompt_surfaces(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
    ) -> _PromptPreparation:
        workspace_root = context_result.system_context.workspace_root
        context_cwd = context_result.system_context.cwd or workspace_root
        attachment_context = resolve_context_attachments(
            request.context_attachments,
            workspace_root=workspace_root,
            cwd=context_cwd,
            extra_skill_roots=self._skill_roots(),
        )
        parsed = parse_slash_invocation(request.message)
        if parsed is None:
            return _PromptPreparation(
                request=request,
                context_reminders=attachment_context.reminders,
                context_attachment_metadata=attachment_context.metadata,
                browser_target=_browser_target_from_context_attachments(attachment_context.metadata),
            )

        resolution = self._command_service.resolve_prompt_command(request.message, workspace_root)
        if resolution is not None:
            return self._with_context_attachments(
                self._preparation_from_command(request, resolution),
                attachment_context.reminders,
                attachment_context.metadata,
            )

        skill = find_skill(
            parsed[0],
            workspace_root=workspace_root,
            cwd=context_result.system_context.cwd or workspace_root,
            extra_roots=self._skill_roots(),
        )
        if skill is not None:
            if not is_skill_enabled(
                skill,
                workspace_root=workspace_root,
                cwd=context_result.system_context.cwd or workspace_root,
                extra_roots=self._skill_roots(),
            ):
                raise ValueError(f"Skill is disabled: /{parsed[0]}")
            if skill.user_invocable:
                return self._with_context_attachments(
                    self._preparation_from_skill(request, skill, parsed[1]),
                    attachment_context.reminders,
                    attachment_context.metadata,
                )

        builtin = self._command_service.resolve_builtin(request.message)
        if builtin is not None:
            return self._with_context_attachments(
                self._preparation_from_builtin(request, builtin),
                attachment_context.reminders,
                attachment_context.metadata,
            )

        raise ValueError(f"Unknown slash command: /{parsed[0]}")

    def _preparation_from_command(
        self,
        request: ChatRequestDTO,
        resolution: SlashCommandResolution,
    ) -> _PromptPreparation:
        command = resolution.command
        prepared = self._apply_prompt_surface_overrides(
            request,
            allowed_tools=command.allowed_tools,
            model=command.model,
            effort=command.effort,
        )
        return _PromptPreparation(
            request=prepared,
            slash_reminder=resolution.reminder(),
            slash_metadata=resolution.metadata(),
        )

    def _preparation_from_builtin(
        self,
        request: ChatRequestDTO,
        resolution: Any,
    ) -> _PromptPreparation:
        command = resolution.command
        prepared = self._apply_prompt_surface_overrides(
            request,
            allowed_tools=command.allowed_tools,
            model=command.model,
            effort=command.effort,
        )
        metadata = resolution.metadata()
        metadata["source"] = "builtin"
        return _PromptPreparation(
            request=prepared,
            slash_reminder=resolution.reminder(),
            slash_metadata=metadata,
        )

    def _preparation_from_skill(
        self,
        request: ChatRequestDTO,
        skill: SkillDefinition,
        raw_arguments: str,
    ) -> _PromptPreparation:
        prepared = self._apply_prompt_surface_overrides(
            request,
            allowed_tools=skill.allowed_tools,
            model=skill.model,
            effort=None,
        )
        reminder = (
            "# Slash Skill Context\n\n"
            f"Skill: {skill.slash_name}\n"
            f"Arguments: {raw_arguments or '(none)'}\n"
            f"Source: {skill.path}\n\n"
            "The user invoked a user-invocable skill. Treat the skill body below as "
            "procedural guidance for this turn and load additional resources only when needed.\n\n"
            f"{skill.body.strip()}"
        )
        metadata = skill.to_inventory_dict()
        metadata["arguments"] = raw_arguments
        return _PromptPreparation(
            request=prepared,
            slash_reminder=reminder,
            slash_metadata=metadata,
        )

    def _with_context_attachments(
        self,
        preparation: _PromptPreparation,
        reminders: list[str],
        metadata: list[dict[str, Any]],
    ) -> _PromptPreparation:
        preparation.context_reminders = list(preparation.context_reminders) + list(reminders)
        preparation.context_attachment_metadata = list(metadata)
        preparation.browser_target = _browser_target_from_context_attachments(metadata)
        return preparation

    def _user_message_metadata(self, preparation: _PromptPreparation) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if preparation.slash_metadata:
            metadata["slash_command"] = preparation.slash_metadata
        if preparation.context_attachment_metadata:
            metadata["context_attachments"] = preparation.context_attachment_metadata
        return metadata

    def _apply_prompt_surface_overrides(
        self,
        request: ChatRequestDTO,
        *,
        allowed_tools: tuple[str, ...] = (),
        model: str | None = None,
        effort: str | None = None,
    ) -> ChatRequestDTO:
        next_allowed_tools = request.allowed_tools
        if allowed_tools:
            if "*" in allowed_tools:
                next_allowed_tools = None
            elif next_allowed_tools:
                next_allowed_tools = sorted(set(next_allowed_tools).union(allowed_tools))
            else:
                next_allowed_tools = list(allowed_tools)

        normalized_effort = (effort or "").strip().lower()
        next_reasoning_level = request.reasoning_level
        if normalized_effort in {"low", "medium", "high", "xhigh", "max"}:
            next_reasoning_level = normalized_effort

        next_model = request.model
        if model and model.strip() and model.strip().lower() != "inherit":
            next_model = model.strip()

        if (
            next_allowed_tools == request.allowed_tools
            and next_reasoning_level == request.reasoning_level
            and next_model == request.model
        ):
            return request
        return replace(
            request,
            allowed_tools=next_allowed_tools,
            reasoning_level=next_reasoning_level,
            model=next_model,
        )

    async def _analyze_prompt_profile(
        self,
        request: ChatRequestDTO,
        *,
        available_tools: list[str],
        workspace_root: str,
        context_size_chars: int = 0,
        conversation_message_count: int = 0,
    ):
        if request.provider in {"llama", "zenmux"} and request.prompt_mode == "auto":
            from personagent.domain.prompts.services.context_analyzer import fallback_prompt_profile

            return fallback_prompt_profile(
                message=request.message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                reason=f"{request.provider}_auto_prompt_analysis_skipped",
            )
        if self._prompt_context_analyzer is None:
            from personagent.domain.prompts.services.context_analyzer import fallback_prompt_profile

            if request.prompt_mode != "auto":
                return await PromptContextAnalyzer(None).analyze(
                    message=request.message,
                    requested_mode=request.prompt_mode,
                    available_tools=available_tools,
                    workspace_root=workspace_root,
                    model=request.model,
                    provider=request.provider,
                    context_size_chars=context_size_chars,
                    conversation_message_count=conversation_message_count,
                )
            return fallback_prompt_profile()
        return await self._prompt_context_analyzer.analyze(
            message=request.message,
            requested_mode=request.prompt_mode,
            available_tools=available_tools,
            workspace_root=workspace_root,
            model=request.model,
            provider=request.provider,
            context_size_chars=context_size_chars,
            conversation_message_count=conversation_message_count,
        )

    def _resolve_tool_schemas(self, request: ChatRequestDTO) -> list[dict[str, Any]]:
        if not request.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        return cast(
            list[dict[str, Any]],
            self._tool_registry.openai_schemas(
                allowed_tools=allowed_tools,
                cache_scope=f"{request.provider}:{request.model}",
            ),
        )

    def _prompt_tool_definitions(self, request: ChatRequestDTO) -> list[ToolDefinition]:
        if not request.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        return [
            tool.definition
            for tool in self._tool_registry.list_enabled(allowed_tools, include_deferred=True)
        ]

    def _skill_inventory(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
    ) -> list[SkillDefinition]:
        workspace_root = context_result.system_context.workspace_root
        cwd = context_result.system_context.cwd or workspace_root
        return discover_enabled_skills(
            workspace_root=workspace_root,
            cwd=cwd,
            extra_roots=self._skill_roots(),
        )

    def _skill_roots(self) -> tuple[str | Path, ...]:
        if self._tool_runtime_config is None:
            return ()
        return tuple(str(path) for path in self._tool_runtime_config.skill_roots)

    def _new_orchestrator(self) -> ToolOrchestrator:
        if self._tool_registry is None or self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")
        return ToolOrchestrator(self._tool_registry, self._tool_runtime_config)

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

        workspace_root = self._prompt_workspace_root(request)
        return ContextBuildResult(
            system_context=SystemContext(
                workspace_root=str(workspace_root),
                cwd=str(workspace_root),
            ),
            user_context=UserContext(current_date=datetime.now(UTC).strftime("%Y-%m-%d")),
            build_duration_ms=0,
            metadata={"source": "fallback"},
        )

    async def _recall_relevant_memories(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
    ) -> _MemoryRecallResult:
        """Execute relevant-memory recall for the current query.

        Args:
            request: Chat request DTO.
            context_result: Build context result.
            conversation: Current conversation, used to track already_surfaced.

        Returns:
            Prompt memories plus a UI trace of selected memory sources.
        """
        workspace_root = context_result.system_context.workspace_root
        project_slug = self._sanitize_project_slug(workspace_root)
        formatted_memories: list[str] = []
        classic_memories = []
        operational_package = None
        conversation.metadata.pop("_operational_memory_prompt", None)

        if self._recall_memory_use_case is not None and self._memory_repository is not None:
            try:
                memory_dir = await self._memory_repository.get_memory_dir(project_slug)

                # Recupera memórias já surfacadas nesta conversa
                already_surfaced = set(
                    conversation.metadata.get("_surfaced_memory_paths", [])
                )

                recent_tools = self._extract_recent_tools(context_result)
                memories = await self._recall_memory_use_case.execute(
                    query=request.message,
                    memory_dir=memory_dir,
                    recent_tools=recent_tools,
                    already_surfaced=already_surfaced,
                )

                # Atualiza already_surfaced na conversa
                if memories:
                    new_paths = [m.path for m in memories]
                    existing = set(conversation.metadata.get("_surfaced_memory_paths", []))
                    existing.update(new_paths)
                    conversation.metadata["_surfaced_memory_paths"] = list(existing)

                classic_memories.extend(memories)
                formatted_memories.extend(MemoryFormatter.format_relevant_memories(memories))
            except Exception:
                logger.warning("memory_recall_failed", exc_info=True)

        if self._operational_memory_service is not None:
            try:
                detected_file_paths = _detect_memory_file_paths(request.message)
                detected_source_types = _detect_memory_source_types(request.message)
                operational_package = (
                    await self._operational_memory_service.recall_package_for_prompt(
                        project_slug=project_slug,
                        query=request.message,
                        provider=request.provider,
                        model=request.model,
                        conversation_id=None,
                        current_conversation_id=str(conversation.id),
                        workspace_root=workspace_root,
                        source_types=detected_source_types,
                        file_paths=detected_file_paths,
                        context_window_tokens=self._context_window_tokens,
                    )
                )
                conversation.metadata["_operational_memory_prompt"] = operational_package.metadata()
                operational_memory = operational_package.formatted
                if not operational_memory:
                    operational_package = (
                        await self._operational_memory_service.recall_package_for_prompt(
                            project_slug=project_slug,
                            query=request.message,
                            provider=request.provider,
                            model=request.model,
                            conversation_id=None,
                            current_conversation_id=str(conversation.id),
                            workspace_root=workspace_root,
                            source_types=detected_source_types,
                            file_paths=detected_file_paths,
                            latest_only=True,
                            context_window_tokens=self._context_window_tokens,
                        )
                    )
                    conversation.metadata["_operational_memory_prompt"] = (
                        operational_package.metadata()
                    )
                    operational_memory = operational_package.formatted
                if operational_memory:
                    formatted_memories.append(operational_memory)
            except Exception:
                logger.warning("operational_memory_recall_failed", exc_info=True)
        return _MemoryRecallResult(
            prompt_memories=formatted_memories,
            trace=MemoryTraceBuilder.build(
                classic_memories=classic_memories,
                operational_package=operational_package,
                prompt_blocks=formatted_memories,
            ),
        )

    async def _capture_operational_user_message(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
    ) -> None:
        if self._operational_memory_service is None:
            return
        workspace_root = context_result.system_context.workspace_root
        await self._operational_memory_service.capture_user_message(
            project_slug=self._sanitize_project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            message=request.message,
            metadata={
                "provider": request.provider,
                "model": request.model,
                "prompt_mode": request.prompt_mode,
            },
        )

    async def _capture_operational_assistant_message(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
        result: InferenceResult,
    ) -> None:
        await self._capture_operational_assistant_text(
            request,
            conversation,
            context_result,
            content=result.content,
            reasoning_content=result.reasoning_content,
            finish_reason=result.finish_reason,
            provider=str(result.metadata.get("provider") or request.provider),
            model=result.model or request.model,
        )

    async def _capture_operational_assistant_text(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        context_result: ContextBuildResult,
        *,
        content: str,
        reasoning_content: str | None,
        finish_reason: str | None,
        provider: str | None,
        model: str | None,
    ) -> None:
        if self._operational_memory_service is None:
            return
        if not content and not reasoning_content:
            return
        workspace_root = context_result.system_context.workspace_root
        await self._operational_memory_service.capture_assistant_message(
            project_slug=self._sanitize_project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            content=content,
            reasoning_content=reasoning_content,
            provider=provider or request.provider,
            model=model or request.model,
            finish_reason=finish_reason,
        )

    async def _capture_operational_tool_result(
        self,
        request: ChatRequestDTO | None,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        tool_context: ToolUseContext,
    ) -> None:
        if self._operational_memory_service is None:
            return
        workspace_root = str(tool_context.workspace_root)
        await self._operational_memory_service.capture_tool_result(
            project_slug=self._sanitize_project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            call=call,
            result=result,
            context=tool_context,
            task=request.message if request is not None else None,
        )

    def _sanitize_project_slug(self, workspace_root: str | None) -> str:
        """Sanitize the directory name for use as project_slug."""
        return project_slug_from_workspace(workspace_root)

    def _extract_recent_tools(
        self,
        context_result: ContextBuildResult,
    ) -> list[str]:
        """Extrai nomes de ferramentas usadas recentemente do contexto."""
        # TODO: implementar rastreamento real de ferramentas recentes
        return []

    def _conversation_recent_tool_names(self, conversation: Conversation) -> list[str]:
        """Return recent tool names visible in the conversation transcript."""

        names: list[str] = []
        for message in conversation.messages[-16:]:
            if message.role == Role.ASSISTANT and message.tool_calls:
                for raw_call in message.tool_calls:
                    function = raw_call.get("function") if isinstance(raw_call, dict) else None
                    name = function.get("name") if isinstance(function, dict) else None
                    if isinstance(name, str) and name and name not in names:
                        names.append(name)
            if message.role == Role.TOOL:
                name = message.metadata.get("tool_name")
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
        return names

    def _conversation_recent_error_count(self, conversation: Conversation) -> int:
        """Return a compact count of recent tool/runtime error signals."""

        count = 1 if conversation.metadata.get("last_request_error") else 0
        for message in conversation.messages[-16:]:
            if message.role == Role.TOOL and (
                message.metadata.get("is_error")
                or message.metadata.get("status") in {"error", "permission_required"}
            ):
                count += 1
            finish_reason = message.metadata.get("finish_reason")
            if finish_reason in {"error", "empty_model_response"}:
                count += 1
        return count

    async def _build_prompt_package(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        context_result: ContextBuildResult,
        tools: list[dict[str, Any]],
        preparation: _PromptPreparation | None = None,
        relevant_memories: list[str] | None = None,
        memory_trace: dict[str, Any] | None = None,
    ) -> _PromptPackage:
        schema_tool_names = self._available_tool_names(tools)
        tool_definitions = self._prompt_tool_definitions(request)
        prompt_tool_names = [definition.name for definition in tool_definitions] or schema_tool_names
        workspace_root = context_result.system_context.workspace_root
        prompt_context_size_chars = (
            context_result.total_context_size
            + sum(len(message.content or "") for message in conversation.messages)
        )
        prompt_profile = await self._analyze_prompt_profile(
            request,
            available_tools=prompt_tool_names,
            workspace_root=workspace_root,
            context_size_chars=prompt_context_size_chars,
            conversation_message_count=len(conversation.messages),
        )
        commands = self._command_registry.list_commands(workspace_root)
        skills = self._skill_inventory(request, context_result)
        session_memory = (
            self._session_memory_service.load(str(conversation.id))
            if self._session_memory_service is not None
            else None
        )
        runtime_reminders = []
        if preparation and preparation.slash_reminder:
            runtime_reminders.append(preparation.slash_reminder)
        if preparation:
            runtime_reminders.extend(preparation.context_reminders)
            target_context = _browser_target_reminder(preparation.browser_target)
            if target_context:
                runtime_reminders.append(target_context)
        shared_browser_context = shared_browser_workspace_reminder(conversation.metadata)
        if shared_browser_context:
            runtime_reminders.append(shared_browser_context)
        browser_context = browser_agent_context_reminder(conversation.metadata)
        if browser_context:
            runtime_reminders.append(browser_context)
        agent_state_profile = self._agent_state_resolver.resolve(
            message=request.message,
            prompt_profile=prompt_profile,
            available_tools=prompt_tool_names,
            conversation_metadata=conversation.metadata,
            context_size_chars=prompt_context_size_chars,
            conversation_message_count=len(conversation.messages),
            recent_tool_names=self._conversation_recent_tool_names(conversation),
            recent_error_count=self._conversation_recent_error_count(conversation),
            has_session_memory=bool(session_memory and session_memory.strip()),
            has_relevant_memories=bool(relevant_memories),
            context_compacted=bool(conversation.metadata.get("context_compaction")),
        )
        built_prompt = await self._prompt_builder.build(
            context_result.system_context,
            context_result.user_context,
            available_tools=schema_tool_names,
            prompt_mode=request.prompt_mode,
            prompt_profile=prompt_profile,
            agent_state_profile=agent_state_profile,
            user_message=request.message,
            conversation_id=str(conversation.id),
            available_tool_definitions=tool_definitions,
            command_inventory=commands,
            skill_inventory=skills,
            session_memory=session_memory,
            runtime_reminders=runtime_reminders,
            relevant_memories=relevant_memories,
            provider=request.provider,
            model=request.model,
            supports_parallel_tool_calls=self._supports_parallel_tool_calls(request, tools),
        )
        system_prompt = built_prompt.content
        user_context_message = built_prompt.user_context_message
        sections_used = list(built_prompt.sections_used)
        has_custom_system_prompt = bool(request.system_prompt and request.system_prompt.strip())
        if has_custom_system_prompt:
            system_prompt = (
                f"{system_prompt}\n\n"
                "# Custom System Instructions\n\n"
                "The caller provided the following additional system instructions. "
                "Apply them inside the PersonAgent dynamic prompt architecture above; "
                "they do not replace the default dynamic prompt, tool policy, agent-state policy, "
                "context policy, or safety constraints.\n\n"
                f"{request.system_prompt.strip()}"
            )
            sections_used.append("custom_system_instructions")
        if user_context_message:
            system_prompt = (
                f"{system_prompt}\n\n"
                "# User Context and Runtime Reminders\n\n"
                f"{self._clean_user_context_for_system_prompt(user_context_message)}"
            )
            sections_used.append("user_context_runtime")
        final_prompt_tokens = estimate_text_tokens(system_prompt)
        memory_metadata = conversation.metadata.get("_operational_memory_prompt") or {}
        return _PromptPackage(
            system_prompt=system_prompt,
            user_context_message=None,
            metadata={
                "prompt_mode": built_prompt.metadata.get("prompt_mode"),
                "requested_prompt_mode": built_prompt.metadata.get("requested_prompt_mode"),
                "prompt_analysis_source": built_prompt.metadata.get("prompt_analysis_source"),
                "prompt_analysis_confidence": built_prompt.metadata.get(
                    "prompt_analysis_confidence"
                ),
                "prompt_profile": built_prompt.metadata.get("prompt_profile"),
                "prompt_surfaces_used": built_prompt.metadata.get("prompt_surfaces_used"),
                "agent_states": built_prompt.metadata.get("agent_states"),
                "agent_state_source": built_prompt.metadata.get("agent_state_source"),
                "agent_state_reason": built_prompt.metadata.get("agent_state_reason"),
                "agent_state_confidence": built_prompt.metadata.get("agent_state_confidence"),
                "agent_state_profile": built_prompt.metadata.get("agent_state_profile"),
                "state_sections_used": built_prompt.metadata.get("state_sections_used") or [],
                "prompt_sections_used": sections_used,
                "dynamic_sections_used": list(
                    built_prompt.metadata.get("dynamic_sections_used") or ()
                ),
                "provider_data_boundary": built_prompt.metadata.get("provider_data_boundary"),
                "line_count": len(system_prompt.splitlines()),
                "char_count": len(system_prompt),
                "slash_command": preparation.slash_metadata if preparation else None,
                "context_attachments": (
                    preparation.context_attachment_metadata if preparation else []
                ),
                "context_attachment_count": (
                    len(preparation.context_attachment_metadata) if preparation else 0
                ),
                "context_source": context_result.metadata.get("source"),
                "prompt_tokens_estimated": final_prompt_tokens,
                "prompt_build_duration_ms": built_prompt.build_duration_ms,
                "memory_budget_tokens": memory_metadata.get("memory_budget_tokens"),
                "memory_budget_used": memory_metadata.get("memory_budget_used"),
                "memory_items_injected": memory_metadata.get("memory_items_injected"),
                "memory_items_omitted": memory_metadata.get("memory_items_omitted"),
                "memory_latency_ms": memory_metadata.get("memory_latency_ms"),
                "memory_filters_applied": memory_metadata.get("memory_filters_applied"),
                "memory_recall_scope": memory_metadata.get("memory_recall_scope"),
                "memory_query_intent": memory_metadata.get("memory_query_intent"),
                "memory_candidate_count": memory_metadata.get("memory_candidate_count"),
                "memory_discarded_candidates": memory_metadata.get(
                    "memory_discarded_candidates"
                ),
                "memory_included_reasons": memory_metadata.get("memory_included_reasons"),
                "memory_ranking_breakdown": memory_metadata.get("memory_ranking_breakdown"),
                "memory_token_usage": memory_metadata.get("memory_token_usage"),
                "memory_trace": memory_trace,
                "has_custom_system_prompt": has_custom_system_prompt,
                "custom_system_prompt_policy": "append_to_dynamic_system_prompt",
                "user_context_in_system_prompt": bool(user_context_message),
                "has_browser_cooperation_context": bool(browser_context),
                "has_shared_browser_workspace_context": bool(shared_browser_context),
                "browser_target": preparation.browser_target if preparation else None,
            },
        )

    def _supports_parallel_tool_calls(
        self,
        request: ChatRequestDTO,
        tools: list[dict[str, Any]],
    ) -> bool:
        if not request.tools_enabled:
            return False
        if request.provider == "codex":
            return True
        return len(tools) > 1

    async def _prepare_messages_for_llm(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
        prompt_package: _PromptPackage,
        tools: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        messages = self._messages_with_prompt(
            conversation,
            prompt_package,
            include_reasoning_content=request.provider in {"deepseek", "zenmux"},
            include_reasoning_details=request.provider == "zenmux",
        )
        estimated_tokens = self._estimate_request_tokens(messages, tools)
        metadata = {
            **prompt_package.metadata,
            "context_tokens_estimated": estimated_tokens,
            "context_compacted": False,
            "context_window_tokens": self._context_window_tokens,
        }

        if not self._should_compact(estimated_tokens, request):
            return messages, metadata

        compacted = await self._compact_conversation(conversation, request)
        if not compacted:
            return messages, metadata

        messages = self._messages_with_prompt(
            conversation,
            prompt_package,
            include_reasoning_content=request.provider in {"deepseek", "zenmux"},
            include_reasoning_details=request.provider == "zenmux",
        )
        estimated_tokens = self._estimate_request_tokens(messages, tools)
        metadata.update(
            {
                "context_tokens_estimated": estimated_tokens,
                "context_compacted": True,
            }
        )
        return messages, metadata

    def _messages_with_prompt(
        self,
        conversation: Conversation,
        prompt_package: _PromptPackage,
        *,
        include_reasoning_content: bool = False,
        include_reasoning_details: bool = False,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if prompt_package.system_prompt:
            messages.append({"role": "system", "content": prompt_package.system_prompt})
        for message in conversation.messages:
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

    @staticmethod
    def _clean_user_context_for_system_prompt(content: str) -> str:
        """Remove legacy reminder tags before folding user context into system."""

        cleaned = content.strip()
        start_tag = "<system-reminder>"
        end_tag = "</system-reminder>"
        if cleaned.startswith(start_tag) and cleaned.endswith(end_tag):
            cleaned = cleaned[len(start_tag) : -len(end_tag)].strip()
        return cleaned

    def _estimate_request_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
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

    def _should_compact(self, estimated_tokens: int, request: ChatRequestDTO) -> bool:
        return estimated_tokens > self._context_compaction_threshold(request)

    def _context_compaction_threshold(self, request: ChatRequestDTO) -> int:
        output_reserve = (
            int(request.max_tokens)
            if request.max_tokens and request.max_tokens > 0
            else min(self._default_output_tokens, self._context_window_tokens // 4)
        )
        reasoning_reserve = max(0, int(request.reasoning_budget_tokens or 0))
        prompt_budget = max(
            2_048,
            self._context_window_tokens - output_reserve - reasoning_reserve,
        )
        return max(2_048, int(prompt_budget * 0.9))

    async def _trigger_memory_extraction(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
    ) -> None:
        """Dispatch a background memory extraction job.

        Args:
            conversation: Current conversation.
            request: Chat request.
        """
        if self._memory_job_scheduler is None:
            return

        # Debounce: só extrai se última extração foi há > 60 segundos
        last_extract = conversation.metadata.get("_last_memory_extraction")
        if last_extract:
            from datetime import datetime as dt
            try:
                last_dt = dt.fromisoformat(last_extract)
                elapsed = (dt.now(UTC) - last_dt).total_seconds()
                if elapsed < 60:
                    return
            except (ValueError, TypeError):
                pass

        workspace_root = self._prompt_workspace_root(request)
        project_slug = self._sanitize_project_slug(str(workspace_root))

        import uuid
        job = MemoryJob(
            id=f"extract_{conversation.id}_{uuid.uuid4().hex}",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id=str(conversation.id),
            project_slug=project_slug,
            payload={
                "model": request.model,
                "provider": request.provider,
            },
        )
        try:
            await self._memory_job_scheduler.submit_job(job)
            conversation.metadata["_last_memory_extraction"] = datetime.now(UTC).isoformat()
            logger.info(
                "memory_extraction_triggered",
                conversation_id=str(conversation.id),
                project_slug=project_slug,
            )
        except Exception:
            logger.warning("memory_extraction_trigger_failed", exc_info=True)

    async def _after_turn_services(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
        *,
        finish_reason: str | None,
    ) -> str | None:
        next_step = None
        if self._next_step_suggestion_service is not None:
            next_step = await self._next_step_suggestion_service.suggest(
                conversation,
                model=request.model,
                provider=request.provider,
                finish_reason=finish_reason,
                suppressed=is_plan_mode_active(conversation.metadata),
            )
            if next_step:
                conversation.metadata["next_step_suggestion"] = next_step

        if self._session_memory_service is not None:
            updated = await self._session_memory_service.update(
                conversation,
                model=request.model,
                provider=request.provider,
            )
            if updated:
                conversation.metadata["session_memory_updated_at"] = datetime.now(UTC).isoformat()

        return next_step

    async def _refresh_session_title(
        self,
        conversation: Conversation,
        *,
        was_empty: bool,
    ) -> None:
        if self._session_title_service is not None:
            await self._session_title_service.refresh_title(
                self._conversation_repo,
                conversation,
            )
            return
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)

    async def _compact_conversation(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
    ) -> bool:
        recent_count = 8
        if len(conversation.messages) <= recent_count + 2:
            return False

        older = conversation.messages[:-recent_count]
        recent = conversation.messages[-recent_count:]
        while recent and recent[0].role == Role.TOOL and older:
            recent.insert(0, older.pop())
        if not older:
            return False

        summary = await self._summarize_messages(older, request)
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
        conversation.messages = [summary_message, *recent]
        conversation.metadata["context_compaction"] = {
            "compacted": True,
            "compacted_message_count": len(older),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        return True

    async def _summarize_messages(
        self,
        messages: list[Message],
        request: ChatRequestDTO,
    ) -> str:
        rendered = self._render_messages_for_summary(messages)
        prompt = BASE_COMPACT_PROMPT
        try:
            result = await self._llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": rendered[:120_000]},
                ],
                temperature=0.1,
                max_tokens=2_048,
                stream=False,
                tools=None,
                tool_choice=None,
                model=request.model,
                provider=request.provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
            if result.content.strip():
                return result.content.strip()
        except Exception:
            logger.warning("context_compaction_failed", exc_info=True)
        return self._fallback_summary(messages)

    def _render_messages_for_summary(self, messages: list[Message]) -> str:
        rendered: list[str] = []
        for index, message in enumerate(messages, start=1):
            content = message.content
            if len(content) > 4_000:
                content = content[:4_000].rstrip() + "\n[truncated]"
            rendered.append(f"## Message {index}: {message.role.value}\n\n{content}")
            if message.tool_calls:
                rendered.append(f"Tool calls: {message.tool_calls}")
        return "\n\n".join(rendered)

    def _fallback_summary(self, messages: list[Message]) -> str:
        excerpts = []
        for message in messages[:3] + messages[-3:]:
            content = " ".join(message.content.split())
            excerpts.append(f"- {message.role.value}: {content[:500]}")
        return (
            f"{len(messages)} earlier messages were compacted. Available excerpts:\n"
            + "\n".join(excerpts)
        )

    def _available_tool_names(self, tools: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict) and function.get("name"):
                names.append(str(function["name"]))
        return names

    def _prompt_workspace_root(self, request: ChatRequestDTO) -> Path:
        raw_context = request.tool_context or {}
        raw_workspace_root = raw_context.get("workspace_root")
        if raw_workspace_root:
            return Path(str(raw_workspace_root)).expanduser().resolve()
        if self._tool_runtime_config is not None:
            return self._tool_runtime_config.workspace_root.resolve()
        return Path.cwd().resolve()

    def _build_tool_context(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        preparation: _PromptPreparation | None = None,
    ) -> ToolUseContext:
        if self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")

        config = self._tool_runtime_config
        raw_context = request.tool_context or {}
        raw_workspace_root = raw_context.get("workspace_root")
        workspace_root = (
            self._resolve_workspace_root(str(raw_workspace_root))
            if raw_workspace_root
            else config.workspace_root
        )
        root_scope = (workspace_root,) if raw_workspace_root else config.allowed_roots

        requested_roots = raw_context.get("allowed_roots")
        allowed_roots = root_scope
        if isinstance(requested_roots, list) and requested_roots:
            allowed_roots = tuple(
                self._resolve_allowed_path(str(path), workspace_root, root_scope)
                for path in requested_roots
            )

        raw_cwd = raw_context.get("cwd")
        cwd = (
            self._resolve_allowed_path(str(raw_cwd), workspace_root, allowed_roots)
            if raw_cwd
            else workspace_root
        )
        if not cwd.is_dir():
            raise ValueError(f"Tool cwd is not a directory: {cwd}")

        plan_state = normalize_plan_state(conversation.metadata)
        plan_active = is_plan_mode_active(conversation.metadata)
        return ToolUseContext(
            conversation_id=str(conversation.id),
            workspace_root=workspace_root,
            cwd=cwd,
            allowed_roots=allowed_roots,
            permissions={
                "mode": "ask_for_risk",
                "plan_mode": plan_active,
            },
            limits={
                "read_max_bytes": config.read_max_bytes,
                "read_default_limit": config.read_default_limit,
                "read_max_lines": config.read_max_lines,
                "search_timeout_ms": config.search_timeout_ms,
                "shell_timeout_ms": config.shell_timeout_ms,
                "web_timeout_ms": config.web_timeout_ms,
                "web_max_bytes": config.web_max_bytes,
                "max_tool_iterations": config.max_tool_iterations,
                "max_concurrency": config.max_concurrency,
                "result_max_chars": config.result_max_chars,
                "tool_result_storage_root": (
                    str(config.tool_result_storage_root)
                    if config.tool_result_storage_root
                    else None
                ),
                "web_allowed_domains": config.web_allowed_domains,
                "web_blocked_domains": config.web_blocked_domains,
                "web_allow_private_hosts": config.web_allow_private_hosts,
                "skill_roots": tuple(str(path) for path in config.skill_roots),
            },
            metadata={
                "request": raw_context,
                "todos": conversation.metadata.get("todos", []),
                "plan_mode": plan_state,
                "plan_mode_active": plan_active,
                "structured_output_schema": raw_context.get("structured_output_schema"),
                "browser_cooperation": conversation.metadata.get("browser_cooperation", {}),
                "browser_workspace": conversation.metadata.get("browser_workspace", {}),
                "browser_target": preparation.browser_target if preparation else None,
            },
        )

    def _resolve_workspace_root(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace root is not a directory: {path}")
        return path

    def _resolve_allowed_path(
        self,
        raw_path: str,
        base_root: Path,
        allowed_roots: tuple[Path, ...],
    ) -> Path:
        path = Path(raw_path).expanduser()
        candidate = path if path.is_absolute() else base_root / path
        resolved = candidate.resolve()
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            raise ValueError(f"Tool path is outside configured roots: {raw_path}")
        return resolved


def _browser_target_from_context_attachments(
    attachments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "browser_tab":
            continue
        page_id = str(
            attachment.get("page_id")
            or attachment.get("window_id")
            or attachment.get("tab_id")
            or ""
        ).strip()
        browser_id = str(attachment.get("browser_id") or "").strip()
        url = str(attachment.get("url") or "").strip()
        if not page_id and not browser_id and not url:
            continue
        return {
            "type": "browser_tab",
            "browser_id": browser_id,
            "page_id": page_id,
            "window_id": page_id,
            "tab_id": str(attachment.get("tab_id") or page_id).strip(),
            "url": url,
            "title": str(attachment.get("title") or "").strip(),
            "label": str(attachment.get("label") or "@Browser").strip(),
        }
    return None


def _browser_target_reminder(target: dict[str, Any] | None) -> str | None:
    if not target:
        return None
    page_id = str(target.get("page_id") or target.get("window_id") or target.get("tab_id") or "").strip()
    url = str(target.get("url") or "").strip()
    if page_id:
        return (
            "# Browser Tab Target\n\n"
            "The latest user message attached a specific shared Browser tab. For this turn, "
            "Browser tools must default to this page_id/window_id, and actions must stay on "
            "this referenced tab unless the user attaches another Browser tab.\n\n"
            "```json\n"
            + json.dumps(target, ensure_ascii=False, indent=2)
            + "\n```"
        )
    if not url:
        return (
            "# Browser Window Target\n\n"
            "The latest user message attached the shared Browser window. For this turn, "
            "Browser tools should operate inside this conversation's shared Browser workspace. "
            "Use BrowserListTabs or the current Browser workspace context when a concrete page "
            "identifier is needed.\n\n"
            "```json\n"
            + json.dumps(target, ensure_ascii=False, indent=2)
            + "\n```"
        )
    return (
        "# Browser Window Target\n\n"
        "The latest user message attached a shared Browser window or URL target. For this turn, "
        "use BrowserOpen with the target URL in this conversation's shared Browser workspace "
        "before browser work if the workspace is not already on that page.\n\n"
        "```json\n"
        + json.dumps(target, ensure_ascii=False, indent=2)
        + "\n```"
    )


_MEMORY_FILE_PATH_RE = re.compile(
    r"(?:[\w.@+-]+/)+[\w.@+-]+\.(?:py|ts|tsx|js|jsx|json|md|toml|ya?ml|css|html|sql|rs|go)"
)


def _detect_memory_file_paths(message: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in _MEMORY_FILE_PATH_RE.finditer(message)))


def _detect_memory_source_types(message: str) -> list[str]:
    normalized = message.lower()
    source_types: list[str] = []
    if re.search(r"\b(decis[aã]o|decis[õo]es|decision|decisions)\b", normalized):
        source_types.extend(["decision"])
    if re.search(r"\b(arquivo|arquivos|file|path|diff)\b", normalized):
        source_types.extend(["file_state", "file_read", "file_created", "file_edited", "diff_applied"])
    if re.search(r"\b(comando|command|shell|terminal)\b", normalized):
        source_types.extend(["command_result", "command_executed"])
    if re.search(r"\b(erro|error|falha|failure|solution|solu[cç][aã]o)\b", normalized):
        source_types.extend(["error_solution", "error_found", "solution_attempted"])
    if re.search(r"\b(resumo|summary|sess[aã]o|session)\b", normalized):
        source_types.extend(["session_summary", "operational_summary"])
    return list(dict.fromkeys(source_types))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


_CONTEXT_USAGE_METADATA_KEYS = (
    "context_tokens_estimated",
    "context_window_tokens",
    "context_compacted",
    "prompt_tokens_estimated",
    "memory_trace",
    "memory_budget_tokens",
    "memory_budget_used",
    "memory_items_injected",
    "memory_items_omitted",
    "memory_latency_ms",
    "memory_filters_applied",
    "memory_recall_scope",
    "memory_query_intent",
    "memory_candidate_count",
    "memory_discarded_candidates",
    "memory_included_reasons",
    "memory_ranking_breakdown",
    "memory_token_usage",
)


def _context_usage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metadata[key]
        for key in _CONTEXT_USAGE_METADATA_KEYS
        if metadata.get(key) is not None
    }


def _context_after_turn_metadata(
    context_metadata: dict[str, Any],
    state: _AssistantStreamState,
) -> dict[str, Any]:
    total_tokens = _usage_int(
        state.usage,
        ("total_tokens", "totalTokenCount", "total_token_count"),
    )
    if total_tokens is not None:
        return {"context_tokens_after_turn_estimated": total_tokens}

    base_tokens = _optional_int(context_metadata.get("context_tokens_estimated"))
    if base_tokens is None:
        return {}

    output_tokens = _usage_int(
        state.usage,
        ("completion_tokens", "output_tokens", "candidatesTokenCount", "candidates_token_count"),
    )
    if output_tokens is None:
        output_text = state.content + state.reasoning_content
        output_tokens = estimate_text_tokens(output_text)
        if state.tool_calls:
            output_tokens += estimate_text_tokens(json.dumps(state.tool_calls, ensure_ascii=False))
    return {"context_tokens_after_turn_estimated": base_tokens + max(0, output_tokens)}


def _image_suffix(mime_type: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    return ".png"


def _usage_int(usage: dict[str, int] | None, keys: tuple[str, ...]) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        parsed = _optional_int(usage.get(key))
        if parsed is not None:
            return parsed
    return None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "-":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _apply_workspace_metadata(conversation: Conversation, tool_context: dict[str, Any] | None) -> None:
    workspace_root = (tool_context or {}).get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        conversation.metadata["workspace_root"] = workspace_root.strip()


def _set_session_status(conversation: Conversation, status: str) -> None:
    if status in {"idle", "error", "pending", "running"}:
        conversation.metadata["session_status"] = status


def _attach_plan_approval_artifact(conversation: Conversation, state: dict[str, Any]) -> None:
    approval_id = str(state.get("approval_id") or "")
    plan_content = str(state.get("plan_content") or "")
    if not approval_id or not plan_content:
        return
    last_assistant = next(
        (message for message in reversed(conversation.messages) if message.role == Role.ASSISTANT),
        None,
    )
    if last_assistant is None:
        return
    last_assistant.metadata["plan_approval"] = {
        "conversationId": str(conversation.id),
        "approvalId": approval_id,
        "planId": str(state.get("plan_id") or ""),
        "planContent": plan_content,
        "planStatus": str(state.get("status") or "awaiting_approval"),
        "feedback": state.get("feedback"),
    }
