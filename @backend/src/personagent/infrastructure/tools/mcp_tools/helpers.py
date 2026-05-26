"""Permission and error helpers for MCP tools."""

from __future__ import annotations

import json

from personagent.domain.tools import (
    ToolArguments,
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
)


async def _mcp_permission(
    arguments: ToolArguments,
    _context: ToolUseContext,
) -> ToolPermissionResult:
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


async def _allow(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult:
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


def _error(call: ToolCall, tool_name: str, message: str) -> ToolResult:
    data = {"type": "mcp_error", "content": message}
    return ToolResult(
        call.id,
        tool_name,
        json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)
