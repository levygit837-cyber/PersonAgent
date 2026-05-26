"""BrowserClick tool factory."""

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
    _is_int,
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


def create_browser_click_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserClick",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        x = arguments.get("x")
        y = arguments.get("y")
        if node_id is not None and (not isinstance(node_id, str) or not node_id.strip()):
            return _deny("BrowserClick node_id must be a non-empty string.")
        if not (isinstance(node_id, str) and node_id.strip()) and (
            not isinstance(x, int | float) or not isinstance(y, int | float)
        ):
            return _deny("BrowserClick requires node_id or numeric x/y coordinates.")
        size_error = _validate_browser_dimensions(arguments, "BrowserClick")
        if size_error is not None:
            return size_error
        button = arguments.get("button", "left")
        if button not in {"left", "middle", "right"}:
            return _deny("BrowserClick button must be left, middle, or right.")
        click_count = arguments.get("click_count", 1)
        if not _is_int(click_count) or int(click_count) < 1 or int(click_count) > 3:
            return _deny("BrowserClick click_count must be between 1 and 3.")
        modifiers = arguments.get("modifiers", [])
        if not isinstance(modifiers, list) or not all(isinstance(item, str) and item.strip() for item in modifiers):
            return _deny("BrowserClick modifiers must be an array of strings.")
        wait_after_ms = arguments.get("wait_after_ms", 250)
        if not _is_int(wait_after_ms) or int(wait_after_ms) < 0 or int(wait_after_ms) > 10_000:
            return _deny("BrowserClick wait_after_ms must be between 0 and 10000.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserClick",
        )
        if target_error:
            return _target_error_result(call, "BrowserClick", target_error)
        browser_id = _browser_session_id(context)
        node_id = str(arguments.get("node_id") or "").strip() or None
        await _progress(
            context,
            call,
            "Clicking browser page...",
            {"browser_id": browser_id, "page_id": target_id, "node_id": node_id, "x": arguments.get("x"), "y": arguments.get("y")},
        )
        try:
            data = await worker.click(
                conversation_id=browser_id,
                page_id=target_id,
                node_id=node_id,
                x=float(arguments["x"]) if isinstance(arguments.get("x"), int | float) else None,
                y=float(arguments["y"]) if isinstance(arguments.get("y"), int | float) else None,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
                button=str(arguments.get("button") or "left"),
                click_count=int(arguments.get("click_count") or 1),
                modifiers=[str(item) for item in arguments.get("modifiers", [])],
                wait_after_ms=int(arguments.get("wait_after_ms") or 250),
            )
        except Exception as exc:
            return _error(call, "BrowserClick", str(exc), exc)
        return _json_result(call, "BrowserClick", _prepare_browser_control_response(data))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserClick",
            description="Click a browser element by node_id from BrowserGetElementMap, or by viewport x/y coordinates.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "button": {"type": "string", "enum": ["left", "middle", "right"], "default": "left"},
                    "click_count": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                    "modifiers": {"type": "array", "items": {"type": "string"}, "default": []},
                    "wait_after_ms": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 250},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser click element node_id coordinate automation",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserClick", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )
