"""ORM-to-dict serializers and metadata mirroring for browser workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from personagent.application.services.browser_workspace.helpers import (
    _coerce_dict,
    _coerce_list,
    _iso,
    _safe_event_source,
)
from personagent.infrastructure.persistence.models import (
    BrowserAnnotationORM,
    BrowserTabORM,
    BrowserTimelineEventORM,
)


def _tab_to_dict(tab: BrowserTabORM) -> dict[str, Any]:
    return {
        "tab_id": tab.tab_id,
        "id": tab.tab_id,
        "url": tab.url or "",
        "title": tab.title or "",
        "runtime": tab.runtime or "lightpanda",
        "active": bool(tab.is_active),
        "is_active": bool(tab.is_active),
        "history": _coerce_list(tab.history),
        "state": _coerce_dict(tab.state),
        "created_at": _iso(tab.created_at),
        "updated_at": _iso(tab.updated_at),
    }


def _mirror_compact_browser_workspace(
    conversation,
    *,
    browser_id: str,
    payload: dict[str, Any],
) -> None:
    metadata = _coerce_dict(getattr(conversation, "metadata", {}))
    if getattr(conversation, "metadata", None) is not metadata:
        conversation.metadata = metadata
    workspace_state = _coerce_dict(payload.get("workspace_state"))
    compact = {
        "active_browser_id": str(workspace_state.get("active_browser_id") or browser_id),
        "active_tab_id": str(payload.get("active_tab_id") or workspace_state.get("active_tab_id") or browser_id),
        "current_url": str(workspace_state.get("current_url") or ""),
        "current_title": str(workspace_state.get("current_title") or ""),
        "last_element_map": _coerce_list(workspace_state.get("last_element_map"))[:220],
        "tabs": _coerce_list(payload.get("tabs"))[:50],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    metadata["browser_workspace"] = compact


def _annotation_to_dict(annotation: BrowserAnnotationORM, browser_id: str) -> dict[str, Any]:
    return {
        "id": annotation.annotation_id,
        "browser_id": browser_id,
        "tab_id": annotation.tab_id or "",
        "node_id": annotation.node_id,
        "body": annotation.body,
        "quote": annotation.quote or "",
        "url": annotation.url or "",
        "title": annotation.title or "",
        "selector": annotation.selector or "",
        "frame_id": annotation.frame_id or "main",
        "selector_chain": _coerce_list(annotation.selector_chain),
        "shadow_path": _coerce_list(annotation.shadow_path),
        "metadata": _coerce_dict(annotation.metadata_),
        "created_at": _iso(annotation.created_at),
        "updated_at": _iso(annotation.updated_at),
    }


def _timeline_event_to_dict(event: BrowserTimelineEventORM, browser_id: str) -> dict[str, Any]:
    return {
        "id": event.event_id,
        "browser_id": browser_id,
        "tab_id": event.tab_id or "",
        "source": _safe_event_source(event.source),
        "event_type": event.event_type,
        "label": event.label,
        "payload": _coerce_dict(event.payload),
        "sequence": int(event.sequence or 0),
        "automation_run_id": event.automation_run_id or "",
        "created_at": _iso(event.created_at),
    }
