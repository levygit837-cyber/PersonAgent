"""Persistent Browser Workspace service.

The service is the V2 persistence boundary for the session-panel browser.  It
keeps snapshots lightweight: runtime state, tabs, annotations and timeline live
in their own tables while large HTML snapshots stay transient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.infrastructure.persistence.models import (
    BrowserAnnotationORM,
    BrowserTabORM,
    BrowserTimelineEventORM,
    BrowserWorkspaceORM,
)


class BrowserWorkspaceService:
    """Persist and hydrate Browser Workspace state for one async DB session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist_view(
        self,
        conversation,
        *,
        browser_id: str,
        view: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist transient view metadata and enrich it with DB-backed workspace data."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._migrate_legacy_metadata(conversation, workspace)
        runtime = str(view.get("runtime") or _runtime_from_user_agent(view.get("user_agent")) or "lightpanda")
        active_tab_id = str(view.get("active_tab_id") or view.get("tab_id") or browser_id)
        url = str(view.get("url") or "")
        title = str(view.get("title") or "")
        workspace.active_runtime = runtime
        workspace.active_tab_id = active_tab_id
        if url and url != "about:blank":
            workspace.current_url = url
            workspace.current_title = title
        state = _coerce_dict(workspace.state)
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
        workspace.state = state
        await self._upsert_tabs(workspace, view, active_tab_id=active_tab_id, runtime=runtime)
        await self._session.commit()
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

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._migrate_legacy_metadata(conversation, workspace)
        tabs = await self._tabs_payload(workspace)
        active_tab_id = str(workspace.active_tab_id or (tabs[0]["tab_id"] if tabs else browser_id))
        annotations = await self._annotations_payload(workspace)
        timeline_events = await self._timeline_payload(workspace)
        state = _coerce_dict(workspace.state)
        return {
            "annotations": annotations,
            "timeline_events": timeline_events,
            "cooperation": _coerce_dict(state.get("cooperation")),
            "workspace_state": {
                "active_browser_id": browser_id,
                "current_url": str(workspace.current_url or ""),
                "current_title": str(workspace.current_title or ""),
                "last_element_map": _coerce_list(state.get("last_element_map"))[:220],
                "runtime": str(workspace.active_runtime or "lightpanda"),
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

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._migrate_legacy_metadata(conversation, workspace)
        sequence = await self._next_sequence(workspace)
        event = BrowserTimelineEventORM(
            event_id=f"evt_{uuid4().hex[:12]}",
            browser_workspace_id=workspace.id,
            tab_id=tab_id or workspace.active_tab_id or browser_id,
            source=_safe_event_source(source),
            event_type=str(event_type or "event"),
            label=str(label or event_type or "Browser event"),
            payload=payload or {},
            sequence=sequence,
            automation_run_id=automation_run_id,
        )
        self._session.add(event)
        await self._session.commit()
        await self._trim_timeline(workspace)
        return _timeline_event_to_dict(event, workspace.browser_id)

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

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._migrate_legacy_metadata(conversation, workspace)
        annotation = BrowserAnnotationORM(
            annotation_id=f"ann_{uuid4().hex[:12]}",
            browser_workspace_id=workspace.id,
            tab_id=tab_id or workspace.active_tab_id or browser_id,
            node_id=node_id,
            url=(url or "").strip(),
            title=(title or "").strip(),
            selector=(selector or "").strip(),
            frame_id=(frame_id or "main").strip(),
            selector_chain=selector_chain or [],
            shadow_path=shadow_path or [],
            body=body.strip(),
            quote=(quote or "").strip(),
            metadata_=metadata or {},
        )
        self._session.add(annotation)
        await self._session.commit()
        await self.append_timeline_event(
            conversation,
            browser_id=browser_id,
            event_type="annotation",
            source="user",
            label="Added annotation",
            payload={"node_id": node_id, "annotation_id": annotation.annotation_id},
            tab_id=annotation.tab_id,
        )
        return {
            "annotation": _annotation_to_dict(annotation, workspace.browser_id),
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

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._session.execute(
            delete(BrowserAnnotationORM).where(
                BrowserAnnotationORM.browser_workspace_id == workspace.id,
                BrowserAnnotationORM.annotation_id == annotation_id,
            )
        )
        await self._session.commit()
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

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        await self._session.execute(
            delete(BrowserTimelineEventORM).where(
                BrowserTimelineEventORM.browser_workspace_id == workspace.id
            )
        )
        await self._session.commit()
        return await self.payload(conversation, browser_id)

    async def _get_or_create_workspace(self, conversation, browser_id: str) -> BrowserWorkspaceORM:
        conversation_id = _conversation_uuid(conversation)
        result = await self._session.execute(
            select(BrowserWorkspaceORM).where(
                BrowserWorkspaceORM.conversation_id == conversation_id,
                BrowserWorkspaceORM.browser_id == browser_id,
            )
        )
        workspace = result.scalar_one_or_none()
        if workspace is not None:
            return workspace
        workspace = BrowserWorkspaceORM(
            conversation_id=conversation_id,
            browser_id=browser_id,
            workspace_id=str(_coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""),
            active_runtime="lightpanda",
            active_tab_id=browser_id,
            state={},
        )
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def _upsert_tabs(
        self,
        workspace: BrowserWorkspaceORM,
        view: dict[str, Any],
        *,
        active_tab_id: str,
        runtime: str,
    ) -> None:
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
        result = await self._session.execute(
            select(BrowserTabORM).where(BrowserTabORM.browser_workspace_id == workspace.id)
        )
        existing = {tab.tab_id: tab for tab in result.scalars().all()}
        for raw_tab in raw_tabs[:50]:
            if not isinstance(raw_tab, dict):
                continue
            tab_id = str(raw_tab.get("tab_id") or raw_tab.get("id") or active_tab_id)
            if not tab_id:
                continue
            tab = existing.get(tab_id)
            if tab is None:
                tab = BrowserTabORM(browser_workspace_id=workspace.id, tab_id=tab_id)
                self._session.add(tab)
            tab.url = str(raw_tab.get("url") or "")
            tab.title = str(raw_tab.get("title") or "")
            tab.runtime = str(raw_tab.get("runtime") or runtime)
            tab.is_active = bool(raw_tab.get("active") or raw_tab.get("is_active") or tab_id == active_tab_id)
            tab.history = _coerce_list(raw_tab.get("history"))
            tab.state = _coerce_dict(raw_tab.get("state"))

    async def _tabs_payload(self, workspace: BrowserWorkspaceORM) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserTabORM)
            .where(BrowserTabORM.browser_workspace_id == workspace.id)
            .order_by(BrowserTabORM.is_active.desc(), BrowserTabORM.updated_at.desc())
            .limit(50)
        )
        return [_tab_to_dict(tab) for tab in result.scalars().all()]

    async def _annotations_payload(self, workspace: BrowserWorkspaceORM) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserAnnotationORM)
            .where(BrowserAnnotationORM.browser_workspace_id == workspace.id)
            .order_by(BrowserAnnotationORM.created_at.desc())
            .limit(100)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return [_annotation_to_dict(row, workspace.browser_id) for row in rows]

    async def _timeline_payload(self, workspace: BrowserWorkspaceORM) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserTimelineEventORM)
            .where(BrowserTimelineEventORM.browser_workspace_id == workspace.id)
            .order_by(BrowserTimelineEventORM.sequence.desc(), BrowserTimelineEventORM.created_at.desc())
            .limit(160)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return [_timeline_event_to_dict(row, workspace.browser_id) for row in rows]

    async def _next_sequence(self, workspace: BrowserWorkspaceORM) -> int:
        result = await self._session.execute(
            select(func.max(BrowserTimelineEventORM.sequence)).where(
                BrowserTimelineEventORM.browser_workspace_id == workspace.id
            )
        )
        return int(result.scalar() or 0) + 1

    async def _trim_timeline(self, workspace: BrowserWorkspaceORM, keep: int = 500) -> None:
        result = await self._session.execute(
            select(BrowserTimelineEventORM.id)
            .where(BrowserTimelineEventORM.browser_workspace_id == workspace.id)
            .order_by(BrowserTimelineEventORM.sequence.desc(), BrowserTimelineEventORM.created_at.desc())
            .offset(keep)
        )
        stale_ids = list(result.scalars().all())
        if not stale_ids:
            return
        await self._session.execute(
            delete(BrowserTimelineEventORM).where(BrowserTimelineEventORM.id.in_(stale_ids))
        )
        await self._session.commit()

    async def _migrate_legacy_metadata(self, conversation, workspace: BrowserWorkspaceORM) -> None:
        state = _coerce_dict(workspace.state)
        if state.get("legacy_metadata_migrated"):
            return
        legacy_workspace = _coerce_dict(_coerce_dict(getattr(conversation, "metadata", {})).get("browser_workspace"))
        annotations = [
            item
            for item in _coerce_list(legacy_workspace.get("annotations"))
            if str(item.get("browser_id") or "") == workspace.browser_id
        ]
        events = [
            item
            for item in _coerce_list(legacy_workspace.get("timeline_events"))
            if str(item.get("browser_id") or "") == workspace.browser_id
        ]
        if annotations:
            existing_result = await self._session.execute(
                select(BrowserAnnotationORM.annotation_id).where(
                    BrowserAnnotationORM.browser_workspace_id == workspace.id
                )
            )
            existing_ids = {str(item) for item in existing_result.scalars().all()}
            for item in annotations:
                annotation_id = str(item.get("id") or f"ann_{uuid4().hex[:12]}")
                if annotation_id in existing_ids:
                    continue
                self._session.add(
                    BrowserAnnotationORM(
                        annotation_id=annotation_id,
                        browser_workspace_id=workspace.id,
                        tab_id=str(item.get("tab_id") or workspace.active_tab_id or workspace.browser_id),
                        node_id=str(item.get("node_id") or ""),
                        url=str(item.get("url") or ""),
                        title=str(item.get("title") or ""),
                        selector=str(item.get("selector") or ""),
                        frame_id=str(item.get("frame_id") or "main"),
                        selector_chain=_coerce_list(item.get("selector_chain")),
                        shadow_path=_coerce_list(item.get("shadow_path")),
                        body=str(item.get("body") or ""),
                        quote=str(item.get("quote") or ""),
                        metadata_={"legacy_metadata": True},
                    )
                )
        if events:
            existing_result = await self._session.execute(
                select(BrowserTimelineEventORM.event_id).where(
                    BrowserTimelineEventORM.browser_workspace_id == workspace.id
                )
            )
            existing_ids = {str(item) for item in existing_result.scalars().all()}
            sequence = await self._next_sequence(workspace)
            for item in events:
                event_id = str(item.get("id") or f"evt_{uuid4().hex[:12]}")
                if event_id in existing_ids:
                    continue
                self._session.add(
                    BrowserTimelineEventORM(
                        event_id=event_id,
                        browser_workspace_id=workspace.id,
                        tab_id=str(item.get("tab_id") or workspace.active_tab_id or workspace.browser_id),
                        source=_safe_event_source(str(item.get("source") or "system")),
                        event_type=str(item.get("event_type") or "event"),
                        label=str(item.get("label") or item.get("event_type") or "Browser event"),
                        payload=_coerce_dict(item.get("payload")),
                        sequence=sequence,
                    )
                )
                sequence += 1
        state["legacy_metadata_migrated"] = True
        workspace.state = state
        await self._session.commit()


def _conversation_uuid(conversation) -> UUID:
    value = getattr(conversation, "id", None)
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _runtime_from_user_agent(user_agent: Any) -> str:
    agent = str(user_agent or "").lower()
    if agent.startswith("lightpanda/"):
        return "lightpanda"
    if agent:
        return "chrome_cdp"
    return ""


def _compact_element_map(raw_map: Any) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in _coerce_list(raw_map):
        if not isinstance(item, dict):
            continue
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
                "selector_chain": _coerce_list(item.get("selector_chain")),
                "shadow_path": _coerce_list(item.get("shadow_path")),
                "stable_key": str(item.get("stable_key") or ""),
                "interactable": bool(item.get("interactable")),
            }
        )
        if len(compact) >= 220:
            break
    return compact


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_event_source(value: str) -> str:
    return value if value in {"user", "agent", "system"} else "user"


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return datetime.now(UTC).isoformat()


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
