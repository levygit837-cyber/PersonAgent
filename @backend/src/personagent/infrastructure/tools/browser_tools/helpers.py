"""Private helpers for browser tool factories.

Extracted from ``browser_tools.py`` as part of browser_tools Slice 1.
Pure functions and constants — no tool definitions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from personagent.application.services.browser_action_arbiter import BrowserActionArbiter
from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.browser_tools.content_cache import (  # noqa: F401
    _DEFAULT_CHUNK_SIZE,
    _EXTRACT_INLINE_CONTENT_CHARS,
    _MAX_CHUNK_COUNT,
    _PAGE_CACHE,
    _cache_page_content,
    _cached_extracted_content_response,
    _coerce_page_or_window_id,
    _prepare_extracted_content_response,
    _resolve_cache_key,
    _run_deduped_browser_extract,
    _split_content_chunks,
    _trim_content,
)
from personagent.infrastructure.tools.browser_tools.link_helpers import (  # noqa: F401
    _MARKDOWN_LINK_PATTERN,
    _coerce_links,
    _curate_links,
    _extract_markdown_links,
    _is_low_quality_link,
)
from personagent.infrastructure.tools.browser_tools.workspace_target import (  # noqa: F401
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_targeted_arguments,
    _browser_view_is_about_blank,
    _browser_workspace,
    _browser_workspace_active_tab_id,
    _browser_workspace_current_url,
    _merge_shared_browser_workspace_tabs,
    _normalize_browser_tab_for_tool,
    _resolve_browser_page_target,
    _workspace_browser_tabs,
)

# ---------------------------------------------------------------------------
# Module-level singletons & constants
# ---------------------------------------------------------------------------

_BROWSER_ACTION_ARBITER = BrowserActionArbiter()


_BROWSER_OPEN_URL_KEYS = ("url", "result_url", "final_url", "href", "link")
_BROWSER_OPEN_INDEX_KEYS = (
    "result_index",
    "index",
    "resultIndex",
    "position",
    "result_number",
    "result",
)
_BROWSER_OPEN_DIRECT_INDEX_KEYS = tuple(
    key for key in _BROWSER_OPEN_INDEX_KEYS if key != "result"
)
_BROWSER_OPEN_SEARCH_ID_KEYS = ("search_id", "searchId")
_BROWSER_ACTIONS = {
    "click",
    "fill",
    "submit",
    "select",
    "press",
    "hover",
    "wait",
    "drag",
    "drop",
    "upload",
    "select_text",
    "scroll_to",
    "screenshot",
}
_BROWSER_CONTROL_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}
_BROWSER_CONSOLE_LEVELS = {"debug", "error", "info", "log", "warning", "warn"}

# ---------------------------------------------------------------------------
# Tool building helpers
# ---------------------------------------------------------------------------


def _simple_browser_control_tool(
    *,
    name: str,
    description: str,
    schema_properties: dict[str, Any],
    search_hint: str,
    handler: Any,
    validate: Any,
) -> Tool:
    permission_kwargs = {}
    if name != "BrowserWait":
        permission_kwargs["check_permissions"] = (
            lambda args, context: _browser_action_permission(name, args, context)
        )
    return build_tool(
        definition=ToolDefinition(
            name=name,
            description=description,
            input_schema={
                "type": "object",
                "properties": schema_properties,
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint=search_hint,
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        **permission_kwargs,
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def _page_target_schema() -> dict[str, Any]:
    return {
        "browser_id": {
            "type": "string",
            "description": "Optional shared Browser panel id returned by BrowserListTabs. Defaults to the active shared browser.",
        },
        "page_id": {
            "type": "string",
            "description": "Optional page_id returned by BrowserOpen or BrowserListTabs.",
        },
        "window_id": {
            "type": "string",
            "description": "Alias for page_id. If both are provided they must match.",
        },
    }


def _viewport_schema() -> dict[str, Any]:
    return {
        "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
        "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
    }


def _validate_browser_dimensions(arguments: ToolArguments, tool_name: str) -> ToolPermissionResult | None:
    width = arguments.get("width", 1024)
    height = arguments.get("height", 720)
    if not _is_int(width) or int(width) < 320 or int(width) > 2400:
        return _deny(f"{tool_name} width must be between 320 and 2400.")
    if not _is_int(height) or int(height) < 240 or int(height) > 1800:
        return _deny(f"{tool_name} height must be between 240 and 1800.")
    return None


def _browser_width(arguments: ToolArguments) -> int:
    return min(max(320, int(arguments.get("width") or 1024)), 2400)


def _browser_height(arguments: ToolArguments) -> int:
    return min(max(240, int(arguments.get("height") or 720)), 1800)


# ---------------------------------------------------------------------------
# Response preparation
# ---------------------------------------------------------------------------


def _prepare_browser_control_response(
    data: dict[str, Any],
    *,
    keep_image: bool = False,
    element_limit: int = 60,
) -> dict[str, Any]:
    result = dict(data)
    elements = _summarize_element_map(result.pop("element_map", []))
    result["element_count"] = len(elements)
    result["elements"] = elements[:element_limit]
    result.pop("browser_snapshot", None)
    result.pop("frame_tree", None)
    if keep_image:
        if result.get("image_data"):
            result.pop("html", None)
            result.pop("document_html", None)
        return result
    result.pop("image_data", None)
    result.pop("image_mime_type", None)
    result.pop("html", None)
    result.pop("document_html", None)
    return result


async def _progress(
    context: ToolUseContext,
    call: ToolCall,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    await context.emit_progress(
        ToolProgress(
            tool_call_id=call.id,
            tool_name=call.name,
            status=ToolExecutionStatus.RUNNING,
            message=message,
            data=data or {},
        )
    )


def _json_result(call: ToolCall, tool_name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.COMPLETED,
        data=data,
    )


# ---------------------------------------------------------------------------
# Element map summarization
# ---------------------------------------------------------------------------


def _summarize_element_map(raw_map: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    if not isinstance(raw_map, list):
        return elements
    for item in raw_map:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        elements.append(
            {
                "node_id": node_id,
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": " ".join(str(item.get("text") or "").split())[:180],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [],
                "shadow_path": item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else [],
                "interactable": bool(item.get("interactable")),
                "stable_key": str(item.get("stable_key") or ""),
                "computed_summary": item.get("computed_summary") if isinstance(item.get("computed_summary"), dict) else {},
                "form_action": str(item.get("form_action") or ""),
                "input_type": str(item.get("input_type") or ""),
                "bounds": item.get("bounds") if isinstance(item.get("bounds"), dict) else {},
            }
        )
        if len(elements) >= 120:
            break
    return elements


# ---------------------------------------------------------------------------
# Argument normalization & validation
# ---------------------------------------------------------------------------


def _normalize_browser_open_arguments(arguments: ToolArguments) -> dict[str, Any]:
    """Recover common model argument variants while preserving canonical behavior."""

    url, url_key = _first_non_empty_string_with_key(arguments, _BROWSER_OPEN_URL_KEYS)
    search_id, search_id_key, invalid_search_id = _first_string_with_key(
        arguments,
        _BROWSER_OPEN_SEARCH_ID_KEYS,
    )
    raw_result_index, index_key = _first_present_with_key(
        arguments,
        _BROWSER_OPEN_DIRECT_INDEX_KEYS,
    )
    recovered_from: list[str] = []
    raw_result = arguments.get("result")

    if isinstance(raw_result, Mapping):
        if not url:
            url, url_key = _first_non_empty_string_with_key(raw_result, _BROWSER_OPEN_URL_KEYS)
        if not search_id and not invalid_search_id:
            search_id, search_id_key, invalid_search_id = _first_string_with_key(
                raw_result,
                _BROWSER_OPEN_SEARCH_ID_KEYS,
            )
        if raw_result_index is None:
            raw_result_index, index_key = _first_present_with_key(
                raw_result,
                _BROWSER_OPEN_INDEX_KEYS,
            )
    elif raw_result is not None and raw_result_index is None:
        raw_result_index = raw_result
        index_key = "result"

    if isinstance(raw_result, str) and raw_result.strip().startswith(("http://", "https://")):
        if not url:
            url = raw_result.strip()
            url_key = "result"
        if index_key == "result":
            raw_result_index = None
            index_key = ""

    result_index = int(raw_result_index) if _is_int(raw_result_index) else None
    invalid_result_index = raw_result_index is not None and result_index is None
    if url_key and url_key != "url":
        recovered_from.append(url_key)
    if index_key and index_key != "result_index":
        recovered_from.append(index_key)
    if search_id_key and search_id_key != "search_id":
        recovered_from.append(search_id_key)
    if search_id and result_index is None and not url:
        recovered_from.append("search_id_only_default_result_1")

    return {
        "url": url,
        "result_index": result_index,
        "search_id": search_id,
        "invalid_result_index": invalid_result_index,
        "invalid_search_id": invalid_search_id,
        "recovered_from": sorted(set(recovered_from)),
    }


def _first_present_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[Any | None, str]:
    for key in keys:
        if key in values:
            return values[key], key
    return None, ""


def _first_non_empty_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str]:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    return None, ""


def _first_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str, bool]:
    for key in keys:
        if key not in values:
            continue
        value = values[key]
        if value is None:
            continue
        if not isinstance(value, str):
            return None, key, True
        if value.strip():
            return value.strip(), key, False
    return None, "", False


def _validate_page_or_window_id(
    page_id: Any,
    window_id: Any,
    *,
    tool_name: str,
    browser_id: Any = None,
) -> ToolPermissionResult | None:
    if browser_id is not None and (not isinstance(browser_id, str) or not browser_id.strip()):
        return _deny(f"{tool_name} browser_id must be a non-empty string.")
    if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
        return _deny(f"{tool_name} page_id must be a non-empty string.")
    if window_id is not None and (not isinstance(window_id, str) or not window_id.strip()):
        return _deny(f"{tool_name} window_id must be a non-empty string.")
    if (
        isinstance(page_id, str)
        and page_id.strip()
        and isinstance(window_id, str)
        and window_id.strip()
        and page_id.strip() != window_id.strip()
    ):
        return _deny(f"{tool_name} requires either page_id or window_id, not both.")
    return None



# ---------------------------------------------------------------------------
# Error / result helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Misc utilities
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float) and not value.is_integer():
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _browser_result_max_chars(context: ToolUseContext) -> int:
    raw_limit = context.limits.get("result_max_chars")
    if raw_limit is None:
        return 60_000
    try:
        parsed = int(raw_limit)
    except (TypeError, ValueError):
        return 60_000
    return parsed if parsed > 0 else 60_000
