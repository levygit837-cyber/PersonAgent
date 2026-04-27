"""Ferramentas de entrada e saída do Plan Mode."""

from __future__ import annotations

import json

from personagent.application.plan_mode import (
    new_plan_approval_id,
    new_plan_id,
    normalize_plan_state,
    planning_instructions,
)
from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)


def create_enter_plan_mode_tool() -> Tool:
    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        reason = str(arguments.get("reason") or "")
        state = normalize_plan_state(context.metadata)
        plan_id = str(state.get("plan_id") or new_plan_id())
        state.update(
            {
                "active": True,
                "status": "draft",
                "plan_id": plan_id,
                "approval_id": None,
                "feedback": None,
                "cancelled": False,
            }
        )
        context.permissions["plan_mode"] = True
        context.metadata["plan_mode"] = state
        data = {
            "type": "plan_mode",
            "action": "enter",
            "active": True,
            "status": "draft",
            "plan_id": plan_id,
            "plan_content": state.get("plan_content") or "",
            "approval_id": None,
            "reason": reason,
            "content": planning_instructions(plan_id),
            "state": state,
        }
        return ToolResult(call.id, "EnterPlanMode", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="EnterPlanMode",
            description="Enter planning mode. Workspace and task mutation tools become blocked.",
            input_schema={
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.PLANNING.value,
            search_hint="plan mode planning no edits",
        ),
        handler=handler,
    )


def create_exit_plan_mode_tool() -> Tool:
    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        summary = str(arguments.get("summary") or "")
        plan = str(arguments.get("plan") or "").strip()
        plan_content = plan or summary.strip()
        state = normalize_plan_state(context.metadata)
        plan_id = str(state.get("plan_id") or new_plan_id())
        approval_id = new_plan_approval_id()
        state.update(
            {
                "active": True,
                "status": "awaiting_approval",
                "plan_id": plan_id,
                "plan_content": plan_content,
                "approval_id": approval_id,
                "feedback": None,
                "cancelled": False,
            }
        )
        context.permissions["plan_mode"] = True
        context.metadata["plan_mode"] = state
        data = {
            "type": "plan_mode",
            "action": "request_approval",
            "active": True,
            "status": "awaiting_approval",
            "plan_id": plan_id,
            "plan_content": plan_content,
            "approval_id": approval_id,
            "summary": summary,
            "content": "Plan ready for approval.",
            "state": state,
        }
        return ToolResult(call.id, "ExitPlanMode", json.dumps(data, ensure_ascii=False), data=data)

    async def check_permissions(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult:
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.ALLOW,
            updated_input=arguments,
            metadata={"policy": "exit_plan_mode_allowed"},
        )

    return build_tool(
        definition=ToolDefinition(
            name="ExitPlanMode",
            description=(
                "Request user approval for the completed plan. This does not execute the plan; "
                "execution starts only after the user approves it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "string",
                        "description": "Full markdown plan to show to the user for approval.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Legacy summary fallback when plan is not supplied.",
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.PLANNING.value,
            search_hint="exit plan implementation mode",
            requires_user_interaction=True,
        ),
        handler=handler,
        check_permissions=check_permissions,
    )


__all__ = ["create_enter_plan_mode_tool", "create_exit_plan_mode_tool"]
