"""Ferramentas de tarefas persistentes e todos efêmeros."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

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

_STATUSES = {"open", "in_progress", "blocked", "completed", "cancelled"}
_PRIORITIES = {"low", "normal", "high", "urgent"}


def create_todo_write_tool() -> Tool:
    """Cria TodoWrite, um estado efêmero por conversa/request."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        todos = arguments.get("todos")
        if not isinstance(todos, list):
            return _deny("TodoWrite requires a 'todos' array.")
        for item in todos:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                return _deny("Each todo must be an object with a string 'content'.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        todos = [_normalize_todo(item) for item in arguments["todos"]]
        context.metadata["todos"] = todos
        data = {"type": "todos", "todos": todos, "content": f"Updated {len(todos)} todos."}
        return ToolResult(
            tool_call_id=call.id,
            tool_name="TodoWrite",
            content=json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="TodoWrite",
            description="Write the agent's current todo list for this conversation.",
            input_schema={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                                "id": {"type": "string"},
                            },
                            "required": ["content"],
                            "additionalProperties": True,
                        },
                    }
                },
                "required": ["todos"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="todo checklist plan steps progress",
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _allow(args, context),
    )


def create_task_tools(store: TaskStore) -> list[Tool]:
    """Cria Task, TaskCreate, TaskGet, TaskUpdate, TaskList, TaskOutput e TaskStop."""
    return [
        _create_task_create_tool(store, name="Task", aliases=()),
        _create_task_create_tool(store, name="TaskCreate", aliases=()),
        _create_task_get_tool(store),
        _create_task_update_tool(store),
        _create_task_list_tool(store),
        _create_task_output_tool(store),
        _create_task_stop_tool(store),
    ]


def _create_task_create_tool(store: TaskStore, *, name: str, aliases: tuple[str, ...]) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        title = arguments.get("title")
        if not isinstance(title, str) or not title.strip():
            return _deny(f"{name} requires a non-empty 'title' string.")
        status = str(arguments.get("status") or "open")
        priority = str(arguments.get("priority") or "normal")
        if status not in _STATUSES:
            return _deny(f"Invalid task status: {status}")
        if priority not in _PRIORITIES:
            return _deny(f"Invalid task priority: {priority}")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
        record = new_task_record(
            title=str(arguments["title"]).strip(),
            description=str(arguments.get("description") or ""),
            status=str(arguments.get("status") or "open"),
            priority=str(arguments.get("priority") or "normal"),
            conversation_id=context.conversation_id,
            workspace_root=str(context.workspace_root),
            metadata=metadata,
        )
        created = await store.create(record)
        data = {"type": "task", "task": created.to_dict(), "content": f"Created task {created.id}."}
        return ToolResult(call.id, name, json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name=name,
            aliases=aliases,
            description="Create a persistent task record.",
            input_schema=_task_create_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task create issue work item",
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_task_mutation_permission,
    )


def _create_task_get_tool(store: TaskStore) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        return _validate_task_id(arguments, "TaskGet")

    async def handler(
        arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        record = await _get_or_error(store, str(arguments["task_id"]), call, "TaskGet")
        if isinstance(record, ToolResult):
            return record
        data = {
            "type": "task",
            "task": record.to_dict(),
            "content": json.dumps(record.to_dict(), ensure_ascii=False),
        }
        return ToolResult(call.id, "TaskGet", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="TaskGet",
            description="Read one persistent task record.",
            input_schema=_task_id_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task get read status",
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def _create_task_update_tool(store: TaskStore) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        invalid = _validate_task_id(arguments, "TaskUpdate")
        if invalid is not None:
            return invalid
        status = arguments.get("status")
        priority = arguments.get("priority")
        if status is not None and str(status) not in _STATUSES:
            return _deny(f"Invalid task status: {status}")
        if priority is not None and str(priority) not in _PRIORITIES:
            return _deny(f"Invalid task priority: {priority}")
        return None

    async def handler(
        arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        values = {
            "title": arguments.get("title"),
            "description": arguments.get("description"),
            "status": arguments.get("status"),
            "priority": arguments.get("priority"),
            "output": arguments.get("output"),
            "metadata": arguments.get("metadata")
            if isinstance(arguments.get("metadata"), dict)
            else None,
        }
        record = await store.update(str(arguments["task_id"]), values)
        if record is None:
            return _not_found(call, "TaskUpdate", str(arguments["task_id"]))
        data = {"type": "task", "task": record.to_dict(), "content": f"Updated task {record.id}."}
        return ToolResult(call.id, "TaskUpdate", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="TaskUpdate",
            description="Update a persistent task record.",
            input_schema=_task_update_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task update status priority output",
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_task_mutation_permission,
    )


def _create_task_list_tool(store: TaskStore) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        status = arguments.get("status")
        if status is not None and str(status) not in _STATUSES:
            return _deny(f"Invalid task status: {status}")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        include_all = arguments.get("all_conversations") is True
        records = await store.list(
            conversation_id=None if include_all else context.conversation_id,
            status=str(arguments["status"]) if arguments.get("status") else None,
            limit=_positive_int(arguments.get("limit"), 50),
        )
        tasks = [record.to_dict() for record in records]
        data = {
            "type": "tasks",
            "tasks": tasks,
            "count": len(tasks),
            "content": json.dumps(tasks, ensure_ascii=False),
        }
        return ToolResult(call.id, "TaskList", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="TaskList",
            description="List persistent task records.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": sorted(_STATUSES)},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    "all_conversations": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task list backlog status",
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def _create_task_output_tool(store: TaskStore) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        return _validate_task_id(arguments, "TaskOutput")

    async def handler(
        arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        record = await _get_or_error(store, str(arguments["task_id"]), call, "TaskOutput")
        if isinstance(record, ToolResult):
            return record
        data = {
            "type": "task_output",
            "task_id": record.id,
            "output": record.output,
            "content": record.output,
        }
        return ToolResult(call.id, "TaskOutput", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="TaskOutput",
            description="Read the output field of a persistent task record.",
            input_schema=_task_id_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task output result log",
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def _create_task_stop_tool(store: TaskStore) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        return _validate_task_id(arguments, "TaskStop")

    async def handler(
        arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        record = await store.update(str(arguments["task_id"]), {"status": "cancelled"})
        if record is None:
            return _not_found(call, "TaskStop", str(arguments["task_id"]))
        data = {"type": "task", "task": record.to_dict(), "content": f"Cancelled task {record.id}."}
        return ToolResult(call.id, "TaskStop", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="TaskStop",
            description="Mark a persistent task record as cancelled.",
            input_schema=_task_id_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.TASK.value,
            search_hint="task stop cancel",
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_task_mutation_permission,
    )


async def _task_mutation_permission(
    arguments: ToolArguments, context: ToolUseContext
) -> ToolPermissionResult:
    if context.permissions.get("plan_mode"):
        return _deny("Task mutation tools are blocked while Plan Mode is active.")
    return await _allow(arguments, context)


async def _allow(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.ALLOW, updated_input=arguments)


async def _get_or_error(store: TaskStore, task_id: str, call: ToolCall, tool_name: str):
    try:
        UUID(task_id)
    except ValueError:
        return _not_found(call, tool_name, task_id)
    record = await store.get(task_id)
    return record if record is not None else _not_found(call, tool_name, task_id)


def _validate_task_id(arguments: ToolArguments, tool_name: str) -> ToolPermissionResult | None:
    task_id = arguments.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return _deny(f"{tool_name} requires a non-empty 'task_id' string.")
    try:
        UUID(task_id)
    except ValueError:
        return _deny(f"Invalid task_id: {task_id}")
    return None


def _not_found(call: ToolCall, tool_name: str, task_id: str) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=f"Task not found: {task_id}",
        status=ToolExecutionStatus.ERROR,
        is_error=True,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 200))


def _normalize_todo(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "pending")
    if status not in {"pending", "in_progress", "completed"}:
        status = "pending"
    return {
        "id": str(item.get("id") or ""),
        "content": str(item["content"]),
        "status": status,
    }


def _task_id_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
        "additionalProperties": False,
    }


def _task_create_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string", "enum": sorted(_STATUSES)},
            "priority": {"type": "string", "enum": sorted(_PRIORITIES)},
            "metadata": {"type": "object", "additionalProperties": True},
        },
        "required": ["title"],
        "additionalProperties": False,
    }


def _task_update_schema() -> dict[str, Any]:
    schema = _task_create_schema()
    schema["properties"] = {
        "task_id": {"type": "string"},
        **schema["properties"],
        "output": {"type": "string"},
    }
    schema["required"] = ["task_id"]
    return schema


__all__ = ["create_task_tools", "create_todo_write_tool"]
