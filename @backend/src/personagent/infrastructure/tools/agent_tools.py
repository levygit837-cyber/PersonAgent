"""PersonAgent-style Agent and SendMessage tools."""

from __future__ import annotations

import json

from personagent.application.tools import TaskStore, new_task_record
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


def create_agent_tools(store: TaskStore) -> list[Tool]:
    """Create Agent and SendMessage communication tools."""
    return [create_agent_tool(store), create_send_message_tool(store)]


def create_agent_tool(store: TaskStore) -> Tool:
    """Create Agent, with AgentTool as a backward-compatible alias."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _deny("Agent requires a non-empty 'prompt' string.")
        description = arguments.get("description")
        if description is not None and not isinstance(description, str):
            return _deny("Agent description must be a string when provided.")
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        name = str(arguments.get("name") or arguments.get("description") or "agent").strip()
        prompt = str(arguments["prompt"]).strip()
        run_in_background = arguments.get("run_in_background") is not False
        metadata = {
            "agent_name": name,
            "agent_type": str(arguments.get("agent_type") or "general"),
            "prompt": prompt,
            "expected_output": str(arguments.get("expected_output") or "").strip() or None,
            "run_in_background": run_in_background,
            "messages": [],
        }
        record = new_task_record(
            title=name,
            description=prompt,
            status="in_progress" if run_in_background else "open",
            priority="normal",
            conversation_id=context.conversation_id,
            workspace_root=str(context.metadata.get("active_workspace_root") or context.workspace_root),
            metadata=metadata,
        )
        created = await store.create(record)
        agent_id = created.id
        data = {
            "type": "agent",
            "agent_id": agent_id,
            "name": name,
            "status": created.status,
            "task": created.to_dict(),
            "content": f"Created agent {name} ({agent_id}).",
        }
        context.metadata.setdefault("agents", {})[agent_id] = data
        return ToolResult(call.id, "Agent", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="Agent",
            aliases=("AgentTool",),
            description=(
                "Create a durable agent/task record for a bounded subtask. Use SendMessage to "
                "communicate with the created agent by id."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "prompt": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "name": {"type": "string"},
                    "expected_output": {"type": "string"},
                    "run_in_background": {"type": "boolean"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            group=ToolGroup.AGENT.value,
            search_hint="agent subagent delegate background task",
            usage_prompt=(
                "Use Agent for bounded work that can be tracked independently. Include the "
                "expected output and ownership. AgentTool remains an alias; Agent is preferred."
            ),
            is_destructive=False,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_agent_permission,
    )


def create_send_message_tool(store: TaskStore) -> Tool:
    """Create SendMessage for existing Agent/Task records."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        agent_id = arguments.get("agent_id") or arguments.get("recipient")
        if not isinstance(agent_id, str) or not agent_id.strip():
            return _deny("SendMessage requires 'agent_id' or 'recipient'.")
        message = arguments.get("message")
        if not isinstance(message, str) or not message.strip():
            return _deny("SendMessage requires a non-empty 'message' string.")
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        agent_id = str(arguments.get("agent_id") or arguments.get("recipient")).strip()
        record = await store.get(agent_id)
        if record is None:
            return _error(call, f"Agent not found: {agent_id}")

        message = {
            "from": str(arguments.get("from_agent") or "orchestrator"),
            "message": str(arguments["message"]).strip(),
            "type": str(arguments.get("type") or "message"),
        }
        metadata = dict(record.metadata or {})
        messages = list(metadata.get("messages") or [])
        messages.append(message)
        metadata["messages"] = messages
        updated = await store.update(agent_id, {"metadata": metadata})
        data = {
            "type": "agent_message",
            "agent_id": agent_id,
            "message": message,
            "task": updated.to_dict() if updated is not None else record.to_dict(),
            "content": f"Sent message to {agent_id}.",
        }
        return ToolResult(call.id, "SendMessage", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="SendMessage",
            description=(
                "Send a durable message to an Agent/Task record created earlier. This is for "
                "agent-to-agent communication, not for normal user-facing replies."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "recipient": {"type": "string"},
                    "message": {"type": "string"},
                    "type": {"type": "string", "enum": ["message", "status", "question", "result"]},
                    "from_agent": {"type": "string"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            group=ToolGroup.AGENT.value,
            search_hint="send message agent subagent communication",
            usage_prompt=(
                "Use SendMessage only for existing Agent/Task records when background work "
                "or team-style coordination needs a durable message."
            ),
            is_read_only=False,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_agent_permission,
    )


async def _agent_permission(
    arguments: ToolArguments,
    context: ToolUseContext,
) -> ToolPermissionResult:
    mode = str(context.permissions.get("mode") or "").lower()
    if mode in {"read_only", "readonly"}:
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.DENY,
            message="Agent communication tools are blocked in read-only permission mode.",
        )
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


def _error(call: ToolCall, message: str) -> ToolResult:
    data = {"type": "agent_error", "content": message}
    return ToolResult(
        call.id,
        "SendMessage",
        json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)
