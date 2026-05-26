"""BrowserScreenshot tool factory."""

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


def create_browser_screenshot_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScreenshot",
        )
        if target_error is not None:
            return target_error
        size_error = _validate_browser_dimensions(arguments, "BrowserScreenshot")
        if size_error is not None:
            return size_error
        if not isinstance(arguments.get("full_page", False), bool):
            return _deny("BrowserScreenshot full_page must be a boolean.")
        image_format = arguments.get("format", "png")
        if image_format not in {"png", "jpeg"}:
            return _deny("BrowserScreenshot format must be png or jpeg.")
        quality = arguments.get("quality")
        if quality is not None and (not _is_int(quality) or int(quality) < 1 or int(quality) > 100):
            return _deny("BrowserScreenshot quality must be between 1 and 100.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScreenshot",
        )
        if target_error:
            return _target_error_result(call, "BrowserScreenshot", target_error)
        await _progress(context, call, "Capturing browser screenshot...", {"page_id": target_id})
        try:
            data = await worker.screenshot(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
                full_page=bool(arguments.get("full_page", False)),
                image_format=str(arguments.get("format") or "png"),
                quality=int(arguments["quality"]) if _is_int(arguments.get("quality")) else None,
            )
        except Exception as exc:
            return _error(call, "BrowserScreenshot", str(exc), exc)
        return _json_result(call, "BrowserScreenshot", _prepare_browser_control_response(data, keep_image=True))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserScreenshot",
            description="Capture pixels through Chrome/Chromium CDP, or return a LightPanda DOM-mirror fallback.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "full_page": {"type": "boolean", "default": False},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "quality": {"type": "integer", "minimum": 1, "maximum": 100},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser screenshot pixels image capture cdp lightpanda",
            max_result_size_chars=240_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )
