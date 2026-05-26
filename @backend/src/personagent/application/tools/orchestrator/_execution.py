"""Single-tool execution, error handling and activity messages."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from personagent.domain.exceptions import (
    PersonAgentError,
    ShellCommandDeniedError,
    ToolError,
    ToolInputValidationError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolPermissionRequiredError,
    ToolTimeoutError,
)
from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolResult,
    ToolUseContext,
)

from ._events import ToolExecutionEvent


class _ToolExecutionMixin:
    """Mixin that executes a single tool call and builds the result event."""

    async def _execute_one_result_event(
        self,
        call: ToolCall,
        context: ToolUseContext,
    ) -> ToolExecutionEvent:
        tool = self._registry.get(call.name)
        if tool is None:
            error = ToolNotFoundError(
                f"No such tool available: {call.name}",
                metadata={"tool_name": call.name},
            )
            return ToolExecutionEvent(
                event="tool_error",
                call=call,
                result=self._error_result(call, call.name, error),
            )

        try:
            validation = await tool.validate_input(call.arguments, context)
            if validation is not None and not validation.allowed:
                error = ToolInputValidationError(
                    validation.message or "Input validation failed.",
                    metadata={
                        "tool_name": tool.definition.name,
                        **validation.metadata,
                    },
                )
                return ToolExecutionEvent(
                    event="tool_error",
                    call=call,
                    result=self._error_result(call, tool.definition.name, error),
                )

            permission = await tool.check_permissions(call.arguments, context)
            if not permission.allowed:
                status = (
                    ToolExecutionStatus.PERMISSION_REQUIRED
                    if permission.behavior == ToolPermissionBehavior.ASK
                    else ToolExecutionStatus.ERROR
                )
                event_name = (
                    "permission_required"
                    if permission.behavior == ToolPermissionBehavior.ASK
                    else "tool_error"
                )
                if permission.behavior == ToolPermissionBehavior.ASK:
                    error = ToolPermissionRequiredError(
                        permission.message or "Tool call requires permission.",
                        metadata={
                            "tool_name": tool.definition.name,
                            **permission.metadata,
                        },
                    )
                else:
                    error_class = (
                        ShellCommandDeniedError
                        if tool.definition.name == "shell"
                        else ToolPermissionDeniedError
                    )
                    error = error_class(
                        permission.message or "Tool call was denied.",
                        metadata={
                            "tool_name": tool.definition.name,
                            **permission.metadata,
                        },
                    )
                return ToolExecutionEvent(
                    event=event_name,
                    call=call,
                    result=self._error_result(
                        call,
                        tool.definition.name,
                        error,
                        status=status,
                    ),
                )

            updated_arguments = permission.updated_input or call.arguments
            if tool.definition.timeout_ms:
                result = await asyncio.wait_for(
                    tool.call(updated_arguments, context, call),
                    timeout=tool.definition.timeout_ms / 1000,
                )
            else:
                result = await tool.call(updated_arguments, context, call)
        except TimeoutError as exc:
            timeout_ms = tool.definition.timeout_ms
            error = ToolTimeoutError(
                f"Tool {tool.definition.name} timed out.",
                metadata={"tool_name": tool.definition.name, "timeout_ms": timeout_ms},
                cause=exc,
            )
            result = self._error_result(call, tool.definition.name, error)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, PersonAgentError)
                else ToolError(
                    f"Error calling tool {tool.definition.name}: {exc}",
                    metadata={"tool_name": tool.definition.name},
                    cause=exc,
                )
            )
            result = self._error_result(call, tool.definition.name, error)

        result_metadata = result.metadata if isinstance(result.metadata, dict) else {}
        if "max_result_size_chars" not in result_metadata:
            result = replace(
                result,
                metadata={
                    **result_metadata,
                    "max_result_size_chars": tool.definition.max_result_size_chars,
                },
            )
        if result.is_error and "error" not in result.metadata:
            error = ToolError(
                result.content or f"Tool {tool.definition.name} failed.",
                metadata={"tool_name": tool.definition.name},
            )
            result = replace(
                result,
                metadata={**result.metadata, **self._error_metadata(error)},
            )
        result = self._cap_result(result, context)
        if result.is_error:
            event_name = (
                "permission_required"
                if result.status == ToolExecutionStatus.PERMISSION_REQUIRED
                else "tool_error"
            )
        else:
            event_name = "tool_result"
        return ToolExecutionEvent(event=event_name, call=call, result=result)

    def _error_result(
        self,
        call: ToolCall,
        tool_name: str,
        error: PersonAgentError,
        *,
        status: ToolExecutionStatus = ToolExecutionStatus.ERROR,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=tool_name,
            content=error.user_message,
            status=status,
            is_error=True,
            metadata=self._error_metadata(error),
        )

    def _error_metadata(self, error: PersonAgentError) -> dict[str, Any]:
        return {"error": error.to_envelope()}

    def _activity_message(self, tool_name: str) -> str:
        if tool_name in {"Read", "read_file"}:
            return "Reading..."
        if tool_name in {"Grep", "Glob", "search_files"}:
            return "Searching..."
        if tool_name == "shell":
            return "Running..."
        if tool_name in {"Write", "Edit"}:
            return "Editing..."
        if tool_name.startswith("Task") or tool_name == "Task":
            return "Updating task..."
        if tool_name == "WebFetch":
            return "Fetching..."
        if tool_name == "BrowserSearch":
            return "Searching..."
        if tool_name in {
            "BrowserOpen",
            "BrowserListTabs",
            "BrowserExtractContent",
            "BrowserReadContentChunk",
            "BrowserGetHtml",
            "BrowserGetElementMap",
            "BrowserClick",
            "BrowserType",
            "BrowserScreenshot",
            "BrowserCloseTab",
            "BrowserReadConsole",
            "BrowserScript",
            "BrowserScroll",
            "BrowserReload",
            "BrowserHistory",
            "BrowserSwitchTab",
            "BrowserWait",
            "BrowserAct",
        }:
            return "Browsing..."
        return "Running tool..."
