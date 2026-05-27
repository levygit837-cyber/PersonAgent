"""Postgres implementation of BrowserCooperationRepository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.browser_cooperation.ports import (
    BrowserCooperationRepository,
)
from personagent.infrastructure.persistence.models import (
    BrowserCooperationEventORM,
    BrowserWorkspaceORM,
)


def _orm_event_to_dict(event: BrowserCooperationEventORM) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "conversation_id": str(event.conversation_id),
        "browser_id": event.browser_id,
        "tab_id": event.tab_id,
        "page_id": event.page_id,
        "source": event.source,
        "channel": getattr(event, "channel", "event"),
        "trace_role": getattr(event, "trace_role", event.source),
        "visibility": getattr(event, "visibility", "raw"),
        "raw_kind": getattr(event, "raw_kind", None),
        "kind": event.kind,
        "timestamp": event.occurred_at.isoformat() if event.occurred_at else None,
        "url": event.url or "",
        "target": event.target if isinstance(event.target, dict) else {},
        "payload": event.payload if isinstance(event.payload, dict) else {},
        "coordinates": getattr(event, "coordinates", {}) if isinstance(getattr(event, "coordinates", {}), dict) else {},
        "duration_ms": getattr(event, "duration_ms", None),
        "trace_effect": getattr(event, "trace_effect", None),
        "correlation_id": getattr(event, "correlation_id", None),
        "importance": event.importance,
        "semantic_label": event.semantic_label or "",
    }


class PostgresBrowserCooperationRepository(BrowserCooperationRepository):
    """SQLAlchemy-backed browser cooperation repository."""

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

    async def next_sequence(self, workspace_id: str) -> int:
        result = await self._session.execute(
            select(func.max(BrowserCooperationEventORM.sequence)).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace_id
            )
        )
        value = result.scalar_one_or_none()
        return int(value or 0) + 1

    async def existing_event_ids(self, workspace_id: str, event_ids: list[str]) -> set[str]:
        if not event_ids:
            return set()
        result = await self._session.execute(
            select(BrowserCooperationEventORM.event_id).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace_id,
                BrowserCooperationEventORM.event_id.in_(event_ids),
            )
        )
        return {str(item) for item in result.scalars().all()}

    async def persist_events(self, workspace_id: str, events: list[dict[str, Any]]) -> None:
        for event in events:
            self._session.add(BrowserCooperationEventORM(**event))

    async def latest_raw_events(self, workspace_id: str, limit: int) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserCooperationEventORM)
            .where(BrowserCooperationEventORM.browser_workspace_id == workspace_id)
            .order_by(BrowserCooperationEventORM.sequence.desc())
            .limit(max(1, min(limit, 200)))
        )
        return [_orm_event_to_dict(event) for event in reversed(result.scalars().all())]

    async def enforce_retention(self, workspace_id: str, limit: int) -> None:
        if limit <= 0:
            return
        cutoff_result = await self._session.execute(
            select(BrowserCooperationEventORM.sequence)
            .where(BrowserCooperationEventORM.browser_workspace_id == workspace_id)
            .order_by(BrowserCooperationEventORM.sequence.desc())
            .offset(limit)
            .limit(1)
        )
        cutoff = cutoff_result.scalar_one_or_none()
        if cutoff is None:
            return
        await self._session.execute(
            delete(BrowserCooperationEventORM).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace_id,
                BrowserCooperationEventORM.sequence <= int(cutoff),
            )
        )

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
    }
