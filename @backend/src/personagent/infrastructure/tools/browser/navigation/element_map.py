"""BrowserGetElementMap tool factory."""

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
    _browser_session_id,
    _browser_view_is_about_blank,
    _browser_workspace_current_url,
    _deny,
    _error,
    _is_int,
    _json_result,
    _page_target_schema,
    _progress,
    _resolve_browser_page_target,
    _summarize_element_map,
    _target_error_result,
    _validate_page_or_window_id,
)


def create_browser_get_element_map_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserGetElementMap",
        )
        if target_error is not None:
            return target_error
        width = arguments.get("width", 1024)
        height = arguments.get("height", 720)
        if not _is_int(width) or int(width) < 320 or int(width) > 2400:
            return _deny("BrowserGetElementMap width must be between 320 and 2400.")
        if not _is_int(height) or int(height) < 240 or int(height) > 1800:
            return _deny("BrowserGetElementMap height must be between 240 and 1800.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        width = min(max(320, int(arguments.get("width") or 1024)), 2400)
        height = min(max(240, int(arguments.get("height") or 720)), 1800)
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserGetElementMap",
        )
        if target_error:
            return _target_error_result(call, "BrowserGetElementMap", target_error)
        browser_id = _browser_session_id(context)
        await _progress(
            context,
            call,
            "Mapping browser elements...",
            {"browser_id": browser_id, "page_id": target_id, "width": width, "height": height},
        )
        try:
            if target_id:
                await worker.switch_tab(
                    conversation_id=browser_id,
                    page_id=target_id,
                    max_tabs=20,
                )
            view = await worker.view_snapshot(
                browser_id=browser_id,
                width=width,
                height=height,
            )
            workspace_url = _browser_workspace_current_url(context)
            if _browser_view_is_about_blank(view) and workspace_url:
                view = await worker.view_navigate(
                    browser_id=browser_id,
                    url=workspace_url,
                    width=width,
                    height=height,
                    cache_mode="prefer_live",
                    wait_for_styles=True,
                )
        except Exception as exc:
            return _error(call, "BrowserGetElementMap", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_element_map",
            "browser_id": view.get("browser_id") or browser_id,
            "page_id": target_id or view.get("active_tab_id") or "",
            "window_id": target_id or view.get("active_tab_id") or "",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "runtime": view.get("runtime") or "",
            "render_mode": view.get("render_mode") or "",
            "css_fidelity": view.get("css_fidelity") or "",
            "tabs": view.get("tabs") or [],
            "active_tab_id": view.get("active_tab_id") or "",
            "element_count": len(elements),
            "elements": elements,
        }
        return _json_result(call, "BrowserGetElementMap", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserGetElementMap",
            description=(
                "Return the current browser page's mapped links, buttons, inputs, forms, and "
                "important content blocks. Use node_id values with BrowserClick, BrowserType, "
                "or BrowserAct for advanced compatibility actions."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
                    "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser element map node_id ui automation",
            max_result_size_chars=24_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=30_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )
