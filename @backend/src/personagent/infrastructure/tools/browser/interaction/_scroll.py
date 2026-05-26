"""BrowserScroll tool factory."""

from __future__ import annotations

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
)
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.browser.building import (
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
    _simple_browser_control_tool,
    _target_error_result,
    _validate_browser_dimensions,
    _validate_page_or_window_id,
    _viewport_schema,
)


def create_browser_scroll_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScroll",
        )
        if target_error is not None:
            return target_error
        for key in ("delta_x", "delta_y"):
            if not isinstance(arguments.get(key, 0), int | float):
                return _deny(f"BrowserScroll {key} must be numeric.")
        return _validate_browser_dimensions(arguments, "BrowserScroll")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScroll",
        )
        if target_error:
            return _target_error_result(call, "BrowserScroll", target_error)
        await _progress(context, call, "Scrolling browser page...", {"page_id": target_id})
        try:
            data = await worker.scroll(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                delta_x=float(arguments.get("delta_x", 0.0)),
                delta_y=float(arguments.get("delta_y", 600.0)),
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserScroll", str(exc), exc)
        return _json_result(call, "BrowserScroll", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserScroll",
        description="Scroll the active or selected browser page.",
        schema_properties={
            **_page_target_schema(),
            "delta_x": {"type": "number", "default": 0},
            "delta_y": {"type": "number", "default": 600},
            **_viewport_schema(),
        },
        search_hint="browser scroll page viewport automation",
        handler=handler,
        validate=validate,
    )
