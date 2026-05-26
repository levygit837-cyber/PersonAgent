"""BrowserReadConsole tool factory."""

from __future__ import annotations

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolGroup,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.browser_tools.helpers import (
    _BROWSER_CONSOLE_LEVELS,
    _browser_session_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _page_target_schema,
    _progress,
    _resolve_browser_page_target,
    _target_error_result,
    _validate_page_or_window_id,
)


def create_browser_read_console_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserReadConsole",
        )
        if target_error is not None:
            return target_error
        levels = arguments.get("levels", [])
        if not isinstance(levels, list) or not all(isinstance(level, str) for level in levels):
            return _deny("BrowserReadConsole levels must be an array of strings.")
        invalid_levels = {level for level in levels if level.lower() not in _BROWSER_CONSOLE_LEVELS}
        if invalid_levels:
            return _deny("BrowserReadConsole levels may include debug, error, info, log, warn, or warning.")
        since_id = arguments.get("since_id")
        if since_id is not None and (not _is_int(since_id) or int(since_id) < 0):
            return _deny("BrowserReadConsole since_id must be a non-negative integer.")
        limit = arguments.get("limit", 100)
        if not _is_int(limit) or int(limit) < 1 or int(limit) > 200:
            return _deny("BrowserReadConsole limit must be between 1 and 200.")
        if not isinstance(arguments.get("clear", False), bool):
            return _deny("BrowserReadConsole clear must be a boolean.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserReadConsole",
        )
        if target_error:
            return _target_error_result(call, "BrowserReadConsole", target_error)
        await _progress(context, call, "Reading browser console...", {"page_id": target_id})
        try:
            data = await worker.read_console(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                levels=[str(level).lower() for level in arguments.get("levels", [])],
                since_id=int(arguments["since_id"]) if _is_int(arguments.get("since_id")) else None,
                limit=int(arguments.get("limit") or 100),
                clear=bool(arguments.get("clear", False)),
            )
        except Exception as exc:
            return _error(call, "BrowserReadConsole", str(exc), exc)
        return _json_result(call, "BrowserReadConsole", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserReadConsole",
            description="Read captured console logs, page errors, and CDP log entries for a browser page.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "levels": {"type": "array", "items": {"type": "string"}, "default": []},
                    "since_id": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
                    "clear": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser console logs pageerror debug error",
            max_result_size_chars=20_000,
            is_read_only=True,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda args: not bool(args.get("clear", False)),
        is_concurrency_safe=lambda args: not bool(args.get("clear", False)),
    )
