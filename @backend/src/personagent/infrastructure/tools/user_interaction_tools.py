"""PersonAgent-style tools for visible user interaction."""

from __future__ import annotations

import json
import os
from typing import Any

from personagent.application.plan_mode import new_tool_approval_id
from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)


def create_ask_user_question_tool() -> Tool:
    """Create AskUserQuestion, a serial checkpoint that pauses for user input."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        questions = arguments.get("questions")
        if not isinstance(questions, list) or not questions:
            return _deny("AskUserQuestion requires a non-empty 'questions' array.")
        for index, item in enumerate(questions):
            if not isinstance(item, dict):
                return _deny(f"Question {index + 1} must be an object.")
            question = item.get("question")
            if not isinstance(question, str) or not question.strip():
                return _deny(f"Question {index + 1} requires a non-empty 'question'.")
            options = item.get("options")
            if options is not None:
                if not isinstance(options, list) or len(options) > 4:
                    return _deny(
                        f"Question {index + 1} options must be an array with up to 4 items."
                    )
                for option_index, option in enumerate(options):
                    if not isinstance(option, dict) or not isinstance(option.get("label"), str):
                        return _deny(
                            f"Question {index + 1} option {option_index + 1} "
                            "requires a string 'label'."
                        )
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        approval_id = new_tool_approval_id()
        questions = [_normalize_question(item) for item in arguments["questions"]]
        data = {
            "type": "ask_user_question",
            "approval_id": approval_id,
            "questions": questions,
            "title": arguments.get("title") or "User input requested",
            "content": "Waiting for user input.",
        }
        context.metadata["pending_user_question"] = {
            "approval_id": approval_id,
            "tool_call_id": call.id,
            "questions": questions,
        }
        return ToolResult(
            tool_call_id=call.id,
            tool_name="AskUserQuestion",
            content=json.dumps(data, ensure_ascii=False),
            status=ToolExecutionStatus.PERMISSION_REQUIRED,
            is_error=True,
            data=data,
            metadata={"interaction": "ask_user_question"},
        )

    return build_tool(
        definition=ToolDefinition(
            name="AskUserQuestion",
            description=(
                "Ask the user one or more concrete questions and pause the tool loop until "
                "the frontend/API provides answers."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the visible user prompt.",
                    },
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "header": {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["label"],
                                        "additionalProperties": False,
                                    },
                                },
                                "allow_freeform": {"type": "boolean"},
                            },
                            "required": ["question"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
            group=ToolGroup.USER_INTERACTION.value,
            search_hint="ask user question clarification checkpoint",
            usage_prompt=(
                "Use AskUserQuestion only when progress is blocked by a concrete user choice. "
                "Ask short, answerable questions with options when possible."
            ),
            should_defer=True,
            requires_user_interaction=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_allow,
    )


def create_send_user_message_tool(*, enabled: bool | None = None) -> Tool:
    """Create optional SendUserMessage/Brief-style visible checkpoint tool."""

    if enabled is None:
        enabled = _brief_tool_enabled()

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        message = arguments.get("message")
        if not isinstance(message, str) or not message.strip():
            return _deny("SendUserMessage requires a non-empty 'message' string.")
        status = str(arguments.get("status") or "normal")
        if status not in {"normal", "proactive"}:
            return _deny("SendUserMessage status must be 'normal' or 'proactive'.")
        attachments = arguments.get("attachments")
        if attachments is not None and not isinstance(attachments, list):
            return _deny("SendUserMessage attachments must be an array when provided.")
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        message = str(arguments["message"]).strip()
        attachments = [str(item) for item in arguments.get("attachments") or []]
        data = {
            "type": "user_message",
            "message": message,
            "attachments": attachments,
            "status": str(arguments.get("status") or "normal"),
            "content": message,
        }
        context.metadata.setdefault("visible_user_messages", []).append(data)
        return ToolResult(
            tool_call_id=call.id,
            tool_name="SendUserMessage",
            content=json.dumps(data, ensure_ascii=False),
            data=data,
            metadata={"visible_to_user": True},
        )

    return build_tool(
        definition=ToolDefinition(
            name="SendUserMessage",
            aliases=("Brief",),
            description=(
                "Send a short visible checkpoint message to the user. Optional/gated; the "
                "normal assistant response remains the primary user-facing channel."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "attachments": {"type": "array", "items": {"type": "string"}},
                    "status": {"type": "string", "enum": ["normal", "proactive"]},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            group=ToolGroup.USER_INTERACTION.value,
            search_hint="brief send user message visible checkpoint",
            usage_prompt=(
                "Use SendUserMessage sparingly for visible checkpoints during long work. "
                "Do not use it instead of the final assistant answer."
            ),
            cacheable_prompt=False,
            is_read_only=True,
        ),
        handler=handler,
        enabled=enabled,
        validate_input=validate,
        check_permissions=_allow,
        is_concurrency_safe=lambda _args: False,
        is_read_only=lambda _args: True,
    )


def _normalize_question(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": str(item["question"]).strip(),
        "header": str(item.get("header") or "").strip() or None,
        "options": [
            {
                "label": str(option.get("label") or "").strip(),
                "description": str(option.get("description") or "").strip() or None,
            }
            for option in item.get("options") or []
        ],
        "allow_freeform": item.get("allow_freeform") is not False,
    }


def _brief_tool_enabled() -> bool:
    raw = (
        os.getenv("PERSONAGENT_BRIEF_TOOL_ENABLED")
        or os.getenv("MINDFLOW_BRIEF_TOOL_ENABLED")
        or ""
    )
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


async def _allow(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult:
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )
