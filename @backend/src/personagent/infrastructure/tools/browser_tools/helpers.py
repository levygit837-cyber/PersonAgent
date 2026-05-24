"""Private helpers for browser tool factories.

Extracted from ``browser_tools.py`` as part of browser_tools Slice 1.
Pure functions and constants — no tool definitions.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

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
from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.tools.browser_tools.link_helpers import (  # noqa: F401
    _MARKDOWN_LINK_PATTERN,
    _coerce_links,
    _curate_links,
    _extract_markdown_links,
    _is_low_quality_link,
)

# ---------------------------------------------------------------------------
# Module-level singletons & constants
# ---------------------------------------------------------------------------

_BROWSER_ACTION_ARBITER = BrowserActionArbiter()

_DEFAULT_CHUNK_SIZE = 3_000
_EXTRACT_INLINE_CONTENT_CHARS = 8_000
_MAX_CHUNK_COUNT = 6

_PAGE_CACHE = get_browser_page_cache()
_BROWSER_EXTRACT_IN_FLIGHT: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
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


def _prepare_extracted_content_response(
    *,
    conversation_id: str,
    data: dict[str, Any],
    include_links: bool,
) -> dict[str, Any]:
    content = str(data.get("content") or "").strip()
    data["content"] = content
    data["content_chars"] = len(content)
    data["chunk_size"] = _DEFAULT_CHUNK_SIZE
    if not content:
        data.update(
            {
                "cache_key": None,
                "chunk_count": 0,
                "chunks_available": False,
                "content_available_in_chunks": False,
                "content_unavailable": True,
                "links": [],
                "links_summary": {
                    "total": 0,
                    "returned": 0,
                    "suppressed": False,
                    "reason": "no_readable_content",
                },
                "buttons": [],
                "message": (
                    "No readable page content was extracted. Try BrowserGetHtml, another source, "
                    "or opening the page in the browser before extracting again."
                ),
            }
        )
        return data

    cache_metadata = _cache_page_content(conversation_id, data)
    data.update(cache_metadata)
    if not include_links:
        data["links"] = []
    if len(content) > _EXTRACT_INLINE_CONTENT_CHARS:
        preview = _trim_content(content, _EXTRACT_INLINE_CONTENT_CHARS)
        data["content"] = preview
        data["content_preview"] = preview
        data["inline_content_truncated"] = True
        data["content_available_in_chunks"] = True
    else:
        data["content_preview"] = content
        data["inline_content_truncated"] = False
        data["content_available_in_chunks"] = False
    data["chunks_available"] = bool(data.get("chunk_count"))
    return data


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def _run_deduped_browser_extract(
    browser_id: str,
    target_key: str,
    factory: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], bool]:
    key_value = str(target_key or "").strip()
    if not key_value:
        return await factory(), False
    key = (browser_id, key_value)
    task = _BROWSER_EXTRACT_IN_FLIGHT.get(key)
    owner = task is None
    if task is None:
        task = asyncio.create_task(factory())
        _BROWSER_EXTRACT_IN_FLIGHT[key] = task
    try:
        data = await task
        return dict(data), not owner
    finally:
        if owner and _BROWSER_EXTRACT_IN_FLIGHT.get(key) is task:
            _BROWSER_EXTRACT_IN_FLIGHT.pop(key, None)


def _cached_extracted_content_response(
    entry: Any,
    *,
    max_chars: int,
    include_links: bool,
) -> dict[str, Any]:
    metadata = _PAGE_CACHE.metadata(entry)
    chunk_count = max(1, min(entry.chunk_count, _MAX_CHUNK_COUNT))
    chunks = _PAGE_CACHE.read_chunks(entry, 1, chunk_count)
    content = "\n\n".join(chunks).strip()
    if len(content) > max_chars:
        content = _trim_content(content, max_chars)
    returned_links = metadata.get("links", []) if include_links and isinstance(metadata.get("links"), list) else []
    links_summary = metadata.get("links_summary") if isinstance(metadata.get("links_summary"), dict) else {}
    buttons = metadata.get("buttons") if isinstance(metadata.get("buttons"), list) else []
    return {
        "type": "browser_extract_content",
        "browser_id": entry.conversation_id,
        "url": entry.url,
        "title": entry.title,
        "page_id": entry.page_id,
        "window_id": entry.page_id,
        "content": content,
        "content_preview": content,
        "content_chars": entry.content_chars,
        "chunk_size": entry.chunk_size or _DEFAULT_CHUNK_SIZE,
        "chunk_count": entry.chunk_count,
        "cache_key": entry.cache_key,
        "links": returned_links,
        "links_summary": links_summary,
        "buttons": buttons,
        "truncated": entry.content_chars > len(content),
        "inline_content_truncated": entry.content_chars > len(content),
        "content_available_in_chunks": entry.chunk_count > 1,
        "chunks_available": entry.chunk_count > 0,
        "already_read": True,
        "read_status": "cached",
        "duplicate_read_avoided": True,
    }


# ---------------------------------------------------------------------------
# Element map & content caching
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


def _cache_page_content(conversation_id: str, data: dict[str, Any]) -> dict[str, Any]:
    content = str(data.get("content") or "")
    if not content:
        return {}
    url = str(data.get("url") or "")
    title = str(data.get("title") or "")
    digest = sha256(f"{url}\n{title}\n{content[:256]}".encode()).hexdigest()[:12]
    cache_key = f"page_{digest}"
    chunks, ranges = _split_content_chunks(content, _DEFAULT_CHUNK_SIZE)
    raw_links = _coerce_links(data.get("links"))
    if not raw_links:
        raw_links = _extract_markdown_links(content)
    links, links_summary = _curate_links(raw_links, content=content, source_url=url)
    page_id = _coerce_page_or_window_id(data.get("page_id"), data.get("window_id"))
    buttons = data.get("buttons") if isinstance(data.get("buttons"), list) else []
    entry = _PAGE_CACHE.store(
        conversation_id=conversation_id,
        cache_key=cache_key,
        url=url,
        title=title,
        page_id=page_id,
        content_chars=len(content),
        chunk_size=_DEFAULT_CHUNK_SIZE,
        chunks=chunks,
        chunk_ranges=ranges,
        links=links,
        links_summary=links_summary,
        buttons=buttons,
    )
    return {
        "cache_key": cache_key,
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunk_count": len(chunks),
        "page_id": entry.page_id,
        "window_id": entry.page_id,
        "links": links,
        "links_summary": links_summary,
        "buttons": buttons,
    }


# ---------------------------------------------------------------------------
# Content chunking & trimming
# ---------------------------------------------------------------------------


def _split_content_chunks(content: str, chunk_size: int) -> tuple[list[str], list[tuple[int, int]]]:
    chunks: list[str] = []
    ranges: list[tuple[int, int]] = []
    index = 0
    total = len(content)
    while index < total:
        hard_end = min(index + chunk_size, total)
        end = hard_end
        if hard_end < total:
            boundary = max(
                content.rfind("\n\n", index, hard_end),
                content.rfind("\n", index, hard_end),
                content.rfind(". ", index, hard_end),
            )
            if boundary > index + int(chunk_size * 0.55):
                end = boundary + (2 if content.startswith("\n\n", boundary) else 1)
        chunk = content[index:end].strip()
        if chunk:
            chunks.append(chunk)
            ranges.append((index, end))
        index = max(end, index + 1)
    return chunks, ranges


def _trim_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    boundary = max(
        content.rfind("\n\n", 0, max_chars),
        content.rfind("\n", 0, max_chars),
        content.rfind(". ", 0, max_chars),
    )
    if boundary > int(max_chars * 0.6):
        return content[: boundary + 1].rstrip()
    return content[:max_chars].rstrip()





# ---------------------------------------------------------------------------
# Argument normalization & validation
# ---------------------------------------------------------------------------


def _resolve_cache_key(conversation_id: str, raw_cache_key: Any) -> str | None:
    return _PAGE_CACHE.resolve_key(conversation_id, raw_cache_key)


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


def _coerce_page_or_window_id(page_id: Any, window_id: Any) -> str | None:
    if isinstance(page_id, str) and page_id.strip():
        return page_id.strip()
    if isinstance(window_id, str) and window_id.strip():
        return window_id.strip()
    return None


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
# Workspace / session / target helpers
# ---------------------------------------------------------------------------


def _browser_session_id(context: ToolUseContext) -> str:
    override = context.metadata.get("_browser_session_id_override")
    if isinstance(override, str) and override.strip():
        return override.strip()
    target = _browser_target(context)
    target_browser_id = str(target.get("browser_id") or "").strip()
    if target_browser_id:
        return target_browser_id
    active_browser_id = str(_browser_workspace(context).get("active_browser_id") or "").strip()
    if active_browser_id:
        return active_browser_id
    return context.conversation_id


def _browser_workspace(context: ToolUseContext) -> Mapping[str, Any]:
    workspace = context.metadata.get("browser_workspace")
    return workspace if isinstance(workspace, Mapping) else {}


def _browser_workspace_active_tab_id(context: ToolUseContext) -> str | None:
    workspace = _browser_workspace(context)
    active_tab_id = str(workspace.get("active_tab_id") or "").strip()
    if active_tab_id:
        return active_tab_id
    tabs = _workspace_browser_tabs(workspace, browser_id=_browser_session_id(context))
    active = next(
        (
            tab
            for tab in tabs
            if bool(tab.get("active") or tab.get("is_active") or tab.get("is_current_page"))
        ),
        None,
    )
    if active:
        return str(active.get("page_id") or active.get("window_id") or active.get("tab_id") or "").strip() or None
    return None


def _browser_workspace_current_url(context: ToolUseContext) -> str | None:
    workspace = _browser_workspace(context)
    url = str(workspace.get("current_url") or "").strip()
    if not url:
        tabs = _workspace_browser_tabs(workspace, browser_id=_browser_session_id(context))
        active = next(
            (
                tab
                for tab in tabs
                if bool(tab.get("active") or tab.get("is_active") or tab.get("is_current_page"))
            ),
            tabs[0] if tabs else None,
        )
        url = str((active or {}).get("final_url") or (active or {}).get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return None


def _browser_view_is_about_blank(view: Mapping[str, Any]) -> bool:
    url = str(view.get("url") or "").strip()
    return not url or url == "about:blank"


def _merge_shared_browser_workspace_tabs(
    data: dict[str, Any],
    context: ToolUseContext,
    *,
    browser_id: str,
    max_tabs: int,
) -> dict[str, Any]:
    result = dict(data)
    workspace = context.metadata.get("browser_workspace")
    if not isinstance(workspace, Mapping):
        result.setdefault("browser_id", browser_id)
        return result
    workspace_tabs = _workspace_browser_tabs(workspace, browser_id=browser_id)
    if not workspace_tabs:
        result.setdefault("browser_id", browser_id)
        return result
    existing_tabs = result.get("tabs") if isinstance(result.get("tabs"), list) else []
    if existing_tabs and int(result.get("tab_count") or 0) > 0:
        merged = [_normalize_browser_tab_for_tool(tab, browser_id=browser_id) for tab in existing_tabs if isinstance(tab, Mapping)]
    else:
        merged = workspace_tabs
    result["type"] = "browser_tabs"
    result["browser_id"] = browser_id
    result["active_browser_id"] = str(workspace.get("active_browser_id") or browser_id)
    result["tab_count"] = len(merged[:max_tabs])
    result["current_url"] = result.get("current_url") or str(workspace.get("current_url") or "")
    active_tab_id = str(workspace.get("active_tab_id") or "")
    result["last_open_page_id"] = result.get("last_open_page_id") or active_tab_id or (merged[0].get("page_id") if merged else None)
    result["last_open_window_id"] = result.get("last_open_window_id") or active_tab_id or (merged[0].get("window_id") if merged else None)
    result["tabs"] = merged[:max_tabs]
    return result


def _workspace_browser_tabs(workspace: Mapping[str, Any], *, browser_id: str) -> list[dict[str, Any]]:
    raw_tabs = workspace.get("tabs")
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    current_url = str(workspace.get("current_url") or "").strip()
    active_tab_id = str(workspace.get("active_tab_id") or browser_id).strip()
    if not tabs and current_url:
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": current_url,
                "final_url": current_url,
                "title": str(workspace.get("current_title") or ""),
                "active": True,
                "is_active": True,
                "runtime": "lightpanda",
            }
        ]
    return [
        _normalize_browser_tab_for_tool(tab, browser_id=browser_id, index=index)
        for index, tab in enumerate(tabs, start=1)
        if isinstance(tab, Mapping)
    ]


def _normalize_browser_tab_for_tool(
    tab: Mapping[str, Any],
    *,
    browser_id: str,
    index: int | None = None,
) -> dict[str, Any]:
    page_id = str(tab.get("page_id") or tab.get("window_id") or tab.get("tab_id") or tab.get("id") or browser_id)
    url = str(tab.get("final_url") or tab.get("url") or "")
    title = str(tab.get("title") or "")
    parsed = urlparse(url)
    domain = parsed.netloc
    active = bool(tab.get("active") or tab.get("is_active"))
    extraction_count = int(tab.get("extraction_count") or 0)
    already_read = bool(tab.get("already_read")) or extraction_count > 0
    return {
        "index": int(tab.get("index") or index or 1),
        "browser_id": str(tab.get("browser_id") or browser_id),
        "page_id": page_id,
        "window_id": page_id,
        "tab_id": page_id,
        "id": page_id,
        "url": str(tab.get("url") or url),
        "final_url": url,
        "domain": domain,
        "title": title,
        "summary": str(tab.get("summary") or title or domain or url),
        "runtime": str(tab.get("runtime") or ""),
        "source_search_id": tab.get("source_search_id"),
        "opener_tool_call_id": tab.get("opener_tool_call_id"),
        "extraction_count": extraction_count,
        "already_read": already_read,
        "read_status": str(tab.get("read_status") or ("read" if already_read else "unread")),
        "is_last_open": bool(tab.get("is_last_open") or active),
        "is_current_page": bool(tab.get("is_current_page") or active),
        "active": active,
        "is_active": active,
        "history": tab.get("history") if isinstance(tab.get("history"), list) else ([url] if url else []),
        "state": dict(tab.get("state")) if isinstance(tab.get("state"), dict) else {},
        "updated_at": str(tab.get("updated_at") or ""),
    }


# ---------------------------------------------------------------------------
# Page target resolution
# ---------------------------------------------------------------------------


def _resolve_browser_page_target(
    arguments: ToolArguments,
    context: ToolUseContext,
    *,
    tool_name: str,
    block_url_argument: bool = False,
) -> tuple[str | None, str | None]:
    requested = _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id"))
    requested_browser_id = str(arguments.get("browser_id") or "").strip()
    has_url_argument = isinstance(arguments.get("url"), str) and bool(arguments["url"].strip())
    if arguments.get("browser_id") is not None and not requested_browser_id:
        return requested, f"{tool_name} browser_id must be a non-empty string."
    target = _browser_target(context)
    target_id = _browser_target_page_id(target)
    target_browser_id = str(target.get("browser_id") or "").strip()
    workspace_browser_id = str(_browser_workspace(context).get("active_browser_id") or "").strip()
    workspace_target_id = _browser_workspace_active_tab_id(context)
    if requested_browser_id and target_browser_id and requested_browser_id != target_browser_id:
        return (
            requested,
            (
                f"{tool_name} cannot target browser_id {requested_browser_id} because the user attached "
                f"Browser workspace {target_browser_id} for this turn."
            ),
        )
    if requested_browser_id:
        context.metadata["_browser_session_id_override"] = requested_browser_id
    elif requested and requested.startswith("browser:"):
        context.metadata["_browser_session_id_override"] = requested
    if not target_id:
        if requested:
            return requested, None
        if workspace_target_id and not has_url_argument and (
            not requested_browser_id or not workspace_browser_id or requested_browser_id == workspace_browser_id
        ):
            return workspace_target_id, None
        return None, None
    if block_url_argument and has_url_argument:
        return (
            requested or target_id,
            (
                f"{tool_name} is bound to the referenced Browser tab {target_id}; "
                "omit url and operate on the attached shared tab instead of opening or reading another page."
            ),
        )
    if requested and requested != target_id:
        return (
            requested,
            (
                f"{tool_name} cannot target page_id/window_id {requested} because the user attached "
                f"Browser tab {target_id} for this turn."
            ),
        )
    return requested or target_id, None


def _browser_targeted_arguments(
    arguments: ToolArguments,
    context: ToolUseContext,
    *,
    tool_name: str,
) -> tuple[ToolArguments, str | None]:
    target_id, error = _resolve_browser_page_target(arguments, context, tool_name=tool_name)
    if error:
        return arguments, error
    if not target_id or _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id")):
        return arguments, None
    updated = dict(arguments)
    updated["page_id"] = target_id
    updated["window_id"] = target_id
    return updated, None


def _browser_target(context: ToolUseContext) -> dict[str, Any]:
    target = context.metadata.get("browser_target")
    return dict(target) if isinstance(target, Mapping) else {}


def _browser_target_page_id(target: Mapping[str, Any]) -> str | None:
    return _coerce_page_or_window_id(
        target.get("page_id") or target.get("tab_id"),
        target.get("window_id"),
    )


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
