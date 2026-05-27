"""Persistent Browser Workspace service.

The service is the V2 persistence boundary for the session-panel browser.  It
keeps snapshots lightweight: runtime state, tabs, annotations and timeline live
in their own tables while large HTML snapshots stay transient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from personagent.application.services.browser_workspace.helpers import (
    _coerce_dict,
    _coerce_list,
    _compact_element_map,
    _conversation_uuid,
    _runtime_from_user_agent,
    _safe_event_source,
)
from personagent.domain.browser_workspace.repositories import BrowserWorkspaceRepository


class BrowserWorkspaceService:
    """Persist and hydrate Browser Workspace state."""

    def __init__(self, repository: BrowserWorkspaceRepository) -> None:
        self._repository = repository

    async def persist_view(
        self,
        conversation,
        *,
        browser_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist transient view metadata and enrich it with DB-backed workspace data."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._migrate_legacy_metadata(conversation, workspace)
        runtime = str(view.get("runtime") or _runtime_from_user_agent(view.get("user_agent")) or "lightpanda")
        active_tab_id = str(view.get("active_tab_id") or view.get("tab_id") or browser_id)
        url = str(view.get("url") or "")
        title = str(view.get("title") or "")

        await self._repository.set_workspace_fields(
            workspace["id"],
            active_runtime=runtime,
            active_tab_id=active_tab_id,
            current_url=url if url and url != "about:blank" else None,
            current_title=title if url and url != "about:blank" else None,
        )

        state = _coerce_dict(workspace.get("state"))
        state.update(
            {
                "last_element_map": _compact_element_map(view.get("element_map")),
                "render_mode": str(view.get("render_mode") or ""),
                "css_fidelity": str(view.get("css_fidelity") or ""),
                "fallback_reason": str(view.get("fallback_reason") or ""),
                "render_cache_key": str(view.get("render_cache_key") or ""),
                "render_cache_status": str(view.get("render_cache_status") or ""),
                "style_ready": bool(view.get("style_ready", False)),
                "stylesheet_count": int(view.get("stylesheet_count") or 0),
                "stylesheet_loaded_count": int(view.get("stylesheet_loaded_count") or 0),
                "stylesheet_cached_count": int(view.get("stylesheet_cached_count") or 0),
            }
        )
        cooperation = _coerce_dict(state.get("cooperation"))
        if cooperation:
            if url and url != "about:blank":
                cooperation["url"] = url
                cooperation["title"] = title
                cooperation["updated_at"] = datetime.now(UTC).isoformat()
            state["cooperation"] = cooperation
        await self._repository.update_workspace_state(workspace["id"], state)

        raw_tabs = _coerce_list(view.get("tabs"))
        if not raw_tabs:
            raw_tabs = [
                {
                    "tab_id": active_tab_id,
                    "url": view.get("url") or "",
                    "title": view.get("title") or "",
                    "runtime": runtime,
                    "active": True,
                    "history": [view.get("url")] if view.get("url") else [],
                }
            ]
        await self._repository.upsert_tabs(
            workspace["id"],
            raw_tabs,
            active_tab_id=active_tab_id,
            runtime=runtime,
        )
        await self._repository.commit()

        payload = await self.payload(conversation, browser_id)
        _mirror_compact_browser_workspace(conversation, browser_id=browser_id, payload=payload)
        view.update(payload)
        snapshot = view.get("browser_snapshot")
        if isinstance(snapshot, dict):
            snapshot.update(
                {
                    "annotations": view["annotations"],
                    "timeline_events": view["timeline_events"],
                    "element_map": view.get("element_map") or [],
                    "tabs": view.get("tabs") or payload.get("tabs") or [],
                    "active_tab_id": view.get("active_tab_id") or payload.get("active_tab_id") or active_tab_id,
                    "runtime": runtime,
                    "cooperation": view.get("cooperation") or payload.get("cooperation") or {},
                }
            )
        return view

    async def payload(self, conversation, browser_id: str) -> dict[str, Any]:
        """Return Browser Workspace state in the V1-compatible API shape."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._migrate_legacy_metadata(conversation, workspace)
        tabs = await self._repository.get_tabs(workspace["id"])
        active_tab_id = str(workspace.get("active_tab_id") or (tabs[0]["tab_id"] if tabs else browser_id))
        annotations = await self._repository.get_annotations(workspace["id"])
        timeline_events = await self._repository.get_timeline_events(workspace["id"])
        state = _coerce_dict(workspace.get("state"))
        return {
            "annotations": annotations,
            "timeline_events": timeline_events,
            "cooperation": _coerce_dict(state.get("cooperation")),
            "workspace_state": {
                "active_browser_id": browser_id,
                "current_url": str(workspace.get("current_url") or ""),
                "current_title": str(workspace.get("current_title") or ""),
                "last_element_map": _coerce_list(state.get("last_element_map"))[:220],
                "runtime": str(workspace.get("active_runtime") or "lightpanda"),
                "active_tab_id": active_tab_id,
                "cooperation": _coerce_dict(state.get("cooperation")),
                "render_cache_key": str(state.get("render_cache_key") or ""),
                "render_cache_status": str(state.get("render_cache_status") or ""),
                "style_ready": bool(state.get("style_ready", False)),
                "stylesheet_count": int(state.get("stylesheet_count") or 0),
                "stylesheet_loaded_count": int(state.get("stylesheet_loaded_count") or 0),
                "stylesheet_cached_count": int(state.get("stylesheet_cached_count") or 0),
            },
            "tabs": tabs,
            "active_tab_id": active_tab_id,
        }

    async def append_timeline_event(
        self,
        conversation,
        *,
        browser_id: str,
        event_type: str,
        source: str,
        label: str,
        payload: dict[str, Any] | None = None,
        tab_id: str | None = None,
        automation_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one reproducible Browser Workspace event."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._migrate_legacy_metadata(conversation, workspace)
        sequence = await self._repository.next_sequence(workspace["id"])
        event = await self._repository.append_timeline_event(
            workspace["id"],
            browser_id,
            {
                "event_id": f"evt_{uuid4().hex[:12]}",
                "tab_id": tab_id or workspace.get("active_tab_id") or browser_id,
                "source": _safe_event_source(source),
                "event_type": str(event_type or "event"),
                "label": str(label or event_type or "Browser event"),
                "payload": payload or {},
                "sequence": sequence,
                "automation_run_id": automation_run_id,
            },
        )
        await self._repository.commit()
        await self._repository.trim_timeline(workspace["id"])
        await self._repository.commit()
        return event

    async def create_annotation(
        self,
        conversation,
        *,
        browser_id: str,
        node_id: str,
        body: str,
        quote: str | None = None,
        url: str | None = None,
        title: str | None = None,
        selector: str | None = None,
        frame_id: str | None = None,
        selector_chain: list[str] | None = None,
        shadow_path: list[str] | None = None,
        tab_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a persistent browser annotation and record it in the timeline."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._migrate_legacy_metadata(conversation, workspace)
        annotation = await self._repository.create_annotation(
            workspace["id"],
            browser_id,
            {
                "annotation_id": f"ann_{uuid4().hex[:12]}",
                "tab_id": tab_id or workspace.get("active_tab_id") or browser_id,
                "node_id": node_id,
                "url": (url or "").strip(),
                "title": (title or "").strip(),
                "selector": (selector or "").strip(),
                "frame_id": (frame_id or "main").strip(),
                "selector_chain": selector_chain or [],
                "shadow_path": shadow_path or [],
                "body": body.strip(),
                "quote": (quote or "").strip(),
                "metadata": metadata or {},
            },
        )
        await self._repository.commit()
        await self.append_timeline_event(
            conversation,
            browser_id=browser_id,
            event_type="annotation",
            source="user",
            label="Added annotation",
            payload={"node_id": node_id, "annotation_id": annotation["id"]},
            tab_id=annotation.get("tab_id"),
        )
        return {
            "annotation": annotation,
            **await self.payload(conversation, browser_id),
        }

    async def delete_annotation(
        self,
        conversation,
        *,
        browser_id: str,
        annotation_id: str,
    ) -> dict[str, Any]:
        """Delete an annotation by public annotation_id."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._repository.delete_annotation(workspace["id"], annotation_id)
        await self._repository.commit()
        await self.append_timeline_event(
            conversation,
            browser_id=browser_id,
            event_type="annotation_deleted",
            source="user",
            label="Deleted annotation",
            payload={"annotation_id": annotation_id},
        )
        return await self.payload(conversation, browser_id)

    async def clear_timeline(self, conversation, *, browser_id: str) -> dict[str, Any]:
        """Clear timeline events for one Browser Workspace."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        await self._repository.clear_timeline(workspace["id"])
        await self._repository.commit()
        return await self.payload(conversation, browser_id)

    async def _migrate_legacy_metadata(self, conversation, workspace: dict[str, Any]) -> None:
        state = _coerce_dict(workspace.get("state"))
        if state.get("legacy_metadata_migrated"):
            return
        legacy_workspace = _coerce_dict(
            _coerce_dict(getattr(conversation, "metadata", {})).get("browser_workspace")
        )
        annotations = [
            item
            for item in _coerce_list(legacy_workspace.get("annotations"))
            if str(item.get("browser_id") or "") == workspace.get("browser_id")
        ]
        events = [
            item
            for item in _coerce_list(legacy_workspace.get("timeline_events"))
            if str(item.get("browser_id") or "") == workspace.get("browser_id")
        ]
        await self._repository.migrate_legacy_annotations(
            workspace["id"], workspace.get("browser_id", ""), annotations
        )
        await self._repository.migrate_legacy_events(
            workspace["id"], workspace.get("browser_id", ""), events
        )
        state["legacy_metadata_migrated"] = True
        await self._repository.update_workspace_state(workspace["id"], state)
        await self._repository.commit()


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
