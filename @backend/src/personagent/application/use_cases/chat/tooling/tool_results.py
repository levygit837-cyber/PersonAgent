"""Tool-call execution and result handling extracted from ``chat_completion.py``.

The chat use case interleaves two halves of the tool loop:

* the *request* side -- materializing OpenAI tool-call schemas, deciding
  whether the next assistant pass should include tools, etc.;
* the *result* side -- parsing the assistant message's ``tool_calls``,
  renaming duplicate IDs, dispatching them through a
  :class:`ToolOrchestrator`, capturing operational memory, mutating the
  conversation state (plan mode, todos, pending approvals, pending user
  questions), and finally appending the tool-result messages to the
  conversation.

This module owns the *result* side. Pulling it out keeps the orchestrator
slim and groups together a cluster of nine private methods that only
called each other -- ``_parse_tool_calls``, ``_unique_tool_call_ids``,
``_execute_tools_into_conversation``, ``_tool_message_from_result``,
``_apply_tool_state_result``, ``_is_plan_mode_result``,
``_is_plan_approval_result``, ``_is_user_question_result``,
``_plan_state_from_result``, ``_record_pending_tool_approval``,
``_record_pending_user_question``, and ``_forwarded_finish_reason``.

Backward compatibility: every method preserves its inputs, outputs, and
side-effects exactly. The only externally observable change is that the
chat use case now delegates these calls to ``self._tool_results.<verb>``.

Concurrency: stateless. Safe to share across requests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import (
    PENDING_TOOL_APPROVAL_KEY,
    PENDING_USER_QUESTION_KEY,
    new_tool_approval_id,
    normalize_plan_state,
    now_iso,
    write_plan_state,
)
from personagent.application.services.browser_cooperation import (
    attach_browser_action_proposal,
)
from personagent.application.tools import ToolOrchestrator
from personagent.application.use_cases.chat.memory.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.security import canonical_args_hash
from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolResult,
    ToolUseContext,
)


class ToolResultHandler:
    """Coordinate the result side of the tool loop for the chat use case.

    The handler is composed of small, pure helpers and a single async
    method (:meth:`execute`) that drives the orchestrator. Every state
    mutation it performs is scoped to either:

    * the in-memory :class:`Conversation` (plan state, todos, pending
      approvals, pending user questions, tool messages); or
    * the operational-memory service (via the injected
      :class:`OperationalMemoryCapture`).

    The handler does NOT persist the conversation -- the caller (the
    chat use case) decides when to flush via its
    :class:`ConversationRepository`. This mirrors how the legacy
    methods worked.
    """

    def __init__(
        self,
        *,
        orchestrator_factory: Callable[[], ToolOrchestrator],
        operational_memory: OperationalMemoryCapture,
    ) -> None:
        self._orchestrator_factory = orchestrator_factory
        self._operational_memory = operational_memory

    # ---- Tool-call parsing & ID stability -------------------------------

    def parse_calls(self, tool_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
        """Convert raw OpenAI tool_calls into the domain ``ToolCall`` list.

        Empty / malformed entries (missing id or name) are dropped --
        the legacy ``_parse_tool_calls`` did the same.
        """

        if not tool_calls:
            return []
        calls = [ToolCall.from_openai(call) for call in tool_calls]
        return [call for call in calls if call.id and call.name]

    def unique_call_ids(
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

    # ---- Tool execution -------------------------------------------------

    async def execute(
        self,
        tool_calls: list[ToolCall],
        tool_context: ToolUseContext,
        conversation: Conversation,
    ) -> None:
        """Run ``tool_calls`` and append their results to ``conversation``.

        Results that come back with status ``PERMISSION_REQUIRED`` are
        applied to the conversation state but NOT appended as a tool
        message -- the caller decides what to do with the pending
        approval (the streaming path records a pending approval, the
        non-streaming path keeps looping).
        """

        orchestrator = self._orchestrator_factory()
        results = await orchestrator.execute_collect(tool_calls, tool_context)
        calls_by_id = {call.id: call for call in tool_calls}
        for result in results:
            call = calls_by_id.get(result.tool_call_id)
            if call is not None:
                await self._operational_memory.capture_tool_result(
                    None,
                    conversation,
                    call,
                    result,
                    tool_context,
                )
            self.apply_state(result, conversation)
            if result.status != ToolExecutionStatus.PERMISSION_REQUIRED:
                conversation.add_message(self.tool_message_from(result))

    def tool_message_from(self, result: ToolResult) -> Message:
        """Render a :class:`Message` for a single tool result."""

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

    # ---- Result classification & state side effects ---------------------

    def apply_state(self, result: ToolResult, conversation: Conversation) -> None:
        """Reflect special-result side effects onto the conversation."""

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

    def is_plan_mode(self, result: ToolResult) -> bool:
        return bool(result.data.get("type") == "plan_mode")

    def is_plan_approval(self, result: ToolResult) -> bool:
        return self.is_plan_mode(result) and bool(
            result.data.get("action") == "request_approval"
        )

    def is_user_question(self, result: ToolResult) -> bool:
        return bool(result.data.get("type") == "ask_user_question")

    def plan_state_from(
        self,
        result: ToolResult,
        conversation: Conversation,
    ) -> dict[str, Any]:
        """Return the normalized plan state for a plan-mode result."""

        state = result.data.get("state")
        if isinstance(state, dict):
            return cast(dict[str, Any], normalize_plan_state({"plan_mode": state}))
        return cast(dict[str, Any], normalize_plan_state(conversation.metadata))

    # ---- Pending approvals & user questions -----------------------------

    def record_pending_approval(
        self,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        request: ChatRequestDTO,
    ) -> dict[str, Any]:
        """Write a pending tool-approval record to ``conversation.metadata``."""

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
        arbiter_metadata = (
            result.metadata.get("browser_action_arbiter")
            if isinstance(result.metadata, dict)
            else None
        )
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

    def record_pending_question(
        self,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        request: ChatRequestDTO,
    ) -> dict[str, Any]:
        """Write a pending user-question record to ``conversation.metadata``."""

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

    # ---- Streaming finish-reason gating ---------------------------------

    def forwarded_finish_reason(
        self,
        chunk: StreamChunk,
        *,
        has_pending_tool_calls: bool,
    ) -> str | None:
        """Decide which ``finish_reason`` (if any) propagates to the client."""

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
        return cast("str | None", chunk.finish_reason)


__all__ = ["ToolResultHandler"]
