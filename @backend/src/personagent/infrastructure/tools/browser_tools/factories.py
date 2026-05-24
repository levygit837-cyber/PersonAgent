"""LightPanda browser tools for the main chat agent."""

from __future__ import annotations

import json

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
    _BROWSER_ACTIONS,
    _BROWSER_CONSOLE_LEVELS,
    _BROWSER_CONTROL_CDP_ALLOWLIST,
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
    _summarize_element_map,
    _target_error_result,
    _validate_browser_dimensions,
    _validate_page_or_window_id,
    _viewport_schema,
)
from personagent.infrastructure.tools.browser_tools.navigation import (
    create_browser_extract_content_tool,
    create_browser_get_element_map_tool,
    create_browser_get_html_tool,
    create_browser_open_tool,
    create_browser_read_content_chunk_tool,
    create_browser_search_tool,
)


def create_browser_tools(worker: LightPandaBrowserWorker) -> list[Tool]:
    """Create all LightPanda browser tools."""

    return [
        create_browser_search_tool(worker),
        create_browser_open_tool(worker),
        create_browser_list_tabs_tool(worker),
        create_browser_extract_content_tool(worker),
        create_browser_read_content_chunk_tool(),
        create_browser_get_html_tool(worker),
        create_browser_get_element_map_tool(worker),
        create_browser_click_tool(worker),
        create_browser_type_tool(worker),
        create_browser_screenshot_tool(worker),
        create_browser_close_tab_tool(worker),
        create_browser_read_console_tool(worker),
        create_browser_script_tool(worker),
        create_browser_scroll_tool(worker),
        create_browser_reload_tool(worker),
        create_browser_history_tool(worker),
        create_browser_switch_tab_tool(worker),
        create_browser_wait_tool(worker),
        create_browser_act_tool(worker),
    ]

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
        if not _is_int(delay_ms) or int(delay_ms) < 0 or int(delay_ms) > 1000:
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


def create_browser_script_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScript",
        )
        if target_error is not None:
            return target_error
        mode = arguments.get("mode", "evaluate")
        if mode not in {"evaluate", "cdp"}:
            return _deny("BrowserScript mode must be evaluate or cdp.")
        if mode == "evaluate":
            script = arguments.get("script")
            if not isinstance(script, str) or not script.strip():
                return _deny("BrowserScript evaluate requires a non-empty script.")
            if len(script) > 10_000:
                return _deny("BrowserScript script must be 10000 characters or fewer.")
        else:
            method = arguments.get("cdp_method")
            if method not in _BROWSER_CONTROL_CDP_ALLOWLIST:
                return _deny(
                    "BrowserScript cdp_method must be one of: "
                    + ", ".join(sorted(_BROWSER_CONTROL_CDP_ALLOWLIST))
                    + "."
                )
            cdp_params = arguments.get("cdp_params")
            if cdp_params is not None and not isinstance(cdp_params, dict):
                return _deny("BrowserScript cdp_params must be an object.")
            if isinstance(cdp_params, dict):
                if len(json.dumps(cdp_params, ensure_ascii=False, default=str)) > 10_000:
                    return _deny("BrowserScript cdp_params must be 10000 serialized characters or fewer.")
                expression = cdp_params.get("expression")
                if isinstance(expression, str) and len(expression) > 10_000:
                    return _deny("BrowserScript Runtime.evaluate expression must be 10000 characters or fewer.")
        timeout_ms = arguments.get("timeout_ms", 5000)
        if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 30_000:
            return _deny("BrowserScript timeout_ms must be between 1 and 30000.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScript",
        )
        if target_error:
            return _target_error_result(call, "BrowserScript", target_error)
        mode = str(arguments.get("mode") or "evaluate")
        await _progress(context, call, f"Running browser script ({mode})...", {"page_id": target_id})
        try:
            data = await worker.script(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                mode=mode,
                script=arguments.get("script") if isinstance(arguments.get("script"), str) else None,
                args=arguments.get("args"),
                cdp_method=arguments.get("cdp_method") if isinstance(arguments.get("cdp_method"), str) else None,
                cdp_params=arguments.get("cdp_params") if isinstance(arguments.get("cdp_params"), dict) else None,
                timeout_ms=int(arguments.get("timeout_ms") or 5000),
            )
        except Exception as exc:
            return _error(call, "BrowserScript", str(exc), exc)
        return _json_result(call, "BrowserScript", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserScript",
            description="Advanced allowlisted browser JS/CDP execution. Prefer explicit browser tools for normal actions.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "mode": {"type": "string", "enum": ["evaluate", "cdp"], "default": "evaluate"},
                    "script": {"type": "string"},
                    "args": {},
                    "cdp_method": {"type": "string", "enum": sorted(_BROWSER_CONTROL_CDP_ALLOWLIST)},
                    "cdp_params": {"type": "object", "additionalProperties": True},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 30000, "default": 5000},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser script javascript evaluate cdp runtime performance dom screenshot logs",
            max_result_size_chars=24_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=40_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserScript", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
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


def create_browser_act_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserAct",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        action = arguments.get("action")
        if not isinstance(node_id, str) or not node_id.strip():
            return _deny("BrowserAct requires a non-empty node_id.")
        if action not in _BROWSER_ACTIONS:
            return _deny(f"BrowserAct action must be one of: {', '.join(sorted(_BROWSER_ACTIONS))}.")
        if action in {"fill", "select"} and not isinstance(arguments.get("value"), str):
            return _deny("BrowserAct fill/select requires a string value.")
        if action == "press" and not isinstance(arguments.get("key", arguments.get("value", "")), str):
            return _deny("BrowserAct press requires key or value.")
        if action == "upload":
            files = arguments.get("files")
            if not isinstance(files, list) or not all(isinstance(item, str) and item.strip() for item in files):
                return _deny("BrowserAct upload requires a non-empty files array.")
        if action == "wait":
            timeout_ms = arguments.get("timeout_ms", arguments.get("value", 1000))
            if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 120_000:
                return _deny("BrowserAct wait timeout_ms must be between 1 and 120000.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        node_id = str(arguments["node_id"]).strip()
        action = str(arguments["action"]).strip()
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserAct",
        )
        if target_error:
            return _target_error_result(call, "BrowserAct", target_error)
        width = min(max(320, int(arguments.get("width") or 1024)), 2400)
        height = min(max(240, int(arguments.get("height") or 720)), 1800)
        value = arguments.get("value") if isinstance(arguments.get("value"), str) else None
        key = arguments.get("key") if isinstance(arguments.get("key"), str) else None
        target_node_id = arguments.get("target_node_id") if isinstance(arguments.get("target_node_id"), str) else None
        timeout_ms = int(arguments["timeout_ms"]) if _is_int(arguments.get("timeout_ms")) else None
        files = [str(item) for item in arguments.get("files", [])] if isinstance(arguments.get("files"), list) else None
        text = arguments.get("text") if isinstance(arguments.get("text"), str) else None
        x = float(arguments["x"]) if isinstance(arguments.get("x"), int | float) else None
        y = float(arguments["y"]) if isinstance(arguments.get("y"), int | float) else None
        await _progress(
            context,
            call,
            f"Running browser action {action}...",
            {"page_id": target_id, "node_id": node_id, "action": action},
        )
        try:
            if target_id:
                await worker.switch_tab(
                    conversation_id=_browser_session_id(context),
                    page_id=target_id,
                    max_tabs=20,
                )
            base_kwargs = {
                "browser_id": _browser_session_id(context),
                "node_id": node_id,
                "action": action,
                "value": value,
                "key": key,
                "width": width,
                "height": height,
            }
            extra_kwargs = {
                "target_node_id": target_node_id,
                "timeout_ms": timeout_ms,
                "files": files,
                "text": text,
                "x": x,
                "y": y,
            }
            compact_extra_kwargs = {key: next_value for key, next_value in extra_kwargs.items() if next_value is not None}
            try:
                view = await worker.view_act(**base_kwargs, **compact_extra_kwargs)
            except TypeError:
                if compact_extra_kwargs:
                    view = await worker.view_act(**base_kwargs)
                else:
                    raise
        except Exception as exc:
            return _error(call, "BrowserAct", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_action",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "runtime": view.get("runtime") or "",
            "render_mode": view.get("render_mode") or "",
            "css_fidelity": view.get("css_fidelity") or "",
            "active_tab_id": view.get("active_tab_id") or "",
            "node_id": node_id,
            "action": action,
            "last_action": view.get("last_action") or {},
            "element_count": len(elements),
            "elements": elements[:60],
        }
        return _json_result(call, "BrowserAct", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserAct",
            description=(
                "Advanced compatibility tool for mapped browser actions. Prefer BrowserClick, BrowserType, "
                "BrowserScroll, BrowserWait, and other explicit browser tools for normal automation. "
                "Supports click, fill, submit, select, press, hover, wait, drag/drop, upload, "
                "select_text, scroll_to, and screenshot."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string", "description": "Element node_id from BrowserGetElementMap."},
                    "action": {
                        "type": "string",
                        "enum": sorted(_BROWSER_ACTIONS),
                    },
                    "value": {"type": "string", "description": "Text/value for fill, select, or press."},
                    "key": {"type": "string", "description": "Keyboard key for press."},
                    "target_node_id": {"type": "string", "description": "Drop target node_id for drag/drop."},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 120000, "description": "Wait timeout."},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Local file paths for upload actions.",
                    },
                    "text": {"type": "string", "description": "Optional text payload for select_text."},
                    "x": {"type": "number", "description": "Viewport x coordinate for drag/drop fallback."},
                    "y": {"type": "number", "description": "Viewport y coordinate for drag/drop fallback."},
                    "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
                    "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
                },
                "required": ["node_id", "action"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser act click fill submit select press hover wait drag drop upload automation node_id",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserAct", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )
