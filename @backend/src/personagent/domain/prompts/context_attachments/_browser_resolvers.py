"""Resolvers for browser-related context attachments."""

from __future__ import annotations

from typing import Any

from personagent.domain.prompts.context_attachments._utils import (
    MAX_BROWSER_ANNOTATION_CHARS,
    _attachment_label,
    _browser_tab_display_path,
    _coerce_dict,
    _single_line_preview,
    _string,
    _truncate,
    _wrap_attached_context,
)


def _resolve_browser_annotation(raw: dict[str, Any], *, index: int) -> tuple[str, dict[str, Any]]:
    label = _attachment_label(raw, index=index, fallback="@Annotation")
    url = _string(raw, "url", "browser_url", "browserUrl", default="")
    title = _string(raw, "title", "browser_title", "browserTitle", default="")
    node_id = _string(raw, "node_id", "nodeId", "browserNodeId", default="")
    selector = _string(raw, "selector", "browserSelector", default="")
    role = _string(raw, "role", "browserRole", default="")
    note = _string(raw, "text", "annotation", "note", default="")
    quote = _string(raw, "quote", "selected_text", "selectedText", "browserQuote", default="")
    quote, truncated = _truncate(quote, MAX_BROWSER_ANNOTATION_CHARS)
    metadata = {
        "type": "browser_annotation",
        "id": raw.get("id", index),
        "label": label,
        "url": url,
        "title": title,
        "node_id": node_id,
        "selector": selector,
        "role": role,
        "text": note,
        "content_preview": _single_line_preview(quote),
        "content_char_count": len(quote),
        "truncated": truncated,
    }
    reminder = _wrap_attached_context(
        "browser_annotation",
        [
            f"Label: {label}",
            f"URL: {url or '(unknown)'}",
            f"Title: {title or '(untitled)'}",
            f"Element node_id: {node_id or '(unknown)'}",
            f"Element role: {role or '(unknown)'}",
            f"Element selector: {selector or '(unknown)'}",
            f"User annotation: {note or '(none)'}",
            "",
            "Element visible text or extracted context:",
            quote or "(empty)",
        ],
    )
    return reminder, metadata


def _resolve_browser_tab(raw: dict[str, Any], *, index: int) -> tuple[str, dict[str, Any]]:
    label = _attachment_label(raw, index=index, fallback="@Browser")
    browser_id = _string(raw, "browser_id", "browserId", default="")
    tab_id = _string(raw, "tab_id", "tabId", "page_id", "pageId", "window_id", "windowId", default="")
    page_id = _string(raw, "page_id", "pageId", "window_id", "windowId", "tab_id", "tabId", default="")
    url = _string(raw, "url", "current_url", "currentUrl", default="")
    title = _string(raw, "title", "current_title", "currentTitle", default="")
    runtime = _string(raw, "runtime", default="")
    display_path = _string(raw, "display_path", "displayPath", default="") or _browser_tab_display_path(
        url,
        title,
    )
    state = _coerce_dict(raw.get("state"))
    scroll = _coerce_dict(raw.get("scroll") or state.get("scroll"))
    viewport = _coerce_dict(raw.get("viewport") or state.get("viewport"))
    selected_element = _coerce_dict(raw.get("selected_element") or raw.get("selectedElement") or state.get("selected_element"))
    active = bool(raw.get("active") or raw.get("is_active") or raw.get("isActive"))
    updated_at = _string(raw, "updated_at", "updatedAt", default="")
    metadata = {
        "type": "browser_tab",
        "id": raw.get("id", index),
        "label": label,
        "browser_id": browser_id,
        "tab_id": tab_id or page_id,
        "page_id": page_id or tab_id,
        "window_id": page_id or tab_id,
        "url": url,
        "title": title,
        "runtime": runtime,
        "active": active,
        "is_active": active,
        "display_path": display_path,
        "scroll": scroll,
        "viewport": viewport,
        "selected_element": selected_element,
        "updated_at": updated_at,
    }
    has_page_target = bool(page_id or tab_id)
    has_url_target = bool(url)
    if has_page_target:
        guidance = (
            "This is a reference to the user's shared Browser panel tab. The Browser panel and "
            "Browser tools operate on the same Browser workspace for this conversation. Treat "
            "the page_id/window_id above as the target tab for Browser tools in this turn. Do "
            "not open a separate copy of this page just because it was mentioned; inspect or "
            "act on the referenced tab when browser work is needed."
        )
    elif has_url_target:
        guidance = (
            "This is a reference to the user's shared Browser window. If the shared Browser "
            "workspace is not already on the target URL, use BrowserOpen with the URL above "
            "inside this conversation's shared Browser workspace before browser work is needed. "
            "Do not treat this Browser mention as plain message text."
        )
    else:
        guidance = (
            "This is a reference to the user's shared Browser window. Browser tools operate "
            "on the same Browser workspace for this conversation. Inspect or act on the "
            "active Browser workspace when browser work is needed, and do not treat this "
            "Browser mention as plain message text."
        )
    reminder = _wrap_attached_context(
        "browser_tab",
        [
            f"Label: {label}",
            f"Browser ID: {browser_id or '(unknown)'}",
            f"Page ID: {page_id or tab_id or '(new or active Browser window)'}",
            f"URL: {url or '(unknown)'}",
            f"Title: {title or '(untitled)'}",
            f"Runtime: {runtime or '(unknown)'}",
            f"Active tab: {'yes' if active else 'no'}",
            f"Scroll: {scroll or {}}",
            f"Viewport: {viewport or {}}",
            f"Selected element: {selected_element or {}}",
            "",
            guidance,
        ],
    )
    return reminder, metadata
