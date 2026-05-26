"""Use-case helpers for chat completion routes."""

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Late-binding module reference.  See module docstring for rationale.
import personagent.interfaces.api.routes.chat as _chat
from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
)
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.models.conversation import Message, Role
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolExecutionStatus
from personagent.interfaces.api.action_approvals import canonical_args_hash
from personagent.interfaces.api.routes.chat.completion.resolvers import (
    resolve_context_window_tokens,
    resolve_context_workspace_root_from_tool_context,
    resolve_default_output_tokens,
    resolve_model,
)
from personagent.interfaces.api.routes.chat.helpers import (
    ToolApprovalDecisionRequest,
    UserQuestionResponseRequest,
    _last_user_message,
    _require_tool_approval,
    _require_user_question,
    resolve_next_step_suggestion_service,
    resolve_prompt_mode,
    resolve_provider,
    resolve_session_memory_service,
)
from personagent.interfaces.config.di_container import DIContainer


async def _load_conversation_for_decision(
    conversation_id: str,
    session: AsyncSession,
) -> tuple[Any, Any]:
    container = _chat.get_container()
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
