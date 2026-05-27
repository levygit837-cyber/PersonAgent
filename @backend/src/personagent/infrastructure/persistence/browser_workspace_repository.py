"""Postgres implementation of BrowserWorkspaceRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.domain.browser_workspace.repositories import BrowserWorkspaceRepository
from personagent.infrastructure.persistence.models import (
    BrowserAnnotationORM,
    BrowserTabORM,
    BrowserTimelineEventORM,
    BrowserWorkspaceORM,
)

# ---------------------------------------------------------------------------
# Serializers (moved from application layer)
# ---------------------------------------------------------------------------


def _tab_to_dict(tab: BrowserTabORM) -> dict[str, Any]:
    return {
        "tab_id": tab.tab_id,
        "id": tab.tab_id,
        "url": tab.url or "",
        "title": tab.title or "",
        "runtime": tab.runtime or "lightpanda",
        "active": bool(tab.is_active),
        "is_active": bool(tab.is_active),
        "history": tab.history if isinstance(tab.history, list) else [],
        "state": tab.state if isinstance(tab.state, dict) else {},
        "created_at": _iso(tab.created_at),
        "updated_at": _iso(tab.updated_at),
    }


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
        "selector_chain": annotation.selector_chain if isinstance(annotation.selector_chain, list) else [],
        "shadow_path": annotation.shadow_path if isinstance(annotation.shadow_path, list) else [],
        "metadata": annotation.metadata_ if isinstance(annotation.metadata_, dict) else {},
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
        "payload": event.payload if isinstance(event.payload, dict) else {},
        "sequence": int(event.sequence or 0),
        "automation_run_id": event.automation_run_id or "",
        "created_at": _iso(event.created_at),
    }


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _safe_event_source(value: str) -> str:
    return value if value in {"user", "agent", "system"} else "user"


# ---------------------------------------------------------------------------
# Repository implementation
# ---------------------------------------------------------------------------


class PostgresBrowserWorkspaceRepository(BrowserWorkspaceRepository):
    """SQLAlchemy-backed browser workspace repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_workspace(
        self,
        conversation_id: str,
        browser_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        result = await self._session.execute(
            select(BrowserWorkspaceORM).where(
                BrowserWorkspaceORM.conversation_id == conversation_id,
                BrowserWorkspaceORM.browser_id == browser_id,
            )
        )
        workspace = result.scalar_one_or_none()
        if workspace is not None:
            return _workspace_to_dict(workspace)
        workspace = BrowserWorkspaceORM(
            conversation_id=conversation_id,
            browser_id=browser_id,
            workspace_id=workspace_id,
            active_runtime="lightpanda",
            active_tab_id=browser_id,
            state={},
        )
        self._session.add(workspace)
        await self._session.flush()
        return _workspace_to_dict(workspace)

    async def update_workspace_state(self, workspace_id: str, state: dict[str, Any]) -> None:
        result = await self._session.execute(
            select(BrowserWorkspaceORM).where(BrowserWorkspaceORM.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if workspace is not None:
            workspace.state = state

    async def set_workspace_fields(
        self,
        workspace_id: str,
        *,
        active_runtime: str | None = None,
        active_tab_id: str | None = None,
        current_url: str | None = None,
        current_title: str | None = None,
    ) -> None:
        result = await self._session.execute(
            select(BrowserWorkspaceORM).where(BrowserWorkspaceORM.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            return
        if active_runtime is not None:
            workspace.active_runtime = active_runtime
        if active_tab_id is not None:
            workspace.active_tab_id = active_tab_id
        if current_url is not None:
            workspace.current_url = current_url
        if current_title is not None:
            workspace.current_title = current_title

    async def upsert_tabs(
        self,
        workspace_id: str,
        tabs: list[dict[str, Any]],
        *,
        active_tab_id: str,
        runtime: str,
    ) -> None:
        result = await self._session.execute(
            select(BrowserTabORM).where(BrowserTabORM.browser_workspace_id == workspace_id)
        )
        existing = {tab.tab_id: tab for tab in result.scalars().all()}
        for raw_tab in tabs[:50]:
            if not isinstance(raw_tab, dict):
                continue
            tab_id = str(raw_tab.get("tab_id") or raw_tab.get("id") or active_tab_id)
            if not tab_id:
                continue
            tab = existing.get(tab_id)
            if tab is None:
                tab = BrowserTabORM(browser_workspace_id=workspace_id, tab_id=tab_id)
                self._session.add(tab)
            tab.url = str(raw_tab.get("url") or "")
            tab.title = str(raw_tab.get("title") or "")
            tab.runtime = str(raw_tab.get("runtime") or runtime)
            tab.is_active = bool(
                raw_tab.get("active") or raw_tab.get("is_active") or tab_id == active_tab_id
            )
            tab.history = raw_tab.get("history") if isinstance(raw_tab.get("history"), list) else []
            tab.state = raw_tab.get("state") if isinstance(raw_tab.get("state"), dict) else {}

    async def get_tabs(self, workspace_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserTabORM)
            .where(BrowserTabORM.browser_workspace_id == workspace_id)
            .order_by(BrowserTabORM.is_active.desc(), BrowserTabORM.updated_at.desc())
            .limit(50)
        )
        return [_tab_to_dict(tab) for tab in result.scalars().all()]

    async def get_annotations(self, workspace_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserAnnotationORM)
            .where(BrowserAnnotationORM.browser_workspace_id == workspace_id)
            .order_by(BrowserAnnotationORM.created_at.desc())
            .limit(100)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return [_annotation_to_dict(row, "") for row in rows]

    async def get_timeline_events(self, workspace_id: str) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserTimelineEventORM)
            .where(BrowserTimelineEventORM.browser_workspace_id == workspace_id)
            .order_by(BrowserTimelineEventORM.sequence.desc(), BrowserTimelineEventORM.created_at.desc())
            .limit(160)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return [_timeline_event_to_dict(row, "") for row in rows]

    async def append_timeline_event(
        self,
        workspace_id: str,
        browser_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        orm = BrowserTimelineEventORM(
            event_id=event["event_id"],
            browser_workspace_id=workspace_id,
            tab_id=event.get("tab_id"),
            source=event["source"],
            event_type=event["event_type"],
            label=event["label"],
            payload=event.get("payload") or {},
            sequence=event["sequence"],
            automation_run_id=event.get("automation_run_id"),
        )
        self._session.add(orm)
        await self._session.flush()
        return _timeline_event_to_dict(orm, browser_id)

    async def create_annotation(
        self,
        workspace_id: str,
        browser_id: str,
        annotation: dict[str, Any],
    ) -> dict[str, Any]:
        orm = BrowserAnnotationORM(
            annotation_id=annotation["annotation_id"],
            browser_workspace_id=workspace_id,
            tab_id=annotation.get("tab_id"),
            node_id=annotation["node_id"],
            url=annotation.get("url", "").strip(),
            title=annotation.get("title", "").strip(),
            selector=annotation.get("selector", "").strip(),
            frame_id=annotation.get("frame_id", "main").strip(),
            selector_chain=annotation.get("selector_chain") or [],
            shadow_path=annotation.get("shadow_path") or [],
            body=annotation["body"].strip(),
            quote=annotation.get("quote", "").strip(),
            metadata_=annotation.get("metadata") or {},
        )
        self._session.add(orm)
        await self._session.flush()
        return _annotation_to_dict(orm, browser_id)

    async def delete_annotation(self, workspace_id: str, annotation_id: str) -> None:
        await self._session.execute(
            delete(BrowserAnnotationORM).where(
                BrowserAnnotationORM.browser_workspace_id == workspace_id,
                BrowserAnnotationORM.annotation_id == annotation_id,
            )
        )

    async def clear_timeline(self, workspace_id: str) -> None:
        await self._session.execute(
            delete(BrowserTimelineEventORM).where(
                BrowserTimelineEventORM.browser_workspace_id == workspace_id
            )
        )

    async def next_sequence(self, workspace_id: str) -> int:
        result = await self._session.execute(
            select(func.max(BrowserTimelineEventORM.sequence)).where(
                BrowserTimelineEventORM.browser_workspace_id == workspace_id
            )
        )
        return int(result.scalar() or 0) + 1

    async def trim_timeline(self, workspace_id: str, keep: int = 500) -> None:
        result = await self._session.execute(
            select(BrowserTimelineEventORM.id)
            .where(BrowserTimelineEventORM.browser_workspace_id == workspace_id)
            .order_by(BrowserTimelineEventORM.sequence.desc(), BrowserTimelineEventORM.created_at.desc())
            .offset(keep)
        )
        stale_ids = list(result.scalars().all())
        if not stale_ids:
            return
        await self._session.execute(
            delete(BrowserTimelineEventORM).where(BrowserTimelineEventORM.id.in_(stale_ids))
        )

    async def migrate_legacy_annotations(
        self,
        workspace_id: str,
        browser_id: str,
        annotations: list[dict[str, Any]],
    ) -> None:
        if not annotations:
            return
        existing_result = await self._session.execute(
            select(BrowserAnnotationORM.annotation_id).where(
                BrowserAnnotationORM.browser_workspace_id == workspace_id
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
                    browser_workspace_id=workspace_id,
                    tab_id=str(item.get("tab_id") or browser_id),
                    node_id=str(item.get("node_id") or ""),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    selector=str(item.get("selector") or ""),
                    frame_id=str(item.get("frame_id") or "main"),
                    selector_chain=item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [],
                    shadow_path=item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else [],
                    body=str(item.get("body") or ""),
                    quote=str(item.get("quote") or ""),
                    metadata_={"legacy_metadata": True},
                )
            )

    async def migrate_legacy_events(
        self,
        workspace_id: str,
        browser_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        if not events:
            return
        existing_result = await self._session.execute(
            select(BrowserTimelineEventORM.event_id).where(
                BrowserTimelineEventORM.browser_workspace_id == workspace_id
            )
        )
        existing_ids = {str(item) for item in existing_result.scalars().all()}
        sequence = await self.next_sequence(workspace_id)
        for item in events:
            event_id = str(item.get("id") or f"evt_{uuid4().hex[:12]}")
            if event_id in existing_ids:
                continue
            self._session.add(
                BrowserTimelineEventORM(
                    event_id=event_id,
                    browser_workspace_id=workspace_id,
                    tab_id=str(item.get("tab_id") or browser_id),
                    source=_safe_event_source(str(item.get("source") or "system")),
                    event_type=str(item.get("event_type") or "event"),
                    label=str(item.get("label") or item.get("event_type") or "Browser event"),
                    payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
                    sequence=sequence,
                )
            )
            sequence += 1

    async def commit(self) -> None:
        await self._session.commit()


def _workspace_to_dict(workspace: BrowserWorkspaceORM) -> dict[str, Any]:
    return {
        "id": str(workspace.id),
        "conversation_id": str(workspace.conversation_id),
        "browser_id": workspace.browser_id,
        "workspace_id": workspace.workspace_id or "",
        "active_runtime": workspace.active_runtime or "lightpanda",
        "active_tab_id": workspace.active_tab_id or "",
        "current_url": workspace.current_url or "",
        "current_title": workspace.current_title or "",
        "state": workspace.state if isinstance(workspace.state, dict) else {},
        "created_at": _iso(workspace.created_at),
        "updated_at": _iso(workspace.updated_at),
    }
