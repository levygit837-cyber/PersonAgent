"""Shared browser-workspace infrastructure helpers.

Functions that read/write conversation metadata (browser_workspace,
browser_cooperation) and are used by ``browser_interaction``,
``workspace_data``, and ``cooperation`` route modules.

Late-binding via ``import sessions as _sessions`` keeps test
monkeypatch compatibility.
"""

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

import personagent.adapters.api.routes.sessions as _sessions
from personagent.application.services.browser_cooperation import (
    BrowserCooperationService,
)
from personagent.application.services.browser_workspace import BrowserWorkspaceService


def _browser_workspace_service(session: AsyncSession) -> BrowserWorkspaceService | None:
    if isinstance(session, AsyncSession):
        return BrowserWorkspaceService(session)
    return None


def _browser_cooperation_service(session: AsyncSession) -> BrowserCooperationService | None:
    if isinstance(session, AsyncSession):
        return BrowserCooperationService(session)
    return None


def _browser_workspace(conversation) -> dict[str, Any]:
    metadata = conversation.metadata
    workspace = metadata.get("browser_workspace")
    if not isinstance(workspace, dict):
        workspace = {}
        metadata["browser_workspace"] = workspace
    workspace.setdefault("annotations", [])
    workspace.setdefault("timeline_events", [])
    workspace.setdefault("last_element_map", [])
    return workspace


def _workspace_payload(conversation, browser_id: str) -> dict[str, Any]:
    workspace = _browser_workspace(conversation)
    annotations = [
        item
        for item in _sessions._coerce_list(workspace.get("annotations"))
        if str(item.get("browser_id") or "") == browser_id
    ]
    timeline_events = [
        item
        for item in _sessions._coerce_list(workspace.get("timeline_events"))
        if str(item.get("browser_id") or "") == browser_id
    ]
    return {
        "annotations": annotations[-100:],
        "timeline_events": timeline_events[-120:],
        "cooperation": _sessions._coerce_dict(
            _sessions._coerce_dict(conversation.metadata.get("browser_cooperation")).get(browser_id)
        ),
        "tabs": _sessions._coerce_list(workspace.get("tabs")),
        "active_tab_id": str(workspace.get("active_tab_id") or browser_id),
        "workspace_state": {
            "active_browser_id": str(workspace.get("active_browser_id") or ""),
            "active_tab_id": str(workspace.get("active_tab_id") or browser_id),
            "current_url": str(workspace.get("current_url") or ""),
            "current_title": str(workspace.get("current_title") or ""),
            "last_element_map": _sessions._coerce_list(workspace.get("last_element_map"))[:220],
            "cooperation": _sessions._coerce_dict(
                _sessions._coerce_dict(conversation.metadata.get("browser_cooperation")).get(browser_id)
            ),
        },
    }


def _compact_element_map(raw_map: Any) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in _sessions._coerce_list(raw_map):
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        compact.append(
            {
                "node_id": node_id,
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": str(item.get("text") or "")[:240],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": _sessions._coerce_list(item.get("selector_chain")),
                "shadow_path": _sessions._coerce_list(item.get("shadow_path")),
                "stable_key": str(item.get("stable_key") or ""),
                "interactable": bool(item.get("interactable")),
            }
        )
        if len(compact) >= 220:
            break
    return compact


def _append_timeline_event(
    conversation,
    *,
    browser_id: str,
    event_type: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = _browser_workspace(conversation)
    event = {
        "id": f"evt_{uuid4().hex[:12]}",
        "browser_id": browser_id,
        "source": _sessions._safe_event_source(source),
        "event_type": event_type,
        "label": label,
        "payload": payload or {},
        "created_at": _sessions._now_iso(),
    }
    events = _sessions._coerce_list(workspace.get("timeline_events"))
    events.append(event)
    workspace["timeline_events"] = events[-120:]
    return event


async def _record_timeline_event(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    event_type: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = _browser_workspace_service(session)
    if service is not None:
        return await service.append_timeline_event(
            conversation,
            browser_id=browser_id,
            event_type=event_type,
            source=source,
            label=label,
            payload=payload,
        )
    return _append_timeline_event(
        conversation,
        browser_id=browser_id,
        event_type=event_type,
        source=source,
        label=label,
        payload=payload,
    )


async def _record_canonical_browser_event(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    kind: str,
    source: str,
    label: str,
    payload: dict[str, Any] | None = None,
    tab_id: str | None = None,
    page_id: str | None = None,
    url: str | None = None,
) -> None:
    service = _browser_cooperation_service(session)
    if service is None:
        return
    result = await service.record_canonical_event(
        conversation,
        browser_id=browser_id,
        kind=kind,
        source=source,
        label=label,
        payload=payload,
        tab_id=tab_id,
        page_id=page_id,
        url=url,
    )
    if result is not None:
        await _sessions._save_conversation(conversation, session)


async def _ingest_view_cooperation_events(
    session: AsyncSession,
    conversation,
    *,
    browser_id: str,
    view: dict[str, Any],
) -> None:
    events = _sessions._coerce_list(view.get("cooperation_events"))
    if not events:
        snapshot = _sessions._coerce_dict(view.get("browser_snapshot"))
        events = _sessions._coerce_list(snapshot.get("cooperation_events"))
    if not events:
        return
    service = _browser_cooperation_service(session)
    if service is None:
        return
    result = await service.ingest_events(
        conversation,
        browser_id=browser_id,
        events=[event for event in events if isinstance(event, dict)],
    )
    cooperation = _sessions._coerce_dict(_sessions._coerce_dict(result.get("state_patch")).get("cooperation"))
    if cooperation:
        view["cooperation"] = cooperation
        if isinstance(view.get("workspace_state"), dict):
            view["workspace_state"]["cooperation"] = cooperation
        if isinstance(view.get("browser_snapshot"), dict):
            view["browser_snapshot"]["cooperation"] = cooperation


async def _persist_browser_workspace_view(
    conversation,
    session: AsyncSession,
    browser_id: str,
    view: dict[str, Any],
) -> dict[str, Any]:
    service = _browser_workspace_service(session)
    if service is not None:
        persisted = await service.persist_view(conversation, browser_id=browser_id, view=view)
        await _ingest_view_cooperation_events(session, conversation, browser_id=browser_id, view=persisted)
        await _sessions._save_conversation(conversation, session)
        return persisted
    workspace = _browser_workspace(conversation)
    workspace["active_browser_id"] = browser_id
    workspace["active_tab_id"] = view.get("active_tab_id") or browser_id
    if view.get("url") and view.get("url") != "about:blank":
        workspace["current_url"] = view.get("url")
        workspace["current_title"] = view.get("title") or ""
    workspace["last_element_map"] = _compact_element_map(view.get("element_map"))
    tabs = _sessions._coerce_list(view.get("tabs"))[:50]
    if not tabs:
        active_tab_id = str(workspace.get("active_tab_id") or browser_id)
        current_url = str(view.get("url") or workspace.get("current_url") or "")
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": current_url,
                "title": str(view.get("title") or workspace.get("current_title") or ""),
                "runtime": str(view.get("runtime") or "lightpanda"),
                "active": True,
                "is_active": True,
                "history": [current_url] if current_url and current_url != "about:blank" else [],
            }
        ]
    workspace["tabs"] = tabs
    view.update(_workspace_payload(conversation, browser_id))
    snapshot = view.get("browser_snapshot")
    if isinstance(snapshot, dict):
        snapshot["annotations"] = view["annotations"]
        snapshot["timeline_events"] = view["timeline_events"]
        snapshot["element_map"] = view.get("element_map") or []
        snapshot["cooperation"] = view.get("cooperation") or {}
    await _ingest_view_cooperation_events(session, conversation, browser_id=browser_id, view=view)
    await _sessions._save_conversation(conversation, session)
    return view
