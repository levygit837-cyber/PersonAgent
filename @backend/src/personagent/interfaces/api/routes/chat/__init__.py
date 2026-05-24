"""FastAPI chat routes."""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
)
from personagent.application.team_chat import (
    default_team_config,
    serialize_team_config,
)
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    InvalidRequestError,
    LLMBackendConnectionError,
    LLMBackendError,
)
from personagent.domain.models.conversation import Message, Role
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolExecutionStatus
from personagent.infrastructure.persistence.database import AsyncSessionLocal as AsyncSessionLocal
from personagent.interfaces.api.action_approvals import canonical_args_hash
from personagent.interfaces.api.errors import error_event
from personagent.interfaces.api.routes.chat.helpers import (
    DB_SESSION_DEPENDENCY,
    ChatRequest,
    ChatResponse,
    ToolApprovalDecisionRequest,
    UserQuestionResponseRequest,
    _last_user_message,
    _require_tool_approval,
    _require_user_question,
    encode_sse,
    resolve_next_step_suggestion_service,
    resolve_prompt_mode,
    resolve_provider,
    resolve_reasoning_budget,
    resolve_session_memory_service,
    resolve_tool_context,
)
from personagent.interfaces.api.routes.chat.helpers import get_db as get_db
from personagent.interfaces.api.routes.chat.models_listing import register_model_listing_routes
from personagent.interfaces.api.routes.chat.plan_approval import register_plan_approval_routes
from personagent.interfaces.api.routes.chat.team_chat import (
    _team_trace_event_for_storage as _team_trace_event_for_storage,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    load_team_memory_snapshot as load_team_memory_snapshot,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_blackboard_event as persist_team_blackboard_event,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_memory_snapshot as persist_team_memory_snapshot,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_run as persist_team_run,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_run_started as persist_team_run_started,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    register_team_chat_routes,
)
from personagent.interfaces.api.routes.chat.tool_approval import register_tool_approval_routes
from personagent.interfaces.config.di_container import DIContainer, get_container

router = APIRouter(prefix="/chat", tags=["chat"])
logger = structlog.get_logger(__name__)

def resolve_model(provider: str, model: str) -> str:
    """Resolve the default model per provider without breaking the existing local default."""
    if provider == "nvidia" and (not model or model == "local-model"):
        return get_container().settings.nvidia_default_model
    if provider == "deepseek" and (not model or model == "local-model"):
        return get_container().settings.deepseek_default_model
    if provider == "zenmux" and (not model or model == "local-model"):
        return get_container().settings.zenmux_default_model
    if provider == "vertex" and (not model or model == "local-model"):
        return get_container().settings.vertex_default_model
    if provider == "kimi" and (not model or model == "local-model"):
        return get_container().settings.kimi_default_model
    if provider == "codex" and (not model or model == "local-model"):
        return get_container().settings.codex_default_model
    return model

def resolve_context_window_tokens(container: DIContainer, provider: str) -> int:
    """Resolve the context window used for provider-specific budgeting/compaction."""
    if provider == "kimi":
        return container.settings.kimi_context_window
    if provider == "deepseek":
        return container.settings.deepseek_context_window
    if provider == "zenmux":
        return container.settings.zenmux_context_window
    if provider == "vertex":
        return container.settings.vertex_context_window
    if provider == "codex":
        return container.settings.codex_context_window
    return container.settings.llama_ctx_size

def resolve_default_output_tokens(container: DIContainer, provider: str) -> int:
    """Resolve the default output budget per provider."""
    if provider == "nvidia":
        return container.settings.nvidia_max_tokens
    if provider == "deepseek":
        return container.settings.deepseek_max_tokens
    if provider == "zenmux":
        return container.settings.zenmux_max_tokens
    if provider == "vertex":
        return container.settings.vertex_max_tokens
    if provider == "kimi":
        return container.settings.kimi_max_tokens
    if provider == "codex":
        return container.settings.codex_max_tokens
    return container.settings.llama_max_tokens

def resolve_context_workspace_root_from_tool_context(tool_context: dict[str, Any]) -> str:
    """Resolve the workspace for flows that already have persisted tool_context."""
    workspace_root = tool_context.get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root
    return str(get_container().settings.tool_workspace_root_path)

def resolve_context_workspace_root(request: ChatRequest) -> str:
    """Resolve the workspace that should feed context and prompts."""
    tool_context = resolve_tool_context(request)
    return resolve_context_workspace_root_from_tool_context(tool_context)

async def _load_conversation_for_decision(
    conversation_id: str,
    session: AsyncSession,
) -> tuple[Any, Any]:
    container = get_container()
    conv_repo = await container.get_conversation_repo(session)
    try:
        parsed_id = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
    conversation = await conv_repo.get_by_id(parsed_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation, conv_repo

def _resume_request_from_tool_approval(
    conversation: Any,
    pending: dict[str, Any],
) -> ChatRequestDTO:
    resume = pending.get("resume_request")
    if not isinstance(resume, dict):
        resume = {}
    provider = resolve_provider(str(resume.get("provider") or "llama"))
    model = resolve_model(provider, str(resume.get("model") or "local-model"))
    tool_context = dict(resume.get("tool_context") or pending.get("tool_context") or {})
    return ChatRequestDTO(
        conversation_id=conversation.id,
        message=str(resume.get("message") or _last_user_message(conversation)),
        system_prompt=resume.get("system_prompt")
        if isinstance(resume.get("system_prompt"), str)
        else None,
        stream=True,
        temperature=float(resume.get("temperature", 0.7)),
        max_tokens=int(resume.get("max_tokens", -1)),
        provider=provider,
        model=model,
        prompt_mode=resolve_prompt_mode(str(resume.get("prompt_mode") or "auto")),
        reasoning_level=(
            str(resume["reasoning_level"]) if resume.get("reasoning_level") is not None else None
        ),
        reasoning_budget_tokens=(
            int(resume["reasoning_budget_tokens"])
            if resume.get("reasoning_budget_tokens") is not None
            else None
        ),
        tools_enabled=bool(resume.get("tools_enabled", True)),
        allowed_tools=(
            [str(item) for item in resume["allowed_tools"]]
            if isinstance(resume.get("allowed_tools"), list)
            else None
        ),
        tool_context=tool_context,
        max_tool_iterations=(
            int(resume["max_tool_iterations"])
            if resume.get("max_tool_iterations") is not None
            else None
        ),
        context_attachments=(
            [dict(item) for item in resume["context_attachments"] if isinstance(item, dict)]
            if isinstance(resume.get("context_attachments"), list)
            else []
        ),
    )

def _create_chat_use_case(
    *,
    container: DIContainer,
    conv_repo: Any,
    llm_backend: LLMBackendRepository,
    provider: str,
    context_workspace_root: str,
) -> ChatCompletionUseCase:
    return ChatCompletionUseCase(
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

async def _approve_pending_tool_call(
    *,
    request: ToolApprovalDecisionRequest,
    conversation: Any,
    conv_repo: Any,
    container: DIContainer,
) -> tuple[ChatCompletionUseCase, ChatRequestDTO, dict[str, Any], Any]:
    pending = _require_tool_approval(conversation.metadata, request.approval_id)
    resume_request = _resume_request_from_tool_approval(conversation, pending)
    llm_backend = container.get_llm_backend(resume_request.provider)
    use_case = _create_chat_use_case(
        container=container,
        conv_repo=conv_repo,
        llm_backend=llm_backend,
        provider=resume_request.provider,
        context_workspace_root=resolve_context_workspace_root_from_tool_context(
            resume_request.tool_context
        ),
    )
    tool = container.get_tool_registry().get(str(pending["tool_name"]))
    if tool is None:
        raise HTTPException(
            status_code=404, detail=f"Tool not found: {pending['tool_name']}"
        )

    context = use_case._build_tool_context(resume_request, conversation)
    arguments = dict(pending.get("arguments") or {})
    expected_hash = str(
        pending.get("args_hash")
        or canonical_args_hash(
            "chat.tool_approval",
            {
                "tool_call_id": pending.get("tool_call_id"),
                "tool_name": pending.get("tool_name"),
                "arguments": arguments,
            },
        )
    )
    if not request.args_hash or request.args_hash != expected_hash:
        raise HTTPException(status_code=403, detail="Tool approval argument hash mismatch.")
    validation = await tool.validate_input(arguments, context)
    if validation is not None and not validation.allowed:
        raise HTTPException(
            status_code=400, detail=validation.message or "Invalid tool input."
        )

    call = ToolCall(
        id=str(pending["tool_call_id"]),
        name=str(pending["tool_name"]),
        arguments=arguments,
    )
    result = await tool.call(arguments, context, call)
    await use_case._capture_operational_tool_result(
        resume_request,
        conversation,
        call,
        result,
        context,
    )
    use_case._apply_tool_state_result(result, conversation)
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content=result.content,
            tool_call_id=result.tool_call_id,
            metadata={
                "tool_name": result.tool_name,
                "status": result.status.value,
                "is_error": result.is_error,
                "approved": True,
                "data": result.data,
                **result.metadata,
            },
        )
    )
    conversation.metadata[PENDING_TOOL_APPROVAL_KEY] = {
        **pending,
        "status": "approved",
        "result_status": result.status.value,
    }
    conversation.metadata["session_status"] = "running"
    if not resume_request.tool_context.get("permission_mode"):
        conversation.metadata["permission_mode"] = "accept_edits"
    await conv_repo.update(conversation)
    return use_case, resume_request, pending, result

async def _answer_pending_user_question(
    *,
    request: UserQuestionResponseRequest,
    conversation: Any,
    conv_repo: Any,
    container: DIContainer,
) -> tuple[ChatCompletionUseCase, ChatRequestDTO, dict[str, Any], dict[str, Any]]:
    pending = _require_user_question(conversation.metadata, request.approval_id)
    resume_request = _resume_request_from_tool_approval(conversation, pending)
    llm_backend = container.get_llm_backend(resume_request.provider)
    use_case = _create_chat_use_case(
        container=container,
        conv_repo=conv_repo,
        llm_backend=llm_backend,
        provider=resume_request.provider,
        context_workspace_root=resolve_context_workspace_root_from_tool_context(
            resume_request.tool_context
        ),
    )
    answer_payload = {
        "type": "ask_user_question_answer",
        "questions": pending.get("questions") or [],
        "answers": request.answers,
        "content": json.dumps(request.answers, ensure_ascii=False),
    }
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content=json.dumps(answer_payload, ensure_ascii=False),
            tool_call_id=str(pending["tool_call_id"]),
            metadata={
                "tool_name": str(pending["tool_name"]),
                "status": ToolExecutionStatus.COMPLETED.value,
                "is_error": False,
                "answered": True,
                "data": answer_payload,
            },
        )
    )
    conversation.metadata[PENDING_USER_QUESTION_KEY] = {
        **pending,
        "status": "answered",
        "answers": request.answers,
    }
    await conv_repo.update(conversation)
    return use_case, resume_request, pending, answer_payload

register_model_listing_routes(router)
register_plan_approval_routes(router)
register_tool_approval_routes(router)
register_team_chat_routes(router)

@router.get("/teams")
async def list_teams() -> dict[str, Any]:
    """List built-in Team Mode presets."""

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
    container = get_container()
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
    container = get_container()
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

