"""BrowserScript tool factory."""

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
from personagent.infrastructure.tools.browser.building import (
    _BROWSER_CONTROL_CDP_ALLOWLIST,
    _browser_action_permission,
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
