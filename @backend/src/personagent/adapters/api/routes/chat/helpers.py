"""Shared helpers, models, and constants for chat routes."""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.adapters.api.routes.workspace_grants import resolve_workspace_root
from personagent.adapters.composition import DIContainer
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
)
from personagent.application.services import NextStepSuggestionService, SessionMemoryService
from personagent.application.team_chat import DEFAULT_TEAM_ID
from personagent.domain.conversation.models import Role
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.infrastructure.persistence.database import AsyncSessionLocal

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
    """Request body for chat completion."""

    conversation_id: str | None = Field(default=None, description="Existing conversation ID")
    message: str = Field(..., min_length=1, description="User message")
    system_prompt: str | None = Field(default=None, description="System prompt")
    stream: bool = Field(default=True, description="Whether to return a streaming response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=-1, ge=-1)
    provider: str = Field(
        default="deepseek",
        description="Inference provider: llama, nvidia, deepseek, zenmux, vertex, kimi, or codex",
    )
    model: str = Field(default="deepseek-v4-flash", description="Model to use for inference")
    prompt_mode: str = Field(
        default="auto",
        description="System prompt mode: auto, writing, exploring, or research.",
    )
    workspace_root: str | None = Field(
        default=None,
        description="Selected local workspace for tools.",
    )
    workspace_id: str | None = Field(
        default=None,
        description="Granted workspace id.",
    )
    reasoning_level: str | None = Field(
        default=None,
        description="Reasoning level: low, medium, high, xhigh, or max",
    )
    reasoning_budget_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Optional token budget for thinking/reasoning. Null means no explicit app cap.",
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
        description="Optional limit for model -> tools -> model cycles. Null means unlimited.",
    )
    context_attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured model-visible context attachments.",
    )
    plan_mode_requested: bool = Field(
        default=False,
        description="Activate planning mode for this turn.",
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
    images: list[dict[str, Any]] = Field(default_factory=list)


class PromptPreviewResponse(BaseModel):
    """Prompt package preview for debugging prompt construction."""

    system_prompt: str
    user_context_message: str | None = None
    sections: list[str] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)
    dynamic_sections: list[str] = Field(default_factory=list)
    agent_states: list[str] = Field(default_factory=list)
    agent_state_source: str | None = None
    agent_state_reason: str | None = None
    state_sections_used: list[str] = Field(default_factory=list)
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
    args_hash: str | None = Field(default=None, description="Pending tool argument hash")


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
    if normalized not in {"llama", "nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid provider. Use llama, nvidia, deepseek, zenmux, vertex, kimi, or codex.",
        )
    return normalized


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
    if request.workspace_id or request.workspace_root:
        try:
            workspace_root = str(
                resolve_workspace_root(
                    workspace_id=request.workspace_id,
                    workspace_root=request.workspace_root,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if request.workspace_id:
            tool_context.setdefault("workspace_id", request.workspace_id)
        tool_context["workspace_root"] = workspace_root
        tool_context["cwd"] = workspace_root
        tool_context["allowed_roots"] = [workspace_root]
    return tool_context


def resolve_team_workspace_id(request: ChatRequest, tool_context: dict[str, Any]) -> str | None:
    raw = tool_context.get("workspace_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if request.workspace_id:
        return request.workspace_id.strip()
    workspace_root = tool_context.get("workspace_root") or request.workspace_root
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root.strip()
    return None


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


def _update_plan_approval_artifact(
    conversation: Any,
    approval_id: str,
    state: dict[str, Any],
) -> None:
    if not approval_id:
        return
    for message in reversed(getattr(conversation, "messages", []) or []):
        if getattr(message, "role", None) != Role.ASSISTANT:
            continue
        metadata = getattr(message, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        artifact = metadata.get("plan_approval")
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("approvalId") or "") != approval_id:
            continue
        artifact["planStatus"] = str(state.get("status") or artifact.get("planStatus") or "")
        artifact["feedback"] = state.get("feedback")
        return
