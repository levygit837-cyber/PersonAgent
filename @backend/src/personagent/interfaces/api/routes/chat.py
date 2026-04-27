"""Rotas de chat da API FastAPI."""

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
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
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
    LLMBackendConnectionError,
    LLMBackendError,
)
from personagent.domain.models.conversation import Message, Role
from personagent.domain.prompts.skills import discover_skills
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolExecutionStatus
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.models import TeamRunORM
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
    """Request body para chat completion."""

    conversation_id: str | None = Field(default=None, description="ID da conversa existente")
    message: str = Field(..., min_length=1, description="Mensagem do usuário")
    system_prompt: str | None = Field(default=None, description="Prompt de sistema")
    stream: bool = Field(default=True, description="Se deve retornar em streaming")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=-1, ge=-1)
    provider: str = Field(
        default="llama",
        description="Provider de inferência: llama, nvidia ou vertex",
    )
    model: str = Field(default="local-model", description="Modelo a ser usado para inferência")
    prompt_mode: str = Field(
        default="auto",
        description="Modo de system prompt: auto, writing, exploring ou research.",
    )
    workspace_root: str | None = Field(
        default=None,
        description="Workspace local selecionado para ferramentas.",
    )
    reasoning_level: str | None = Field(
        default=None,
        description="Nível de reasoning: low, medium, high, xhigh ou max",
    )
    reasoning_budget_tokens: int | None = Field(
        default=None,
        ge=0,
        le=32768,
        description="Orçamento de tokens para thinking/reasoning",
    )
    tools_enabled: bool = Field(
        default=True,
        description="Se o modelo pode chamar ferramentas locais.",
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Allowlist opcional de ferramentas.",
    )
    tool_context: dict | None = Field(
        default=None,
        description="Contexto opcional de ferramentas: cwd e allowed_roots.",
    )
    max_tool_iterations: int | None = Field(
        default=None,
        ge=1,
        description="Limite de ciclos modelo -> ferramentas -> modelo.",
    )


class ChatResponse(BaseModel):
    """Response body para chat completion."""

    conversation_id: str
    message_id: str
    content: str
    reasoning_content: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    model: str | None = None
    provider: str | None = None
    images: list[dict[str, str]] = Field(default_factory=list)


class ChatCommandInfo(BaseModel):
    name: str
    slash_name: str
    description: str = ""
    argument_hint: str | None = None
    source: str
    path: str
    user_invocable: bool = True


class TeamRunStartRequest(ChatRequest):
    """Initial WebSocket payload for Team Mode."""

    type: str = Field(default="team.run.start")
    team_id: str | None = Field(default=DEFAULT_TEAM_ID)
    team_config: dict[str, Any] | None = None


class PlanDecisionRequest(BaseModel):
    """Decisão do usuário sobre um plano pendente."""

    conversation_id: str = Field(..., description="ID da conversa")
    approval_id: str | None = Field(default=None, description="ID da aprovação pendente")
    feedback: str | None = Field(default=None, description="Feedback opcional do usuário")


class ToolApprovalDecisionRequest(BaseModel):
    """Decisão do usuário sobre uma ferramenta pendente."""

    conversation_id: str = Field(..., description="ID da conversa")
    approval_id: str = Field(..., description="ID da aprovação pendente")


def encode_sse(data: dict) -> str:
    """Codifica um payload JSON como evento SSE."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependency para obter sessão de banco de dados."""
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


DB_SESSION_DEPENDENCY = Depends(get_db)


def resolve_reasoning_budget(request: ChatRequest) -> int | None:
    """Resolve o orçamento de reasoning a partir do nível ou valor explícito."""
    if request.reasoning_budget_tokens is not None:
        return request.reasoning_budget_tokens

    if request.reasoning_level is None:
        return None

    level = request.reasoning_level.strip().lower()
    if level not in REASONING_BUDGETS:
        raise HTTPException(
            status_code=400,
            detail=("reasoning_level inválido. Use low, medium, high, xhigh ou max."),
        )
    return REASONING_BUDGETS[level]


def resolve_provider(provider: str) -> str:
    """Normaliza e valida o provider de inferência."""
    normalized = provider.strip().lower()
    if normalized not in {"llama", "nvidia", "vertex"}:
        raise HTTPException(
            status_code=400,
            detail="provider inválido. Use llama, nvidia ou vertex.",
        )
    return normalized


def resolve_model(provider: str, model: str) -> str:
    """Resolve modelo default por provider sem quebrar o default local existente."""
    if provider == "nvidia" and (not model or model == "local-model"):
        return get_container().settings.nvidia_default_model
    if provider == "vertex" and (not model or model == "local-model"):
        return get_container().settings.vertex_default_model
    return model


def resolve_prompt_mode(prompt_mode: str | None) -> str:
    """Normaliza e valida o modo de prompt."""
    normalized = (prompt_mode or "auto").strip().lower()
    if normalized not in {"auto", "writing", "exploring", "research"}:
        raise HTTPException(
            status_code=400,
            detail="prompt_mode inválido. Use auto, writing, exploring ou research.",
        )
    return normalized


def resolve_tool_context(request: ChatRequest) -> dict:
    """Normaliza o contexto de ferramentas vindo do cliente."""
    tool_context = dict(request.tool_context or {})
    if request.workspace_root:
        tool_context.setdefault("workspace_root", request.workspace_root)
        tool_context.setdefault("cwd", request.workspace_root)
        tool_context.setdefault("allowed_roots", [request.workspace_root])
    return tool_context


def resolve_context_workspace_root(request: ChatRequest) -> str:
    """Resolve o workspace que deve alimentar contexto e prompt."""
    tool_context = resolve_tool_context(request)
    workspace_root = tool_context.get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root
    return str(get_container().settings.tool_workspace_root_path)


async def _load_conversation_for_decision(
    conversation_id: str,
    session: AsyncSession,
) -> tuple[Any, Any]:
    container = get_container()
    conv_repo = await container.get_conversation_repo(session)
    try:
        parsed_id = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="conversation_id inválido.") from exc
    conversation = await conv_repo.get_by_id(parsed_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation, conv_repo


def _require_plan_approval(
    *,
    state: dict[str, Any],
    request: PlanDecisionRequest,
) -> dict[str, Any]:
    if state.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Não há plano aguardando aprovação.")
    if request.approval_id and state.get("approval_id") != request.approval_id:
        raise HTTPException(
            status_code=409, detail="A aprovação do plano não corresponde ao estado atual."
        )
    if not state.get("approval_id"):
        raise HTTPException(status_code=409, detail="Plano pendente sem approval_id.")
    return state


def _require_tool_approval(metadata: dict[str, Any], approval_id: str) -> dict[str, Any]:
    pending = metadata.get(PENDING_TOOL_APPROVAL_KEY)
    if not isinstance(pending, dict):
        raise HTTPException(status_code=409, detail="Não há ferramenta aguardando aprovação.")
    if pending.get("approval_id") != approval_id:
        raise HTTPException(
            status_code=409, detail="A aprovação da ferramenta não corresponde ao estado atual."
        )
    if pending.get("status") != "awaiting_approval":
        raise HTTPException(status_code=409, detail="A ferramenta não está aguardando aprovação.")
    return dict(pending)


@router.get("/teams")
async def list_teams() -> dict[str, Any]:
    """List built-in Team Mode presets."""

    return {
        "object": "list",
        "data": [serialize_team_config(default_team_config())],
    }


@router.get("/models")
async def list_models(
    provider: str = Query(default="llama", description="Provider: llama, nvidia ou vertex"),
    capability: str | None = Query(default=None, description="Filtro de capability"),
    refresh: bool = Query(default=False, description="Ignora cache do catálogo"),
) -> dict:
    """Lista os modelos disponíveis no backend LLM."""
    container = get_container()
    resolved_provider = resolve_provider(provider)
    llm_backend = container.get_llm_backend(resolved_provider)
    if resolved_provider == "nvidia":
        list_provider_models = getattr(llm_backend, "list_models", None)
        if list_provider_models is None:
            raise HTTPException(status_code=500, detail="NVIDIA provider sem catálogo")
        return await list_provider_models(capability=capability, refresh=refresh)
    if resolved_provider == "vertex":
        list_provider_models = getattr(llm_backend, "list_models", None)
        if list_provider_models is None:
            raise HTTPException(status_code=500, detail="Vertex provider sem catálogo")
        return await list_provider_models(capability=capability, refresh=refresh)

    models_info = await llm_backend.get_model_info()
    return models_info if models_info else {"data": [], "object": "list"}


@router.get("/commands", response_model=list[ChatCommandInfo])
async def list_chat_commands(
    workspace_root: str | None = Query(default=None),
) -> list[ChatCommandInfo]:
    """List prompt slash commands and user-invocable skills for desktop autocomplete."""

    root = workspace_root or resolve_context_workspace_root(ChatRequest(message="placeholder"))
    container = get_container()
    commands = [
        ChatCommandInfo(
            name=command.name,
            slash_name=command.slash_name,
            description=command.description,
            argument_hint=command.argument_hint,
            source="command",
            path=str(command.path),
            user_invocable=True,
        )
        for command in container.create_command_registry().list_commands(root)
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
        )
        for skill in discover_skills(workspace_root=root)
        if skill.user_invocable
    ]
    by_name: dict[str, ChatCommandInfo] = {}
    for item in [*commands, *skills]:
        by_name.setdefault(item.slash_name, item)
    return sorted(by_name.values(), key=lambda item: item.slash_name)


@router.post("/completions", response_model=ChatResponse)
async def chat_completion(
    request: ChatRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> ChatResponse:
    """Envia uma mensagem e recebe uma resposta completa (não-streaming)."""
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
        context_window_tokens=container.settings.llama_ctx_size,
        default_output_tokens=container.settings.llama_max_tokens,
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
    )

    try:
        result = await use_case.execute(dto)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMBackendConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMBackendError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
    """Envia uma mensagem e recebe a resposta em streaming (Server-Sent Events)."""
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
        context_window_tokens=container.settings.llama_ctx_size,
        default_output_tokens=container.settings.llama_max_tokens,
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
            yield encode_sse({"event": "error", "error": str(exc), "status": 404})
        except ValueError as exc:
            yield encode_sse({"event": "error", "error": str(exc), "status": 400})
        except LLMBackendConnectionError as exc:
            yield encode_sse({"event": "error", "error": str(exc), "status": 503})
        except LLMBackendError as exc:
            yield encode_sse({"event": "error", "error": str(exc), "status": 500})
        except Exception as exc:
            logger.exception("chat_stream_unhandled_error")
            yield encode_sse(
                {
                    "event": "error",
                    "error": f"Erro inesperado no stream de chat: {exc}",
                    "status": 500,
                }
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


@router.post("/plan/approve")
async def approve_plan(
    request: PlanDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Aprova um plano pendente e retorna a mensagem de execução a ser injetada."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    state = _require_plan_approval(
        state=normalize_plan_state(conversation.metadata), request=request
    )
    plan_content = str(state.get("plan_content") or "").strip()
    if not plan_content:
        raise HTTPException(status_code=400, detail="Plano pendente sem conteúdo renderizável.")

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
    """Mantém o PlanMode ativo para revisão do plano."""

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
    """Cancela o PlanMode sem executar o plano."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    state = normalize_plan_state(conversation.metadata)
    if request.approval_id and state.get("approval_id") != request.approval_id:
        raise HTTPException(
            status_code=409, detail="A aprovação do plano não corresponde ao estado atual."
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
    """Aprova e executa uma ferramenta previamente pausada por permissão."""

    conversation, conv_repo = await _load_conversation_for_decision(
        request.conversation_id, session
    )
    pending = _require_tool_approval(conversation.metadata, request.approval_id)
    container = get_container()
    tool = container.get_tool_registry().get(str(pending["tool_name"]))
    if tool is None:
        raise HTTPException(
            status_code=404, detail=f"Ferramenta não encontrada: {pending['tool_name']}"
        )

    use_case = ChatCompletionUseCase(
        conversation_repo=conv_repo,
        llm_backend=container.get_llm_backend("llama"),
        tool_registry=container.get_tool_registry(),
        tool_runtime_config=container.get_tool_runtime_config(),
    )
    context = use_case._build_tool_context(
        ChatRequestDTO(
            conversation_id=conversation.id,
            message="",
            tool_context=dict(pending.get("tool_context") or {}),
        ),
        conversation,
    )
    arguments = dict(pending.get("arguments") or {})
    validation = await tool.validate_input(arguments, context)
    if validation is not None and not validation.allowed:
        raise HTTPException(
            status_code=400, detail=validation.message or "Entrada da ferramenta inválida."
        )

    call = ToolCall(
        id=str(pending["tool_call_id"]),
        name=str(pending["tool_name"]),
        arguments=arguments,
    )
    result = await tool.call(arguments, context, call)
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
    return {
        "event": "tool_approval_changed",
        "conversation_id": str(conversation.id),
        "approval_id": request.approval_id,
        "status": "approved",
        "tool_result": result.to_stream_dict(),
        "injected_message": "Continue after the approved tool result.",
    }


@router.post("/tools/reject")
async def reject_tool(
    request: ToolApprovalDecisionRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Rejeita uma ferramenta pendente."""

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
        "injected_message": "The requested tool call was rejected. Continue without it.",
    }


@router.websocket("/team/ws")
async def team_chat_websocket(websocket: WebSocket) -> None:
    """Run Team Mode over a bidirectional WebSocket."""

    await websocket.accept()
    trace_events: list[dict[str, Any]] = []
    status = "running"
    final_output: str | None = None
    final_output_parts: list[str] = []
    consensus: dict[str, Any] | None = None
    error_message: str | None = None
    conversation_id: str | None = None
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

        async with AsyncSessionLocal() as session:
            conv_repo = await container.get_conversation_repo(session)
            orchestrator = TeamChatOrchestrator(
                conversation_repo=conv_repo,
                llm_backend=llm_backend,
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
                tool_context=resolve_tool_context(start),
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
                    conversation_id = str(event.get("conversation_id") or conversation_id or "")
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
                    if event.get("event") == "team_consensus_failed":
                        status = "failed"
                        consensus = (
                            event.get("consensus")
                            if isinstance(event.get("consensus"), dict)
                            else consensus
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
        error_message = str(exc)
        event = {"event": "error", "error": error_message, "status": 400}
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    except LLMBackendError as exc:
        status = "failed"
        error_message = str(exc)
        event = {"event": "error", "error": error_message, "status": 500}
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    except Exception as exc:
        logger.exception("team_chat_websocket_unhandled_error")
        status = "failed"
        error_message = f"Unexpected Team Mode error: {exc}"
        event = {"event": "error", "error": error_message, "status": 500}
        trace_events.append(event)
        await _send_ws_json_safely(websocket, event)
    finally:
        if team_config_payload is not None:
            if final_output is None and final_output_parts:
                final_output = "".join(final_output_parts)
            await persist_team_run(
                conversation_id=conversation_id,
                status=status,
                team_config=team_config_payload,
                trace_events=trace_events,
                final_output=final_output,
                consensus=consensus,
                error_message=error_message,
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


async def _close_ws_safely(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except RuntimeError:
        return


async def persist_team_run(
    *,
    conversation_id: str | None,
    status: str,
    team_config: dict[str, Any],
    trace_events: list[dict[str, Any]],
    final_output: str | None,
    consensus: dict[str, Any] | None,
    error_message: str | None,
) -> None:
    """Persist a Team Mode run after the WebSocket closes."""

    try:
        compact_trace_events = [
            compact_event
            for event in trace_events
            if (compact_event := _team_trace_event_for_storage(event)) is not None
        ]
        async with AsyncSessionLocal() as session:
            run = TeamRunORM(
                conversation_id=UUID(conversation_id) if conversation_id else None,
                status=status,
                team_config=team_config,
                trace_events=compact_trace_events,
                final_output=final_output,
                consensus=consensus,
                error_message=error_message,
                finished_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
    except Exception:
        logger.exception("team_run_persist_failed", conversation_id=conversation_id)


def _team_trace_event_for_storage(event: dict[str, Any]) -> dict[str, Any] | None:
    """Keep Team Mode history useful without persisting token-by-token payloads."""

    if event.get("event") in {"agent_delta", "final_delta"}:
        return None

    compact = dict(event)
    for field in ("content", "reasoning_content", "final_output"):
        value = compact.pop(field, None)
        if isinstance(value, str) and value:
            compact[f"{field}_length"] = len(value)
        elif value not in (None, ""):
            compact[f"{field}_present"] = True
    return compact
