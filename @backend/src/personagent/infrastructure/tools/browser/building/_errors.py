"""Error and result helpers for browser tools."""

from __future__ import annotations

import json

from personagent.application.services.insights.browser_action_arbiter import BrowserActionArbiter
from personagent.domain.tools import (
    ToolArguments,
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
)
from personagent.infrastructure.tools.browser.workspace_target import (
    _browser_targeted_arguments,
)

_BROWSER_ACTION_ARBITER = BrowserActionArbiter()


def _target_error_result(call: ToolCall, tool_name: str, message: str) -> ToolResult:
    data = {
        "type": _error_type(tool_name),
        "error": message,
        "browser_target_conflict": True,
    }
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        data=data,
    )


def _error(
    call: ToolCall,
    tool_name: str,
    message: str,
    exc: Exception | None = None,
) -> ToolResult:
    data = {"type": _error_type(tool_name), "error": message}
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        data["details"] = {key: value for key, value in details.items() if value}
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data,
    )


def _error_type(tool_name: str) -> str:
    return {
        "BrowserSearch": "browser_search",
        "BrowserOpen": "browser_open",
        "BrowserListTabs": "browser_tabs",
        "BrowserExtractContent": "browser_extract_content",
        "BrowserReadContentChunk": "browser_content_chunks",
        "BrowserGetHtml": "browser_get_html",
        "BrowserGetElementMap": "browser_element_map",
        "BrowserClick": "browser_click",
        "BrowserType": "browser_type",
        "BrowserScreenshot": "browser_screenshot",
        "BrowserCloseTab": "browser_close_tab",
        "BrowserReadConsole": "browser_console",
        "BrowserScript": "browser_script",
        "BrowserScroll": "browser_scroll",
        "BrowserReload": "browser_reload",
        "BrowserHistory": "browser_history",
        "BrowserSwitchTab": "browser_switch_tab",
        "BrowserWait": "browser_wait",
        "BrowserAct": "browser_action",
    }.get(tool_name, "browser")


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


async def _browser_action_permission(
    tool_name: str,
    arguments: ToolArguments,
    context: ToolUseContext,
) -> ToolPermissionResult:
    targeted_arguments, target_error = _browser_targeted_arguments(
        arguments,
        context,
        tool_name=tool_name,
    )
    if target_error:
        return _deny(target_error)
    permission = _BROWSER_ACTION_ARBITER.decide(
        tool_name=tool_name,
        arguments=targeted_arguments,
        context=context,
    ).to_permission_result()
    if targeted_arguments is not arguments:
        return ToolPermissionResult(
            behavior=permission.behavior,
            message=permission.message,
            updated_input=targeted_arguments,
            metadata=permission.metadata,
        )
    return permission
