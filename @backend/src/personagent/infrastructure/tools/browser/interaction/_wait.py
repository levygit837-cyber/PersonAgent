"""BrowserWait tool factory."""

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
    _is_int,
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


def create_browser_wait_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserWait",
        )
        if target_error is not None:
            return target_error
        timeout_ms = arguments.get("timeout_ms", 1000)
        if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 120_000:
            return _deny("BrowserWait timeout_ms must be between 1 and 120000.")
        state = arguments.get("state")
        if state is not None and state not in {"load", "domcontentloaded", "networkidle"}:
            return _deny("BrowserWait state must be load, domcontentloaded, or networkidle.")
        return _validate_browser_dimensions(arguments, "BrowserWait")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserWait",
        )
        if target_error:
            return _target_error_result(call, "BrowserWait", target_error)
        await _progress(context, call, "Waiting for browser page...", {"page_id": target_id})
        try:
            data = await worker.wait(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                timeout_ms=int(arguments.get("timeout_ms") or 1000),
                state=arguments.get("state") if isinstance(arguments.get("state"), str) else None,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserWait", str(exc), exc)
        return _json_result(call, "BrowserWait", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserWait",
        description="Wait for time or a load state on the active or selected browser page.",
        schema_properties={
            **_page_target_schema(),
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 120000, "default": 1000},
            "state": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"]},
            **_viewport_schema(),
        },
        search_hint="browser wait load state timeout",
        handler=handler,
        validate=validate,
    )
