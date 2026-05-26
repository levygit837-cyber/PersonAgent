"""BrowserType tool factory."""

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
from personagent.infrastructure.tools.browser.building import (
    _browser_action_permission,
    _browser_height,
    _browser_session_id,
    _browser_width,
    _deny,
    _error,
    _json_result,
    _page_target_schema,
    _prepare_browser_control_response,
    _progress,
    _resolve_browser_page_target,
    _target_error_result,
    _validate_browser_dimensions,
    _validate_page_or_window_id,
    _viewport_schema,
)


def create_browser_type_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserType",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        if node_id is not None and (not isinstance(node_id, str) or not node_id.strip()):
            return _deny("BrowserType node_id must be a non-empty string.")
        mode = arguments.get("mode", "type")
        if mode not in {"type", "fill", "press"}:
            return _deny("BrowserType mode must be type, fill, or press.")
        if mode in {"type", "fill"} and not isinstance(arguments.get("text"), str):
            return _deny("BrowserType type/fill requires text.")
        if mode == "press" and not isinstance(arguments.get("key", arguments.get("text")), str):
            return _deny("BrowserType press requires key or text.")
        if not isinstance(arguments.get("clear", False), bool):
            return _deny("BrowserType clear must be a boolean.")
        if not isinstance(arguments.get("submit", False), bool):
            return _deny("BrowserType submit must be a boolean.")
        delay_ms = arguments.get("delay_ms", 0)
        if not isinstance(delay_ms, int) or delay_ms < 0 or delay_ms > 1000:
            return _deny("BrowserType delay_ms must be between 0 and 1000.")
        return _validate_browser_dimensions(arguments, "BrowserType")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserType",
        )
        if target_error:
            return _target_error_result(call, "BrowserType", target_error)
        mode = str(arguments.get("mode") or "type")
        node_id = str(arguments.get("node_id") or "").strip() or None
        await _progress(context, call, f"Typing in browser ({mode})...", {"page_id": target_id, "node_id": node_id})
        try:
            data = await worker.type_input(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                node_id=node_id,
                mode=mode,
                text=arguments.get("text") if isinstance(arguments.get("text"), str) else None,
                key=arguments.get("key") if isinstance(arguments.get("key"), str) else None,
                clear=bool(arguments.get("clear", False)),
                delay_ms=int(arguments.get("delay_ms") or 0),
                submit=bool(arguments.get("submit", False)),
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserType", str(exc), exc)
        return _json_result(call, "BrowserType", _prepare_browser_control_response(data))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserType",
            description="Type, fill, or press a key in the browser, optionally targeting a node_id.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["type", "fill", "press"], "default": "type"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "clear": {"type": "boolean", "default": False},
                    "delay_ms": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 0},
                    "submit": {"type": "boolean", "default": False},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser type fill press keyboard input node_id automation",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserType", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )
