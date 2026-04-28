"""FastAPI chat routes."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
    normalize_plan_state,
    plan_mode_event,
    write_plan_state,
)
from personagent.application.services import NextStepSuggestionService, SessionMemoryService
from personagent.application.team_chat import (
    DEFAULT_TEAM_ID,
    TeamChatOrchestrator,
    TeamChatRequest,
    TeamValidationError,
    default_team_config,
    parse_team_config,
    serialize_team_config,
)
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    DatabaseError,
    InvalidRequestError,
    LLMBackendConnectionError,
    LLMBackendError,
    TeamValidationSystemError,
)
from personagent.domain.models.conversation import Message, Role
from personagent.domain.prompts.commands import CommandService
from personagent.domain.prompts.skills import discover_enabled_skills
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolExecutionStatus
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.models import (
    TeamBlackboardEventORM,
    TeamMemorySnapshotORM,
    TeamRunORM,
)
from personagent.interfaces.api.errors import error_event
from personagent.interfaces.config.di_container import DIContainer, get_container

router = APIRouter(prefix="/chat", tags=["chat"])
logger = structlog.get_logger(__name__)

REASONING_BUDGETS = {
    "low": 2048,
    "medium": 4082,
    "high": 8192,
    "xhigh": 16382,
    "max": 32768,
}
MAX_TEAM_WS_ERROR_LENGTH = 600


def resolve_session_memory_service(
    container: DIContainer,
    llm_backend: LLMBackendRepository,
) -> SessionMemoryService:
    update_backend = llm_backend if container.settings.chat_session_memory_updates_enabled else None
    return container.create_session_memory_service(update_backend)


def resolve_next_step_suggestion_service(
    container: DIContainer,
    llm_backend: LLMBackendRepository,
) -> NextStepSuggestionService | None:
    if not container.settings.chat_next_step_suggestions_enabled:
        return None
    return container.create_next_step_suggestion_service(llm_backend)


class ChatRequest(BaseModel):
    """Request body for chat completion."""

    conversation_id: str | None = Field(default=None, description="Existing conversation ID")
    message: str = Field(..., min_length=1, description="User message")
    system_prompt: str | None = Field(default=None, description="System prompt")
    stream: bool = Field(default=True, description="Whether to return a streaming response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=-1, ge=-1)
    provider: str = Field(
        default="llama",
        description="Inference provider: llama, nvidia, deepseek, vertex, kimi, or codex",
    )
    model: str = Field(default="local-model", description="Model to use for inference")
    prompt_mode: str = Field(
        default="auto",
        description="System prompt mode: auto, writing, exploring, or research.",
    )
    workspace_root: str | None = Field(
        default=None,
        description="Selected local workspace for tools.",
    )
    reasoning_level: str | None = Field(
        default=None,
        description="Reasoning level: low, medium, high, xhigh, or max",
    )
    reasoning_budget_tokens: int | None = Field(
        default=None,
        ge=0,
        le=32768,
        description="Token budget for thinking/reasoning",
    )
    tools_enabled: bool = Field(
        default=True,
        description="Whether the model can call local tools.",
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Optional tool allowlist.",
    )
    tool_context: dict | None = Field(
        default=None,
        description="Optional tool context: cwd and allowed_roots.",
    )
    max_tool_iterations: int | None = Field(
        default=None,
        ge=1,
        description="Limit for model -> tools -> model cycles.",
    )
    context_attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured model-visible context attachments.",
    )


class ChatResponse(BaseModel):
    """Response body for chat completion."""

    conversation_id: str
    message_id: str
    content: str
    reasoning_content: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    model: str | None = None
    provider: str | None = None
    images: list[dict[str, str]] = Field(default_factory=list)


class PromptPreviewResponse(BaseModel):
    """Prompt package preview for debugging prompt construction."""

    system_prompt: str
    user_context_message: str | None = None
    sections: list[str] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)
    dynamic_sections: list[str] = Field(default_factory=list)
    mode: str | None = None
    requested_mode: str | None = None
    analysis_source: str | None = None
    analysis_confidence: float | None = None
    line_count: int
    char_count: int
    estimated_tokens: int | None = None
    provider_data_boundary: str | None = None
    provider: str
    model: str


class ChatCommandInfo(BaseModel):
    name: str
    slash_name: str
    description: str = ""
    argument_hint: str | None = None
    source: str
    path: str
    user_invocable: bool = True
    should_query: bool = True
    ui_action: str | None = None


class TeamRunStartRequest(ChatRequest):
    """Initial WebSocket payload for Team Mode."""

    type: str = Field(default="team.run.start")
    team_id: str | None = Field(default=DEFAULT_TEAM_ID)
    team_config: dict[str, Any] | None = None


class PlanDecisionRequest(BaseModel):
    """User decision for a pending plan."""

    conversation_id: str = Field(..., description="Conversation ID")
    approval_id: str | None = Field(default=None, description="Pending approval ID")
    feedback: str | None = Field(default=None, description="Optional user feedback")


class ToolApprovalDecisionRequest(BaseModel):
    """User decision for a pending tool."""

    conversation_id: str = Field(..., description="Conversation ID")
    approval_id: str = Field(..., description="Pending approval ID")


class UserQuestionResponseRequest(BaseModel):
    """User answer for AskUserQuestion."""

    conversation_id: str = Field(..., description="Conversation ID")
    approval_id: str = Field(..., description="Pending question ID")
    answers: dict[str, Any] | list[Any] | str = Field(..., description="User answers")


def encode_sse(data: dict) -> str:
    """Encode a JSON payload as an SSE event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependency that provides a database session."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


DB_SESSION_DEPENDENCY = Depends(get_db)


def resolve_reasoning_budget(request: ChatRequest) -> int | None:
    """Resolve the reasoning budget from the level or explicit value."""
    if request.reasoning_budget_tokens is not None:
        return request.reasoning_budget_tokens

    if request.reasoning_level is None:
        return None

    level = request.reasoning_level.strip().lower()
    if level not in REASONING_BUDGETS:
        raise HTTPException(
            status_code=400,
            detail=("Invalid reasoning_level. Use low, medium, high, xhigh, or max."),
        )
    return REASONING_BUDGETS[level]


def resolve_provider(provider: str) -> str:
    """Normalize and validate the inference provider."""
    normalized = provider.strip().lower()
    if normalized not in {"llama", "nvidia", "deepseek", "vertex", "kimi", "codex"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid provider. Use llama, nvidia, deepseek, vertex, kimi, or codex.",
        )
    return normalized


def resolve_model(provider: str, model: str) -> str:
    """Resolve the default model per provider without breaking the existing local default."""
    if provider == "nvidia" and (not model or model == "local-model"):
        return get_container().settings.nvidia_default_model
    if provider == "deepseek" and (not model or model == "local-model"):
        return get_container().settings.deepseek_default_model
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
    if provider == "vertex":
        return container.settings.vertex_max_tokens
    if provider == "kimi":
        return container.settings.kimi_max_tokens
    if provider == "codex":
        return container.settings.codex_max_tokens
    return container.settings.llama_max_tokens


def resolve_prompt_mode(prompt_mode: str | None) -> str:
    """Normalize and validate the prompt mode."""
    normalized = (prompt_mode or "auto").strip().lower()
    if normalized not in {"auto", "writing", "exploring", "research"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid prompt_mode. Use auto, writing, exploring, or research.",
        )
    return normalized


def resolve_tool_context(request: ChatRequest) -> dict:
    """Normalize the tool context received from the client."""
    tool_context = dict(request.tool_context or {})
    if request.workspace_root:
        tool_context.setdefault("workspace_root", request.workspace_root)
        tool_context.setdefault("cwd", request.workspace_root)
        tool_context.setdefault("allowed_roots", [request.workspace_root])
    return tool_context


def resolve_context_workspace_root(request: ChatRequest) -> str:
    """Resolve the workspace that should feed context and prompts."""
    tool_context = resolve_tool_context(request)
    return resolve_context_workspace_root_from_tool_context(tool_context)


def resolve_context_workspace_root_from_tool_context(tool_context: dict[str, Any]) -> str:
    """Resolve the workspace for flows that already have persisted tool_context."""
    workspace_root = tool_context.get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root
    return str(get_container().settings.tool_workspace_root_path)


def resolve_team_workspace_id(request: ChatRequest, tool_context: dict[str, Any]) -> str | None:
    raw = tool_context.get("workspace_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    workspace_root = tool_context.get("workspace_root") or request.workspace_root
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root.strip()
    return None


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


def _require_plan_approval(
    *,
    state: dict[str, Any],
    request: PlanDecisionRequest,
) -> dict[str, Any]:
    if state.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="There is no plan awaiting approval.")
    if request.approval_id and state.get("approval_id") != request.approval_id:
        raise HTTPException(
            status_code=409, detail="The plan approval does not match the current state."
        )
    if not state.get("approval_id"):
        raise HTTPException(status_code=409, detail="Pending plan has no approval_id.")
    return state


def _require_tool_approval(metadata: dict[str, Any], approval_id: str) -> dict[str, Any]:
    pending = metadata.get(PENDING_TOOL_APPROVAL_KEY)
    if not isinstance(pending, dict):
        raise HTTPException(status_code=409, detail="There is no tool awaiting approval.")
    if pending.get("approval_id") != approval_id:
        raise HTTPException(
            status_code=409, detail="The tool approval does not match the current state."
        )
    if pending.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="The tool is not awaiting approval.")
    return dict(pending)


def _require_user_question(metadata: dict[str, Any], approval_id: str) -> dict[str, Any]:
    pending = metadata.get(PENDING_USER_QUESTION_KEY)
    if not isinstance(pending, dict):
        raise HTTPException(status_code=409, detail="There is no question awaiting an answer.")
    if pending.get("approval_id") != approval_id:
        raise HTTPException(
            status_code=409, detail="The pending question does not match the current state."
        )
    if pending.get("status") != "awaiting_answer":
        raise HTTPException(status_code=409, detail="The question is not awaiting an answer.")
    return dict(pending)


def _last_user_message(conversation: Any) -> str:
    for message in reversed(conversation.messages):
        if message.role == Role.USER and message.content.strip():
            return message.content
    return ""


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


@router.get("/teams")
async def list_teams() -> dict[str, Any]:
    """List built-in Team Mode presets."""

    return {
        "object": "list",
        "data": [serialize_team_config(default_team_config())],
    }


@router.get("/models")
async def list_models(
    provider: str = Query(default="llama", description="Provider: llama, nvidia, deepseek, vertex, kimi, or codex"),
    capability: str | None = Query(default=None, description="Capability filter"),
    refresh: bool = Query(default=False, description="Ignore the catalog cache"),
) -> dict:
    """List the models available from the LLM backend."""
    container = get_container()
    resolved_provider = resolve_provider(provider)
    llm_backend = container.get_llm_backend(resolved_provider)
    if resolved_provider in {"nvidia", "deepseek", "vertex", "kimi", "codex"}:
        list_provider_models = getattr(llm_backend, "list_models", None)
        if list_provider_models is None:
            raise HTTPException(status_code=500, detail=f"{resolved_provider} provider has no catalog")
        return await list_provider_models(capability=capability, refresh=refresh)

    models_info = await llm_backend.get_model_info()
    return models_info if models_info else {"data": [], "object": "list"}


@router.get("/auth/codex/status")
async def codex_auth_status() -> dict[str, Any]:
    """Return Codex CLI authentication state without exposing tokens."""
    container = get_container()
    llm_backend = container.get_llm_backend("codex")
    auth_status = getattr(llm_backend, "auth_status", None)
    if auth_status is None:
        raise HTTPException(status_code=500, detail="codex provider sem estado de auth")
    return auth_status()


@router.post("/auth/codex/logout")
async def codex_auth_logout() -> dict[str, Any]:
    """Executa `codex logout` para desconectar a conta do ChatGPT Subscription."""
    container = get_container()
    llm_backend = container.get_llm_backend("codex")
    logout = getattr(llm_backend, "logout", None)
    if logout is None:
        raise HTTPException(status_code=500, detail="codex provider sem logout")
    try:
        return await logout()
    except LLMBackendConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMBackendError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/commands", response_model=list[ChatCommandInfo])
async def list_chat_commands(
    workspace_root: str | None = Query(default=None),
) -> list[ChatCommandInfo]:
    """List prompt slash commands and user-invocable skills for desktop autocomplete."""

    root = workspace_root or resolve_context_workspace_root(ChatRequest(message="placeholder"))
    container = get_container()
    skill_roots = tuple(str(path) for path in container.get_tool_runtime_config().skill_roots)
    command_service = CommandService(container.create_command_registry())
    commands = [
        ChatCommandInfo(
            name=command.name,
            slash_name=command.slash_name,
            description=command.description,
            argument_hint=command.argument_hint,
            source="command",
            path=str(command.path),
            user_invocable=True,
            should_query=not command.disable_model_invocation,
        )
        for command in command_service.list_prompt_commands(root)
    ]
    builtins = [
        ChatCommandInfo(
            name=command.name,
            slash_name=command.slash_name,
            description=command.description,
            argument_hint=command.argument_hint,
            source="builtin",
            path=command.path,
            user_invocable=True,
            should_query=command.should_query,
            ui_action=command.ui_action,
        )
        for command in command_service.list_builtin_commands()
    ]
    skills = [
        ChatCommandInfo(
            name=skill.name,
            slash_name=skill.slash_name,
            description=skill.description,
            argument_hint=skill.argument_hint,
            source="skill",
            path=str(skill.path),
            user_invocable=skill.user_invocable,
            should_query=True,
        )
        for skill in discover_enabled_skills(
            workspace_root=root,
            cwd=root,
            extra_roots=skill_roots,
        )
        if skill.user_invocable
    ]
    by_name: dict[str, ChatCommandInfo] = {}
    for item in [*commands, *skills, *builtins]:
        by_name.setdefault(item.slash_name, item)
    return sorted(by_name.values(), key=lambda item: item.slash_name)


@router.post("/prompt/preview", response_model=PromptPreviewResponse)
async def prompt_preview(
    request: ChatRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> PromptPreviewResponse:
    """Build and return the prompt package without running a completion."""

    container = get_container()
    provider = resolve_provider(request.provider)
    model = resolve_model(provider, request.model)
    prompt_mode = resolve_prompt_mode(request.prompt_mode)
    llm_backend = container.get_llm_backend(provider)
    conv_repo = await container.get_conversation_repo(session)
    context_workspace_root = resolve_context_workspace_root(request)
    use_case = _create_chat_use_case(
        container=container,
        conv_repo=conv_repo,
        llm_backend=llm_backend,
        provider=provider,
        context_workspace_root=context_workspace_root,
    )

    try:
        conversation_id = UUID(request.conversation_id) if request.conversation_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
    dto = ChatRequestDTO(
        conversation_id=conversation_id,
        message=request.message,
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
    )

    try:
        return PromptPreviewResponse(**await use_case.preview_prompt(dto))
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    )

    conversation_id = None
    if request.conversation_id:
        conversation_id = UUID(request.conversation_id)

    dto = ChatRequestDTO(
        conversation_id=conversation_id,
        message=request.message,
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
    )

    conversation_id = None
    if request.conversation_id:
        conversation_id = UUID(request.conversation_id)

    dto = ChatRequestDTO(
        conversation_id=conversation_id,
        message=request.message,
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


@router.post("/plan/approve")
async def approve_plan(
    request: PlanDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Approve a pending plan and return the execution message to inject."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    state = _require_plan_approval(
        state=normalize_plan_state(conversation.metadata), request=request
    )
    plan_content = str(state.get("plan_content") or "").strip()
    if not plan_content:
        raise HTTPException(status_code=400, detail="Pending plan has no renderable content.")

    injected_message = f"Implement the following plan:\n\n{plan_content}"
    feedback = (request.feedback or "").strip()
    if feedback:
        injected_message = f"{injected_message}\n\nUser feedback:\n\n{feedback}"

    state.update(
        {
            "active": False,
            "status": "approved",
            "approval_id": None,
            "feedback": feedback or None,
            "cancelled": False,
            "pending_injected_message": injected_message,
        }
    )
    write_plan_state(conversation.metadata, state)
    await conv_repo.update(conversation)

    return {
        **plan_mode_event(str(conversation.id), state),
        "injected_message": injected_message,
    }


@router.post("/plan/continue")
async def continue_plan(
    request: PlanDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Keep PlanMode active for plan revision."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    state = _require_plan_approval(
        state=normalize_plan_state(conversation.metadata), request=request
    )
    feedback = (request.feedback or "").strip()
    state.update(
        {
            "active": True,
            "status": "draft",
            "approval_id": None,
            "feedback": feedback or None,
            "cancelled": False,
        }
    )
    write_plan_state(conversation.metadata, state)
    await conv_repo.update(conversation)

    suggested_message = (
        f"Continue planning with this feedback:\n\n{feedback}"
        if feedback
        else "Continue planning. Revise the plan and request approval again when ready."
    )
    return {
        **plan_mode_event(str(conversation.id), state),
        "suggested_message": suggested_message,
    }


@router.post("/plan/cancel")
async def cancel_plan(
    request: PlanDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Cancel PlanMode without executing the plan."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    state = normalize_plan_state(conversation.metadata)
    if request.approval_id and state.get("approval_id") != request.approval_id:
        raise HTTPException(
            status_code=409, detail="The plan approval does not match the current state."
        )
    state.update(
        {
            "active": False,
            "status": "cancelled",
            "approval_id": None,
            "feedback": (request.feedback or "").strip() or state.get("feedback"),
            "cancelled": True,
        }
    )
    write_plan_state(conversation.metadata, state)
    await conv_repo.update(conversation)

    return plan_mode_event(str(conversation.id), state)


@router.post("/tools/approve")
async def approve_tool(
    request: ToolApprovalDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Approve and execute a tool previously paused by permission handling."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    container = get_container()
    _use_case, _resume_request, _pending, result = await _approve_pending_tool_call(
        request=request,
        conversation=conversation,
        conv_repo=conv_repo,
        container=container,
    )
    return {
        "event": "tool_approval_changed",
        "conversation_id": str(conversation.id),
        "approval_id": request.approval_id,
        "status": "approved",
        "tool_result": result.to_stream_dict(),
        "resume_available": True,
    }


@router.post("/tools/approve/stream")
async def approve_tool_stream(
    request: ToolApprovalDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> StreamingResponse:
    """Approve a tool, persist the tool_result, and resume the model over SSE."""

    async def event_generator() -> AsyncIterator[str]:
        try:
            conversation, conv_repo = await _load_conversation_for_decision(
                request.conversation_id, session
            )
            container = get_container()
            use_case, resume_request, pending, result = await _approve_pending_tool_call(
                request=request,
                conversation=conversation,
                conv_repo=conv_repo,
                container=container,
            )
            pending_arguments = dict(pending.get("arguments") or {})
            yield encode_sse(
                {
                    "event": "tool_approval_changed",
                    "conversation_id": str(conversation.id),
                    "approval_id": request.approval_id,
                    "status": "approved",
                    "tool_result": result.to_stream_dict(),
                }
            )
            yield encode_sse(
                {
                    "event": "tool_result",
                    "conversation_id": str(conversation.id),
                    "tool_call_id": result.tool_call_id,
                    "tool_name": result.tool_name,
                    "tool_status": result.status.value,
                    "tool_input": pending_arguments,
                    "tool_result": result.content,
                    "tool_error": result.content if result.is_error else None,
                    "tool_data": result.data,
                    "metadata": {**result.metadata, "approved": True},
                }
            )

            async for chunk in use_case.resume_after_tool_result_stream(resume_request):
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
        except HTTPException as exc:
            yield encode_sse(error_event(exc))
        except Exception as exc:
            logger.exception("tool_approval_stream_unhandled_error")
            yield encode_sse(
                error_event(exc, default_message="Unexpected error while approving tool.")
            )
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


@router.post("/tools/reject")
async def reject_tool(
    request: ToolApprovalDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Reject a pending tool."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    pending = _require_tool_approval(conversation.metadata, request.approval_id)
    conversation.metadata[PENDING_TOOL_APPROVAL_KEY] = {
        **pending,
        "status": "rejected",
    }
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="Tool call rejected by the user.",
            tool_call_id=str(pending["tool_call_id"]),
            metadata={
                "tool_name": str(pending["tool_name"]),
                "status": ToolExecutionStatus.ERROR.value,
                "is_error": True,
                "rejected": True,
            },
        )
    )
    await conv_repo.update(conversation)
    return {
        "event": "tool_approval_changed",
        "conversation_id": str(conversation.id),
        "approval_id": request.approval_id,
        "status": "rejected",
        "resume_available": False,
    }


@router.post("/user-question/respond/stream")
async def answer_user_question_stream(
    request: UserQuestionResponseRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> StreamingResponse:
    """Persist an AskUserQuestion answer and resume the model over SSE."""

    async def event_generator() -> AsyncIterator[str]:
        try:
            conversation, conv_repo = await _load_conversation_for_decision(
                request.conversation_id, session
            )
            container = get_container()
            use_case, resume_request, pending, answer_payload = await _answer_pending_user_question(
                request=request,
                conversation=conversation,
                conv_repo=conv_repo,
                container=container,
            )
            yield encode_sse(
                {
                    "event": "ask_user_question_answered",
                    "conversation_id": str(conversation.id),
                    "approval_id": request.approval_id,
                    "tool_call_id": str(pending["tool_call_id"]),
                    "tool_name": str(pending["tool_name"]),
                    "answers": request.answers,
                }
            )
            yield encode_sse(
                {
                    "event": "tool_result",
                    "conversation_id": str(conversation.id),
                    "tool_call_id": str(pending["tool_call_id"]),
                    "tool_name": str(pending["tool_name"]),
                    "tool_status": ToolExecutionStatus.COMPLETED.value,
                    "tool_result": json.dumps(answer_payload, ensure_ascii=False),
                    "tool_error": None,
                    "tool_data": answer_payload,
                    "metadata": {"answered": True},
                }
            )

            async for chunk in use_case.resume_after_tool_result_stream(resume_request):
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
        except HTTPException as exc:
            yield encode_sse(error_event(exc))
        except Exception as exc:
            logger.exception("user_question_stream_unhandled_error")
            yield encode_sse(
                error_event(exc, default_message="Unexpected error while answering question.")
            )
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


@router.websocket("/team/ws")
async def team_chat_websocket(websocket: WebSocket) -> None:
    """Run Team Mode over a bidirectional WebSocket."""

    await websocket.accept()
    trace_events: list[dict[str, Any]] = []
    status = "running"
    final_output: str | None = None
    final_output_parts: list[str] = []
    consensus: dict[str, Any] | None = None
    blackboard_snapshot: dict[str, Any] | None = None
    team_memory_snapshot: dict[str, Any] | None = None
    error_message: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    workspace_id: str | None = None
    team_config_payload: dict[str, Any] | None = None
    stop_event = asyncio.Event()

    try:
        raw_start = await websocket.receive_json()
        start = TeamRunStartRequest.model_validate(raw_start)
        if start.type != "team.run.start":
            raise ValueError("First Team Mode WebSocket message must be team.run.start")

        provider = resolve_provider(start.provider)
        model = resolve_model(provider, start.model)
        team = parse_team_config(start.team_id, start.team_config)
        team_config_payload = serialize_team_config(team)
        container = get_container()
        llm_backend = container.get_llm_backend(provider)
        initial_tool_context = resolve_tool_context(start)
        workspace_id = resolve_team_workspace_id(start, initial_tool_context)
        loaded_memory = await load_team_memory_snapshot(workspace_id)
        if loaded_memory:
            initial_tool_context["team_memory_snapshot"] = loaded_memory
        if workspace_id:
            initial_tool_context["workspace_id"] = workspace_id

        async with AsyncSessionLocal() as session:
            conv_repo = await container.get_conversation_repo(session)
            tool_registry = getattr(container, "get_tool_registry", lambda: None)() if start.tools_enabled else None
            tool_runtime_config = (
                getattr(container, "get_tool_runtime_config", lambda: None)()
                if start.tools_enabled
                else None
            )
            orchestrator = TeamChatOrchestrator(
                conversation_repo=conv_repo,
                llm_backend=llm_backend,
                tool_registry=tool_registry,
                tool_runtime_config=tool_runtime_config,
                session_title_service=getattr(container, "get_session_title_service", lambda: None)(),
            )
            request = TeamChatRequest(
                conversation_id=UUID(start.conversation_id) if start.conversation_id else None,
                message=start.message,
                system_prompt=start.system_prompt,
                provider=provider,
                model=model,
                temperature=start.temperature,
                max_tokens=start.max_tokens,
                reasoning_level=start.reasoning_level,
                reasoning_budget_tokens=resolve_reasoning_budget(start),
                workspace_root=start.workspace_root,
                tool_context=initial_tool_context,
                allowed_tools=start.allowed_tools,
                max_tool_iterations=start.max_tool_iterations,
            )
            stop_task = asyncio.create_task(_watch_team_stop(websocket, stop_event))
            try:
                async for event in orchestrator.execute(
                    request=request,
                    team=team,
                    cancel_event=stop_event,
                ):
                    trace_event = _team_trace_event_for_storage(event)
                    if trace_event is not None:
                        trace_events.append(trace_event)
                    if event.get("run_id"):
                        run_id = str(event.get("run_id"))
                    conversation_id = str(event.get("conversation_id") or conversation_id or "")
                    if event.get("event") == "team_run_started" and run_id:
                        await persist_team_run_started(
                            run_id=run_id,
                            conversation_id=conversation_id,
                            workspace_id=workspace_id,
                            team_config=team_config_payload,
                        )
                    if event.get("event") == "blackboard_event" and run_id:
                        await persist_team_blackboard_event(
                            run_id=run_id,
                            conversation_id=conversation_id,
                            workspace_id=workspace_id,
                            event=event,
                        )
                    if event.get("event") == "blackboard_snapshot" and isinstance(
                        event.get("snapshot"), dict
                    ):
                        blackboard_snapshot = event.get("snapshot")
                    if event.get("event") == "final_delta":
                        final_output_parts.append(str(event.get("content") or ""))
                    if event.get("event") == "consensus_reached":
                        consensus = (
                            event.get("consensus")
                            if isinstance(event.get("consensus"), dict)
                            else None
                        )
                    if event.get("event") == "team_run_completed":
                        status = "completed"
                        final_output = str(
                            event.get("final_output") or "".join(final_output_parts) or ""
                        )
                        consensus = (
                            event.get("consensus")
                            if isinstance(event.get("consensus"), dict)
                            else consensus
                        )
                        blackboard_snapshot = (
                            event.get("blackboard_snapshot")
                            if isinstance(event.get("blackboard_snapshot"), dict)
                            else blackboard_snapshot
                        )
                        team_memory_snapshot = (
                            event.get("team_memory_snapshot")
                            if isinstance(event.get("team_memory_snapshot"), dict)
                            else team_memory_snapshot
                        )
                    if event.get("event") == "team_consensus_failed":
                        status = "failed"
                        consensus = (
                            event.get("consensus")
                            if isinstance(event.get("consensus"), dict)
                            else consensus
                        )
                        blackboard_snapshot = (
                            event.get("blackboard_snapshot")
                            if isinstance(event.get("blackboard_snapshot"), dict)
                            else blackboard_snapshot
                        )
                        team_memory_snapshot = (
                            event.get("team_memory_snapshot")
                            if isinstance(event.get("team_memory_snapshot"), dict)
                            else team_memory_snapshot
                        )
                    if event.get("event") == "team_run_cancelled":
                        status = "cancelled"
                    await websocket.send_json(event)
            finally:
                stop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_task

    except WebSocketDisconnect:
        status = "cancelled"
    except (TeamValidationError, ValueError) as exc:
        status = "failed"
        error = TeamValidationSystemError(str(exc))
        error_message = error.user_message
        event = error_event(error)
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    except LLMBackendError as exc:
        status = "failed"
        error_message = exc.user_message
        event = error_event(exc)
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    except SQLAlchemyError as exc:
        logger.exception("team_chat_websocket_database_error")
        status = "failed"
        error_message = _compact_team_error_message("Team Mode database error", exc)
        event = error_event(DatabaseError(error_message, cause=exc))
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    except Exception as exc:
        logger.exception("team_chat_websocket_unhandled_error")
        status = "failed"
        error_message = _compact_team_error_message("Unexpected Team Mode error", exc)
        event = error_event(exc, default_message=error_message)
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    finally:
        if team_config_payload is not None:
            if final_output is None and final_output_parts:
                final_output = "".join(final_output_parts)
            await persist_team_run(
                run_id=run_id,
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                status=status,
                team_config=team_config_payload,
                trace_events=trace_events,
                blackboard_snapshot=blackboard_snapshot,
                team_memory_snapshot=team_memory_snapshot,
                final_output=final_output,
                consensus=consensus,
                error_message=error_message,
            )
            if workspace_id and team_memory_snapshot is not None:
                await persist_team_memory_snapshot(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    snapshot=team_memory_snapshot,
                )
        await _close_ws_safely(websocket)


async def _watch_team_stop(websocket: WebSocket, stop_event) -> None:
    while not stop_event.is_set():
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            stop_event.set()
            return
        except RuntimeError:
            stop_event.set()
            return
        if isinstance(message, dict) and message.get("type") == "team.run.stop":
            stop_event.set()
            return


async def _send_ws_json_safely(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except RuntimeError:
        return


def _compact_team_error_message(prefix: str, exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if "team_runs.run_id" in text and "UndefinedColumnError" in text:
        return (
            f"{prefix}: local database schema is missing Team Mode columns. "
            "Restart the backend or run database initialization to apply the Team Mode schema."
        )
    if len(text) > MAX_TEAM_WS_ERROR_LENGTH:
        text = f"{text[:MAX_TEAM_WS_ERROR_LENGTH].rstrip()}..."
    return f"{prefix}: {text}"


async def _close_ws_safely(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except RuntimeError:
        return


async def persist_team_run_started(
    *,
    run_id: str,
    conversation_id: str | None,
    team_config: dict[str, Any] | None,
    workspace_id: str | None = None,
) -> None:
    """Create the Team Mode run row while the WebSocket is still active."""

    try:
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(select(TeamRunORM).where(TeamRunORM.run_id == run_id))
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(
                TeamRunORM(
                    run_id=run_id,
                    conversation_id=UUID(conversation_id) if conversation_id else None,
                    workspace_id=workspace_id,
                    status="running",
                    team_config=team_config or {},
                    trace_events=[],
                )
            )
            await session.commit()
    except Exception:
        logger.exception("team_run_started_persist_failed", run_id=run_id)


async def persist_team_blackboard_event(
    *,
    run_id: str,
    conversation_id: str | None,
    event: dict[str, Any],
    workspace_id: str | None = None,
) -> None:
    """Persist one Blackboard journal event as soon as it is emitted."""

    try:
        async with AsyncSessionLocal() as session:
            session.add(
                TeamBlackboardEventORM(
                    run_id=run_id,
                    conversation_id=UUID(conversation_id) if conversation_id else None,
                    workspace_id=workspace_id,
                    sequence=int(event.get("sequence") or 0),
                    phase=str(event.get("phase") or ""),
                    round=event.get("round") if isinstance(event.get("round"), int) else None,
                    agent_id=str(event.get("agent_id") or "") or None,
                    event_type=str(event.get("event_type") or "blackboard_event"),
                    payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
                )
            )
            await session.commit()
    except Exception:
        logger.exception("team_blackboard_event_persist_failed", run_id=run_id)


async def load_team_memory_snapshot(workspace_id: str | None) -> dict[str, Any] | None:
    """Load the compact Team memory snapshot for a workspace."""

    if not workspace_id:
        return None
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(TeamMemorySnapshotORM).where(
                        TeamMemorySnapshotORM.workspace_id == workspace_id
                    )
                )
            ).scalar_one_or_none()
            snapshot = row.snapshot if row is not None else None
            return snapshot if isinstance(snapshot, dict) else None
    except Exception:
        logger.exception("team_memory_snapshot_load_failed", workspace_id=workspace_id)
        return None


async def persist_team_memory_snapshot(
    *,
    workspace_id: str,
    run_id: str | None,
    snapshot: dict[str, Any],
) -> None:
    """Upsert the compact Team memory snapshot for a workspace."""

    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(TeamMemorySnapshotORM).where(
                        TeamMemorySnapshotORM.workspace_id == workspace_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = TeamMemorySnapshotORM(workspace_id=workspace_id)
                session.add(row)
            row.snapshot = snapshot
            row.last_run_id = run_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        logger.exception("team_memory_snapshot_persist_failed", workspace_id=workspace_id)


async def persist_team_run(
    *,
    run_id: str | None,
    conversation_id: str | None,
    status: str,
    team_config: dict[str, Any],
    trace_events: list[dict[str, Any]],
    blackboard_snapshot: dict[str, Any] | None,
    final_output: str | None,
    consensus: dict[str, Any] | None,
    error_message: str | None,
    workspace_id: str | None = None,
    team_memory_snapshot: dict[str, Any] | None = None,
) -> None:
    """Persist a Team Mode run after the WebSocket closes."""

    try:
        compact_trace_events = [
            compact_event
            for event in trace_events
            if (compact_event := _team_trace_event_for_storage(event)) is not None
        ]
        async with AsyncSessionLocal() as session:
            run = None
            if run_id:
                run = (
                    await session.execute(select(TeamRunORM).where(TeamRunORM.run_id == run_id))
                ).scalar_one_or_none()
            if run is None:
                run = TeamRunORM(run_id=run_id)
                session.add(run)
            run.conversation_id = UUID(conversation_id) if conversation_id else None
            run.workspace_id = workspace_id
            run.status = status
            run.team_config = team_config
            run.trace_events = compact_trace_events
            run.blackboard_snapshot = blackboard_snapshot or team_memory_snapshot
            run.final_output = final_output
            run.consensus = consensus
            run.error_message = error_message
            run.finished_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        logger.exception("team_run_persist_failed", conversation_id=conversation_id)


def _team_trace_event_for_storage(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep Team Mode history useful without persisting token-by-token payloads."""

    if event.get("event") in {"agent_delta", "final_delta"}:
        return None

    compact = dict(event)
    if compact.get("event") == "blackboard_snapshot":
        snapshot = compact.pop("snapshot", None)
        if isinstance(snapshot, dict):
            compact["snapshot_entry_count"] = snapshot.get("entry_count", 0)
            compact["snapshot_latest_sequence"] = snapshot.get("latest_sequence", 0)
    for field in ("content", "reasoning_content", "final_output"):
        value = compact.pop(field, None)
        if isinstance(value, str) and value:
            compact[f"{field}_length"] = len(value)
        elif value not in (None, ""):
            compact[f"{field}_present"] = True
    return compact
