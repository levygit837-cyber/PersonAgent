"""Workspace, session, and page-target resolution helpers.

Extracted from ``helpers.py`` as part of browser_tools helpers Slice C.
Groups functions that share the browser workspace/target state and the
page-target resolution verb.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from personagent.domain.tools import ToolArguments, ToolUseContext
from personagent.infrastructure.tools.browser_tools.content_cache import (
    _coerce_page_or_window_id,
)

# ---------------------------------------------------------------------------
# Workspace / session helpers
# ---------------------------------------------------------------------------


def _browser_workspace(context: ToolUseContext) -> Mapping[str, Any]:
    workspace = context.metadata.get("browser_workspace")
    return workspace if isinstance(workspace, Mapping) else {}


def _browser_target(context: ToolUseContext) -> dict[str, Any]:
    target = context.metadata.get("browser_target")
    return dict(target) if isinstance(target, Mapping) else {}


def _browser_target_page_id(target: Mapping[str, Any]) -> str | None:
    return _coerce_page_or_window_id(
        target.get("page_id") or target.get("tab_id"),
        target.get("window_id"),
    )


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


# ---------------------------------------------------------------------------
# Tab normalization & merging
# ---------------------------------------------------------------------------


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
