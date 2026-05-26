"""BrowserAct tool factory."""

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
    _BROWSER_ACTIONS,
    _browser_action_permission,
    _browser_session_id,
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
