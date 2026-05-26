"""Chat completion route registration."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# Late-binding module reference.  See module docstring for rationale.
import personagent.adapters.api.routes.chat as _chat
from personagent.adapters.api.errors import error_event
from personagent.adapters.api.routes.chat.completion.resolvers import (
    resolve_context_window_tokens,
    resolve_context_workspace_root,
    resolve_default_output_tokens,
    resolve_model,
)
from personagent.adapters.api.routes.chat.helpers import (
    DB_SESSION_DEPENDENCY,
    ChatRequest,
    ChatResponse,
    encode_sse,
    resolve_next_step_suggestion_service,
    resolve_prompt_mode,
    resolve_provider,
    resolve_reasoning_budget,
    resolve_session_memory_service,
    resolve_tool_context,
)
from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    InvalidRequestError,
    LLMBackendConnectionError,
    LLMBackendError,
)

logger = structlog.get_logger(__name__)


def register_completion_routes(router: APIRouter) -> None:
    """Register chat completion and teams endpoints."""

    @router.get("/teams")
    async def list_teams() -> dict[str, Any]:
        """List built-in Team Mode presets."""
        from personagent.application.team_chat import default_team_config, serialize_team_config

        return {
            "object": "list",
            "data": [serialize_team_config(default_team_config())],
        }

    @router.post("/completions", response_model=ChatResponse)
    async def chat_completion(
        request: ChatRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> ChatResponse:
        """Send a message and receive a complete non-streaming response."""
        container = _chat.get_container()
        provider = resolve_provider(request.provider)
        model = resolve_model(provider, request.model)
        prompt_mode = resolve_prompt_mode(request.prompt_mode)
        llm_backend = container.get_llm_backend(provider)
        conv_repo = await container.get_conversation_repo(session)
        context_workspace_root = resolve_context_workspace_root(request)

        use_case = ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=llm_backend,
            tool_registry=container.get_tool_registry(),
            tool_runtime_config=container.get_tool_runtime_config(),
            build_context_use_case=container.create_build_context_use_case(context_workspace_root),
            prompt_builder=container.get_prompt_builder(),
            prompt_context_analyzer=container.create_prompt_context_analyzer(llm_backend),
            command_registry=container.create_command_registry(),
            session_memory_service=resolve_session_memory_service(container, llm_backend),
            next_step_suggestion_service=resolve_next_step_suggestion_service(container, llm_backend),
            session_title_service=getattr(container, "get_session_title_service", lambda: None)(),
            recall_memory_use_case=(
                container.create_recall_memory_use_case(llm_backend)
                if container.settings.memory_recall_enabled
                else None
            ),
            memory_job_scheduler=(
                container.get_memory_job_scheduler()
                if container.settings.auto_memory_enabled
                else None
            ),
            memory_repository=container.get_memory_repository(),
            operational_memory_service=container.get_operational_memory_service(),
            context_window_tokens=resolve_context_window_tokens(container, provider),
            default_output_tokens=resolve_default_output_tokens(container, provider),
            artifact_root=container.settings.personagent_artifact_root,
            artifact_ttl_seconds=container.settings.personagent_artifact_ttl_seconds,
        )

        conversation_id = None
        if request.conversation_id:
            conversation_id = UUID(request.conversation_id)

        message_text = request.message
        plan_mode_requested = request.plan_mode_requested
        if message_text.strip() == "/plan":
            plan_mode_requested = True
            message_text = "Enter plan mode"
        elif message_text.strip().startswith("/plan "):
            plan_mode_requested = True
            message_text = message_text.strip()[6:]

        dto = ChatRequestDTO(
            conversation_id=conversation_id,
            message=message_text,
            system_prompt=request.system_prompt,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            provider=provider,
            model=model,
            prompt_mode=prompt_mode,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=resolve_reasoning_budget(request),
            tools_enabled=request.tools_enabled and container.settings.tools_enabled,
            allowed_tools=request.allowed_tools,
            tool_context=resolve_tool_context(request),
            max_tool_iterations=request.max_tool_iterations,
            context_attachments=request.context_attachments,
            plan_mode_requested=plan_mode_requested,
        )

        try:
            result = await use_case.execute(dto)
        except ConversationNotFoundError:
            raise
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
        except LLMBackendConnectionError:
            raise
        except LLMBackendError:
            raise

        return ChatResponse(
            conversation_id=str(result.conversation_id),
            message_id=result.message_id,
            content=result.content,
            reasoning_content=result.reasoning_content,
            finish_reason=result.finish_reason,
            usage=result.usage,
            model=result.model,
            provider=result.provider,
            images=[image.to_dict() for image in result.images],
        )

    @router.post("/completions/stream")
    async def chat_completion_stream(
        request: ChatRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> StreamingResponse:
        """Send a message and receive the response as Server-Sent Events."""
        container = _chat.get_container()
        provider = resolve_provider(request.provider)
        model = resolve_model(provider, request.model)
        prompt_mode = resolve_prompt_mode(request.prompt_mode)
        llm_backend = container.get_llm_backend(provider)
        conv_repo = await container.get_conversation_repo(session)
        context_workspace_root = resolve_context_workspace_root(request)

        use_case = ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=llm_backend,
            tool_registry=container.get_tool_registry(),
            tool_runtime_config=container.get_tool_runtime_config(),
            build_context_use_case=container.create_build_context_use_case(context_workspace_root),
            prompt_builder=container.get_prompt_builder(),
            prompt_context_analyzer=container.create_prompt_context_analyzer(llm_backend),
            command_registry=container.create_command_registry(),
            session_memory_service=resolve_session_memory_service(container, llm_backend),
            next_step_suggestion_service=resolve_next_step_suggestion_service(container, llm_backend),
            session_title_service=getattr(container, "get_session_title_service", lambda: None)(),
            recall_memory_use_case=(
                container.create_recall_memory_use_case(llm_backend)
                if container.settings.memory_recall_enabled
                else None
            ),
            memory_job_scheduler=(
                container.get_memory_job_scheduler()
                if container.settings.auto_memory_enabled
                else None
            ),
            memory_repository=container.get_memory_repository(),
            operational_memory_service=container.get_operational_memory_service(),
            context_window_tokens=resolve_context_window_tokens(container, provider),
            default_output_tokens=resolve_default_output_tokens(container, provider),
            artifact_root=container.settings.personagent_artifact_root,
            artifact_ttl_seconds=container.settings.personagent_artifact_ttl_seconds,
        )

        conversation_id = None
        if request.conversation_id:
            conversation_id = UUID(request.conversation_id)

        message_text = request.message
        plan_mode_requested = request.plan_mode_requested
        if message_text.strip() == "/plan":
            plan_mode_requested = True
            message_text = "Enter plan mode"
        elif message_text.strip().startswith("/plan "):
            plan_mode_requested = True
            message_text = message_text.strip()[6:]

        dto = ChatRequestDTO(
            conversation_id=conversation_id,
            message=message_text,
            system_prompt=request.system_prompt,
            stream=True,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            provider=provider,
            model=model,
            prompt_mode=prompt_mode,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=resolve_reasoning_budget(request),
            tools_enabled=request.tools_enabled and container.settings.tools_enabled,
            allowed_tools=request.allowed_tools,
            tool_context=resolve_tool_context(request),
            max_tool_iterations=request.max_tool_iterations,
            context_attachments=request.context_attachments,
            plan_mode_requested=plan_mode_requested,
        )

        async def event_generator() -> AsyncIterator[str]:
            """Gera eventos SSE para o streaming."""
            try:
                async for chunk in use_case.execute_stream(dto):
                    data: dict = dict(chunk.metadata)
                    if chunk.content:
                        data["content"] = chunk.content
                    if chunk.reasoning_content:
                        data["reasoning_content"] = chunk.reasoning_content
                    if chunk.is_thinking:
                        data["is_thinking"] = True
                    if chunk.finish_reason:
                        data["finish_reason"] = chunk.finish_reason
                    if chunk.usage:
                        data["usage"] = chunk.usage
                    if chunk.tool_calls:
                        data["tool_calls"] = chunk.tool_calls
                    if chunk.images:
                        data["images"] = [image.to_dict() for image in chunk.images]

                    if data:
                        yield encode_sse(data)

            except ConversationNotFoundError as exc:
                yield encode_sse(error_event(exc))
            except ValueError as exc:
                yield encode_sse(error_event(exc, status_code=400))
            except LLMBackendConnectionError as exc:
                yield encode_sse(error_event(exc))
            except LLMBackendError as exc:
                yield encode_sse(error_event(exc))
            except Exception as exc:
                logger.exception("chat_stream_unhandled_error")
                yield encode_sse(error_event(exc, default_message="Unexpected error in chat stream."))
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
