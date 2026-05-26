"""Tab management browser tool factories.

Extracted from ``factories.py`` (browser_tools Slice 4).
Contains: BrowserListTabs, BrowserCloseTab, BrowserReload,
BrowserHistory, BrowserSwitchTab.
"""

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
    _PAGE_CACHE,
    _browser_action_permission,
    _browser_height,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_width,
    _coerce_page_or_window_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _merge_shared_browser_workspace_tabs,
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


def create_browser_list_tabs_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserListTabs max_tabs must be an integer between 1 and 50.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        max_tabs = min(max(1, int(arguments.get("max_tabs") or 20)), 50)
        await _progress(
            context,
            call,
            "Listing browser tabs...",
            {"max_tabs": max_tabs},
        )
        try:
            browser_id = _browser_session_id(context)
            data = await worker.list_tabs(
                conversation_id=browser_id,
                max_tabs=max_tabs,
            )
            data = _merge_shared_browser_workspace_tabs(
                data,
                context,
                browser_id=browser_id,
                max_tabs=max_tabs,
            )
        except Exception as exc:
            return _error(call, "BrowserListTabs", str(exc), exc)
        return _json_result(call, "BrowserListTabs", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserListTabs",
            description=(
                "List browser tabs/pages from the shared Browser panel and BrowserOpen state for "
                "the current chat conversation. Use this to recover browser_id/page_id values and "
                "keep browser work consistent with the visible panel. Each tab includes "
                "already_read/read_status/extraction_count; do not extract a tab again unless "
                "force_refresh is explicitly needed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "max_tabs": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 20,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser list tabs pages page_id research opened urls",
            is_read_only=True,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: True,
    )


def create_browser_close_tab_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserCloseTab",
        )
        if target_error is not None:
            return target_error
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserCloseTab max_tabs must be between 1 and 50.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserCloseTab",
        )
        if target_error:
            return _target_error_result(call, "BrowserCloseTab", target_error)
        await _progress(context, call, "Closing browser tab...", {"page_id": target_id})
        try:
            browser_id = _browser_session_id(context)
            data = await worker.close_tab(
                conversation_id=browser_id,
                page_id=target_id,
                max_tabs=min(max(1, int(arguments.get("max_tabs") or 20)), 50),
            )
            closed_page_id = str(data.get("closed_page_id") or target_id or "").strip() or None
            _PAGE_CACHE.clear_conversation(browser_id, page_id=closed_page_id)
        except Exception as exc:
            return _error(call, "BrowserCloseTab", str(exc), exc)
        return _json_result(call, "BrowserCloseTab", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserCloseTab",
            description="Close a logical browser tab/page, clear its caches, and return the updated tab state.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "max_tabs": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser close tab page window cleanup",
            is_read_only=False,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserCloseTab", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_reload_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserReload",
        )
        return target_error or _validate_browser_dimensions(arguments, "BrowserReload")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserReload",
        )
        if target_error:
            return _target_error_result(call, "BrowserReload", target_error)
        await _progress(context, call, "Reloading browser page...", {"page_id": target_id})
        try:
            data = await worker.reload(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserReload", str(exc), exc)
        return _json_result(call, "BrowserReload", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserReload",
        description="Reload the active or selected browser page.",
        schema_properties={**_page_target_schema(), **_viewport_schema()},
        search_hint="browser reload refresh page",
        handler=handler,
        validate=validate,
    )


def create_browser_history_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserHistory",
        )
        if target_error is not None:
            return target_error
        direction = arguments.get("direction", "back")
        if direction not in {"back", "forward"}:
            return _deny("BrowserHistory direction must be back or forward.")
        return _validate_browser_dimensions(arguments, "BrowserHistory")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserHistory",
        )
        if target_error:
            return _target_error_result(call, "BrowserHistory", target_error)
        direction = -1 if arguments.get("direction", "back") == "back" else 1
        await _progress(context, call, "Navigating browser history...", {"page_id": target_id, "direction": direction})
        try:
            data = await worker.history(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                direction=direction,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserHistory", str(exc), exc)
        return _json_result(call, "BrowserHistory", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserHistory",
        description="Move the selected browser page backward or forward in history.",
        schema_properties={
            **_page_target_schema(),
            "direction": {"type": "string", "enum": ["back", "forward"], "default": "back"},
            **_viewport_schema(),
        },
        search_hint="browser history back forward navigation",
        handler=handler,
        validate=validate,
    )


def create_browser_switch_tab_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserSwitchTab",
        )
        if target_error is not None:
            return target_error
        if not _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id")) and not _browser_target_page_id(_browser_target(context)):
            return _deny("BrowserSwitchTab requires page_id or window_id.")
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserSwitchTab max_tabs must be between 1 and 50.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserSwitchTab",
        )
        if target_error:
            return _target_error_result(call, "BrowserSwitchTab", target_error)
        await _progress(context, call, "Switching browser tab...", {"page_id": target_id})
        try:
            data = await worker.switch_tab(
                conversation_id=_browser_session_id(context),
                page_id=str(target_id),
                max_tabs=min(max(1, int(arguments.get("max_tabs") or 20)), 50),
            )
        except Exception as exc:
            return _error(call, "BrowserSwitchTab", str(exc), exc)
        return _json_result(call, "BrowserSwitchTab", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserSwitchTab",
            description="Activate a logical browser tab by page_id/window_id and return the updated tab state.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "max_tabs": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser switch tab activate page window",
            is_read_only=False,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserSwitchTab", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )
