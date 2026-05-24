"""Tool approval endpoints (approve, approve/stream, reject, answer question).

Endpoint functions access monkeypatchable symbols (``get_container``,
``_approve_pending_tool_call``, ``_answer_pending_user_question``,
``_load_conversation_for_decision``) through the ``_chat`` module
reference so that test monkeypatches are resolved at call time.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# Late-binding module reference.  See module docstring for rationale.
import personagent.interfaces.api.routes.chat as _chat
from personagent.application.plan_mode import PENDING_TOOL_APPROVAL_KEY
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    LLMBackendConnectionError,
    LLMBackendError,
)
from personagent.domain.models.conversation import Message, Role
from personagent.domain.tools import ToolExecutionStatus
from personagent.interfaces.api.errors import error_event
from personagent.interfaces.api.routes.chat.helpers import (
    DB_SESSION_DEPENDENCY,
    ToolApprovalDecisionRequest,
    UserQuestionResponseRequest,
    _require_tool_approval,
    encode_sse,
)


def register_tool_approval_routes(router: APIRouter) -> None:
    """Register tool approve, reject, and user-question endpoints."""

    @router.post("/tools/approve")
    async def approve_tool(
        request: ToolApprovalDecisionRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Approve and execute a tool previously paused by permission handling."""

        conversation, conv_repo = await _chat._load_conversation_for_decision(
            request.conversation_id, session
        )
        container = _chat.get_container()
        _use_case, _resume_request, _pending, result = await _chat._approve_pending_tool_call(
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
                conversation, conv_repo = await _chat._load_conversation_for_decision(
                    request.conversation_id, session
                )
                container = _chat.get_container()
                use_case, resume_request, pending, result = await _chat._approve_pending_tool_call(
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
                import structlog
                logger = structlog.get_logger(__name__)
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

        conversation, conv_repo = await _chat._load_conversation_for_decision(
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
        conversation.metadata["session_status"] = "idle"
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
                conversation, conv_repo = await _chat._load_conversation_for_decision(
                    request.conversation_id, session
                )
                container = _chat.get_container()
                use_case, resume_request, pending, answer_payload = (
                    await _chat._answer_pending_user_question(
                        request=request,
                        conversation=conversation,
                        conv_repo=conv_repo,
                        container=container,
                    )
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
                import structlog
                logger = structlog.get_logger(__name__)
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
