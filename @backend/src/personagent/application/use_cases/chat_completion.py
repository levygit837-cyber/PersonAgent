"""Caso de uso: Chat Completion."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

from personagent.application.dto.chat_dto import ChatRequestDTO, ChatResponseDTO
from personagent.application.jobs.memory_job import JobType, MemoryJob
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    is_plan_mode_active,
    new_tool_approval_id,
    normalize_plan_state,
    now_iso,
    plan_mode_event,
    write_plan_state,
)
from personagent.application.services import NextStepSuggestionService, SessionMemoryService
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
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import GeneratedImage, InferenceResult, StreamChunk
from personagent.domain.prompts.commands import (
    CommandRegistry,
    SlashCommandResolution,
    parse_slash_invocation,
)
from personagent.domain.prompts.compact import BASE_COMPACT_PROMPT
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.prompts.services.prompt_builder import estimate_text_tokens
from personagent.domain.prompts.skills import SkillDefinition, discover_skills, find_skill
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolResult,
    ToolUseContext,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class _PromptPackage:
    system_prompt: str | None
    user_context_message: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class _PromptPreparation:
    request: ChatRequestDTO
    slash_reminder: str | None = None
    slash_metadata: dict[str, Any] | None = None


class ChatCompletionUseCase:
    """Orquestra uma interação de chat com o LLM."""

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        llm_backend: LLMBackendRepository,
        tool_registry: ToolRegistry | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
        build_context_use_case: BuildContextUseCase | None = None,
        prompt_builder: PromptBuilder | None = None,
        prompt_context_analyzer: PromptContextAnalyzer | None = None,
        command_registry: CommandRegistry | None = None,
        session_memory_service: SessionMemoryService | None = None,
        next_step_suggestion_service: NextStepSuggestionService | None = None,
        recall_memory_use_case: RecallMemoryUseCase | None = None,
        memory_job_scheduler: MemoryJobScheduler | None = None,
        memory_repository: MemoryRepository | None = None,
        context_window_tokens: int = 262_144,
        default_output_tokens: int = 65_536,
    ):
        self._conversation_repo = conversation_repo
        self._llm_backend = llm_backend
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config
        self._build_context_use_case = build_context_use_case
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._prompt_context_analyzer = prompt_context_analyzer
        self._command_registry = command_registry or CommandRegistry()
        self._session_memory_service = session_memory_service
        self._next_step_suggestion_service = next_step_suggestion_service
        self._recall_memory_use_case = recall_memory_use_case
        self._memory_job_scheduler = memory_job_scheduler
        self._memory_repository = memory_repository
        self._context_window_tokens = max(4_096, int(context_window_tokens))
        self._default_output_tokens = max(1, int(default_output_tokens))
        self._state_manager = StateManager.get_instance()

    async def execute(self, request: ChatRequestDTO) -> ChatResponseDTO:
        """Executa um chat completion síncrono."""
        conversation = await self._get_or_create_conversation(request)
        was_empty = len(conversation.messages) == 0

        context_result = await self._build_context_result(request, conversation)
        preparation = self._prepare_prompt_surfaces(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request)

        # Adiciona mensagem do usuário
        user_msg = Message(role=Role.USER, content=request.message)
        conversation.add_message(user_msg)

        # Recall memórias relevantes
        relevant_memories = await self._recall_relevant_memories(
            request, context_result, conversation
        )

        prompt_package = await self._build_prompt_package(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=relevant_memories,
        )

        tool_context = self._build_tool_context(request, conversation) if tools else None
        result = InferenceResult(content="")
        seen_tool_call_ids: set[str] = set()

        try:
            max_iterations = self._max_tool_iterations(request)
            iteration = 0
            while max_iterations is None or iteration < max_iterations:
                messages, _context_metadata = await self._prepare_messages_for_llm(
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

                assistant_msg = self._assistant_message_from_result(result)
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

        # Atualiza título se for a primeira mensagem
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)

        assistant_msg = conversation.messages[-1]
        await self._after_turn_services(
            conversation,
            request,
            finish_reason=result.finish_reason,
        )
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
        """Executa um chat completion com streaming."""
        conversation = await self._get_or_create_conversation(request)
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

    async def resume_after_tool_result_stream(
        self,
        request: ChatRequestDTO,
    ) -> AsyncIterator[StreamChunk]:
        """Retoma o loop do modelo depois que um tool_result foi persistido."""
        if request.conversation_id is None:
            raise ConversationNotFoundError("conversation_id é obrigatório para retomar ferramenta")
        conversation = await self._get_or_create_conversation(request)
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
        """Executa um turno de streaming, opcionalmente sem nova mensagem de usuário."""
        context_result = await self._build_context_result(request, conversation)
        preparation = self._prepare_prompt_surfaces(request, context_result)
        request = preparation.request
        tools = self._resolve_tool_schemas(request)

        if append_user_message:
            user_msg = Message(role=Role.USER, content=request.message)
            conversation.add_message(user_msg)

        # Emite status para o frontend saber que está montando o prompt
        yield StreamChunk(metadata={"event": "status", "status": status})

        # Recall memórias relevantes
        relevant_memories = await self._recall_relevant_memories(
            request, context_result, conversation
        )

        prompt_package = await self._build_prompt_package(
            request,
            conversation,
            context_result,
            tools,
            preparation,
            relevant_memories=relevant_memories,
        )

        tool_context = self._build_tool_context(request, conversation) if tools else None
        final_finish_reason = None
        final_usage = None
        final_model = request.model
        final_provider = request.provider
        seen_tool_call_ids: set[str] = set()

        try:
            max_iterations = self._max_tool_iterations(request)
            iteration = 0
            tool_limit_exceeded = False
            prompt_context_emitted = False
            while max_iterations is None or iteration < max_iterations:
                messages, context_metadata = await self._prepare_messages_for_llm(
                    conversation,
                    request,
                    prompt_package,
                    tools,
                )
                if not prompt_context_emitted:
                    yield StreamChunk(
                        metadata={
                            "event": "prompt_context",
                            **context_metadata,
                        }
                    )
                    prompt_context_emitted = True
                assistant_content_chunks: list[str] = []
                assistant_reasoning_chunks: list[str] = []
                assistant_images: list[GeneratedImage] = []
                assistant_metadata: dict[str, Any] = {}
                assistant_tool_calls: list[dict[str, Any]] | None = None
                assistant_finish_reason = None
                assistant_usage = None
                assistant_model = request.model
                assistant_provider = request.provider

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
                    chunk_metadata = {
                        "provider": request.provider,
                        "model": request.model,
                        **chunk.metadata,
                    }
                    if chunk.content:
                        assistant_content_chunks.append(chunk.content)
                    if chunk.reasoning_content:
                        assistant_reasoning_chunks.append(chunk.reasoning_content)
                    if chunk.images:
                        assistant_images.extend(chunk.images)
                    if chunk.tool_calls:
                        assistant_tool_calls = self._unique_tool_call_ids(
                            chunk.tool_calls,
                            seen_tool_call_ids,
                            iteration,
                        )
                        assistant_finish_reason = "tool_calls"
                    assistant_metadata.update(
                        {
                            key: value
                            for key, value in chunk_metadata.items()
                            if key.startswith(("vertex_", "kimi_"))
                        }
                    )
                    if chunk.finish_reason:
                        internal_tool_stop = (
                            assistant_tool_calls is not None
                            and chunk.finish_reason != "tool_calls"
                            and not chunk.content
                            and not chunk.reasoning_content
                            and not chunk.images
                        )
                        if not internal_tool_stop:
                            assistant_finish_reason = chunk.finish_reason
                            if chunk.finish_reason != "tool_calls":
                                final_finish_reason = chunk.finish_reason
                    if chunk.usage:
                        assistant_usage = chunk.usage
                        final_usage = chunk.usage
                    if chunk_metadata.get("model"):
                        assistant_model = str(chunk_metadata["model"])
                    else:
                        assistant_model = request.model
                    assistant_provider = str(chunk_metadata.get("provider") or request.provider)
                    final_model = assistant_model
                    final_provider = assistant_provider
                    forwarded_finish_reason = self._forwarded_finish_reason(
                        chunk,
                        has_pending_tool_calls=assistant_tool_calls is not None,
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

                assistant_content = "".join(assistant_content_chunks)
                assistant_reasoning = "".join(assistant_reasoning_chunks)
                conversation.add_message(
                    Message(
                        role=Role.ASSISTANT,
                        content=assistant_content,
                        tool_calls=assistant_tool_calls,
                        metadata={
                            "reasoning_content": assistant_reasoning or None,
                            "finish_reason": assistant_finish_reason,
                            "usage": assistant_usage,
                            "model": assistant_model,
                            "provider": assistant_provider,
                            "images": [image.to_dict() for image in assistant_images],
                            **assistant_metadata,
                        },
                    )
                )

                tool_calls = self._parse_tool_calls(assistant_tool_calls)
                if not tool_calls or not tool_context:
                    break

                orchestrator = self._new_orchestrator()
                results_by_id: dict[str, ToolResult] = {}
                waiting_for_plan_approval = False
                waiting_for_tool_approval = False
                async for event in orchestrator.execute(tool_calls, tool_context):
                    if event.result is not None:
                        results_by_id[event.call.id] = event.result
                    metadata = event.to_stream_metadata()
                    if event.result is not None and event.event == "permission_required":
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
                iteration += 1
                if waiting_for_plan_approval or waiting_for_tool_approval:
                    break
                if max_iterations is not None and iteration >= max_iterations:
                    tool_limit_exceeded = True

            if tool_limit_exceeded:
                final_finish_reason = "tool_iterations_exceeded"
                yield StreamChunk(
                    finish_reason="tool_iterations_exceeded",
                    metadata={
                        "event": "tool_iterations_exceeded",
                        "provider": final_provider,
                        "model": final_model,
                    },
                )

        except LLMBackendError as exc:
            logger.error("llm_backend_stream_error", error=str(exc))
            raise

        next_step_suggestion = await self._after_turn_services(
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

        await self._conversation_repo.update(conversation)

        # Trigger extração de memória em background
        await self._trigger_memory_extraction(conversation, request)

        # Atualiza título se necessário
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)

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
            }
        )

    async def _get_or_create_conversation(self, request: ChatRequestDTO) -> Conversation:
        """Recupera ou cria uma conversa baseada no request."""
        if request.conversation_id:
            conversation = await self._conversation_repo.get_by_id(request.conversation_id)
            if not conversation:
                raise ConversationNotFoundError(
                    f"Conversa {request.conversation_id} não encontrada"
                )
            return conversation

        # Cria nova conversa
        conversation = Conversation()
        await self._conversation_repo.create(conversation)
        return conversation

    def _assistant_message_from_result(self, result: InferenceResult) -> Message:
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
                **result.metadata,
            },
        )

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
        for result in results:
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
        pending = {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
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
            },
            "created_at": now_iso(),
        }
        conversation.metadata[PENDING_TOOL_APPROVAL_KEY] = pending
        return {
            "conversation_id": str(conversation.id),
            "approval_id": approval_id,
            "tool_approval": pending,
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

    def _prepare_prompt_surfaces(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
    ) -> _PromptPreparation:
        parsed = parse_slash_invocation(request.message)
        if parsed is None:
            return _PromptPreparation(request=request)

        workspace_root = context_result.system_context.workspace_root
        resolution = self._command_registry.resolve(request.message, workspace_root)
        if resolution is not None:
            return self._preparation_from_command(request, resolution)

        skill = find_skill(
            parsed[0],
            workspace_root=workspace_root,
            cwd=context_result.system_context.cwd or workspace_root,
            extra_roots=self._skill_roots(),
        )
        if skill is not None and skill.user_invocable:
            return self._preparation_from_skill(request, skill, parsed[1])

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
    ):
        if request.provider == "llama" and request.prompt_mode == "auto":
            from personagent.domain.prompts.services.context_analyzer import fallback_prompt_profile

            return fallback_prompt_profile()
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
                )
            return fallback_prompt_profile()
        return await self._prompt_context_analyzer.analyze(
            message=request.message,
            requested_mode=request.prompt_mode,
            available_tools=available_tools,
            workspace_root=workspace_root,
            model=request.model,
            provider=request.provider,
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
        return discover_skills(
            workspace_root=workspace_root,
            cwd=cwd,
            extra_roots=self._skill_roots(),
            include_global=False,
        )

    def _skill_roots(self) -> tuple[str | Path, ...]:
        if self._tool_runtime_config is None:
            return ()
        return tuple(str(path) for path in self._tool_runtime_config.skill_roots)

    def _new_orchestrator(self) -> ToolOrchestrator:
        if self._tool_registry is None or self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")
        return ToolOrchestrator(self._tool_registry, self._tool_runtime_config)

    def _max_tool_iterations(self, request: ChatRequestDTO) -> int | None:
        if request.max_tool_iterations is not None:
            return max(1, int(request.max_tool_iterations))
        if self._tool_runtime_config is None:
            return 1
        return self._tool_runtime_config.max_tool_iterations

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
    ) -> list[str]:
        """Executa o recall de memórias relevantes para a query atual.

        Args:
            request: DTO do chat request.
            context_result: Resultado do build context.
            conversation: Conversa atual (para tracking de already_surfaced).

        Returns:
            Lista de memórias relevantes formatadas como strings.
        """
        if self._recall_memory_use_case is None or self._memory_repository is None:
            return []

        workspace_root = context_result.system_context.workspace_root
        project_slug = self._sanitize_project_slug(workspace_root)

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

            return MemoryFormatter.format_relevant_memories(memories)
        except Exception:
            logger.warning("memory_recall_failed", exc_info=True)
            return []

    def _sanitize_project_slug(self, workspace_root: str | None) -> str:
        """Sanitiza o nome do diretório para uso como project_slug."""
        if not workspace_root:
            return "default"
        name = Path(workspace_root).name
        # Remove caracteres problemáticos para filesystem
        import re
        return re.sub(r'[^a-zA-Z0-9_-]', '_', name).lower() or "default"

    def _extract_recent_tools(
        self,
        context_result: ContextBuildResult,
    ) -> list[str]:
        """Extrai nomes de ferramentas usadas recentemente do contexto."""
        # TODO: implementar rastreamento real de ferramentas recentes
        return []

    async def _build_prompt_package(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        context_result: ContextBuildResult,
        tools: list[dict[str, Any]],
        preparation: _PromptPreparation | None = None,
        relevant_memories: list[str] | None = None,
    ) -> _PromptPackage:
        schema_tool_names = self._available_tool_names(tools)
        tool_definitions = self._prompt_tool_definitions(request)
        prompt_tool_names = [definition.name for definition in tool_definitions] or schema_tool_names
        workspace_root = context_result.system_context.workspace_root
        prompt_profile = await self._analyze_prompt_profile(
            request,
            available_tools=prompt_tool_names,
            workspace_root=workspace_root,
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
        built_prompt = await self._prompt_builder.build(
            context_result.system_context,
            context_result.user_context,
            available_tools=schema_tool_names,
            prompt_mode=request.prompt_mode,
            prompt_profile=prompt_profile,
            user_message=request.message,
            conversation_id=str(conversation.id),
            available_tool_definitions=tool_definitions,
            command_inventory=commands,
            skill_inventory=skills,
            session_memory=session_memory,
            runtime_reminders=runtime_reminders,
            relevant_memories=relevant_memories,
        )
        system_prompt = built_prompt.content
        sections_used = list(built_prompt.sections_used)
        has_custom_system_prompt = bool(request.system_prompt and request.system_prompt.strip())
        if has_custom_system_prompt:
            system_prompt = (
                f"{system_prompt}\n\n"
                "# Custom System Instructions\n\n"
                "The caller provided the following additional system instructions. "
                "Apply them inside the PersonAgent dynamic prompt architecture above; "
                "they do not replace the default dynamic prompt, tool policy, context policy, "
                "or safety constraints.\n\n"
                f"{request.system_prompt.strip()}"
            )
            sections_used.append("custom_system_instructions")
        return _PromptPackage(
            system_prompt=system_prompt,
            user_context_message=built_prompt.user_context_message,
            metadata={
                "prompt_mode": built_prompt.metadata.get("prompt_mode"),
                "requested_prompt_mode": built_prompt.metadata.get("requested_prompt_mode"),
                "prompt_analysis_source": built_prompt.metadata.get("prompt_analysis_source"),
                "prompt_analysis_confidence": built_prompt.metadata.get(
                    "prompt_analysis_confidence"
                ),
                "prompt_profile": built_prompt.metadata.get("prompt_profile"),
                "prompt_surfaces_used": built_prompt.metadata.get("prompt_surfaces_used"),
                "prompt_sections_used": sections_used,
                "dynamic_sections_used": list(
                    built_prompt.metadata.get("dynamic_sections_used") or ()
                ),
                "slash_command": preparation.slash_metadata if preparation else None,
                "context_source": context_result.metadata.get("source"),
                "prompt_tokens_estimated": estimate_text_tokens(system_prompt)
                + estimate_text_tokens(built_prompt.user_context_message or ""),
                "prompt_build_duration_ms": built_prompt.build_duration_ms,
                "has_custom_system_prompt": has_custom_system_prompt,
                "custom_system_prompt_policy": "append_to_dynamic_system_prompt",
            },
        )

    async def _prepare_messages_for_llm(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
        prompt_package: _PromptPackage,
        tools: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        messages = self._messages_with_prompt(conversation, prompt_package)
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

        messages = self._messages_with_prompt(conversation, prompt_package)
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
    ) -> list[dict[str, Any]]:
        messages = conversation.get_messages_for_llm(prompt_package.system_prompt)
        if not prompt_package.user_context_message:
            return messages
        insert_at = 1 if messages and messages[0].get("role") == "system" else 0
        messages.insert(
            insert_at,
            {"role": "user", "content": prompt_package.user_context_message},
        )
        return messages

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
        """Dispara um job de extração de memória em background.

        Args:
            conversation: Conversa atual.
            request: Request do chat.
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
            role=Role.USER,
            content=(
                "<system-reminder>\n"
                "Earlier conversation messages were compacted to stay within the context "
                "window. Use this summary as continuity context, then rely on the recent "
                "messages below for exact current state.\n\n"
                f"{summary}\n"
                "</system-reminder>"
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
                "result_max_chars": config.result_max_chars,
                "tool_result_storage_root": (
                    str(config.tool_result_storage_root)
                    if config.tool_result_storage_root
                    else None
                ),
                "web_allowed_domains": config.web_allowed_domains,
                "web_blocked_domains": config.web_blocked_domains,
                "skill_roots": tuple(str(path) for path in config.skill_roots),
            },
            metadata={
                "request": raw_context,
                "todos": conversation.metadata.get("todos", []),
                "plan_mode": plan_state,
                "plan_mode_active": plan_active,
                "structured_output_schema": raw_context.get("structured_output_schema"),
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

def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
