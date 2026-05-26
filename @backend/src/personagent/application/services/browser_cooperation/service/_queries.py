"""Persistence queries for browser cooperation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.browser_cooperation.helpers import (
    DEFAULT_COOPERATION_POLICY,
    _coerce_dict,
    _conversation_uuid,
    _policy_from_state,
)
from personagent.infrastructure.persistence.models import (
    BrowserCooperationEventORM,
    BrowserWorkspaceORM,
)

from ._mapping import _orm_event_to_dict


async def _get_or_create_workspace(
    session: AsyncSession,
    conversation,
    browser_id: str,
) -> BrowserWorkspaceORM:
    conversation_id = _conversation_uuid(conversation)
    result = await session.execute(
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
    session.add(workspace)
    await session.flush()
    return workspace


async def _next_cooperation_sequence(
    session: AsyncSession,
    workspace: BrowserWorkspaceORM,
) -> int:
    result = await session.execute(
        select(func.max(BrowserCooperationEventORM.sequence)).where(
            BrowserCooperationEventORM.browser_workspace_id == workspace.id
        )
    )
    value = result.scalar_one_or_none()
    return int(value or 0) + 1


async def _existing_event_ids(
    session: AsyncSession,
    workspace: BrowserWorkspaceORM,
    event_ids: list[str],
) -> set[str]:
    if not event_ids:
        return set()
    result = await session.execute(
        select(BrowserCooperationEventORM.event_id).where(
            BrowserCooperationEventORM.browser_workspace_id == workspace.id,
            BrowserCooperationEventORM.event_id.in_(event_ids),
        )
    )
    return {str(item) for item in result.scalars().all()}


async def _latest_raw_events(
    session: AsyncSession,
    workspace: BrowserWorkspaceORM,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(BrowserCooperationEventORM)
        .where(BrowserCooperationEventORM.browser_workspace_id == workspace.id)
        .order_by(BrowserCooperationEventORM.sequence.desc())
        .limit(max(1, min(limit, 200)))
    )
    events = [
        _orm_event_to_dict(event)
        for event in reversed(result.scalars().all())
    ]
    return events


async def _enforce_retention(
    session: AsyncSession,
    workspace: BrowserWorkspaceORM,
    cooperation: Mapping[str, Any],
) -> None:
    policy = _policy_from_state(cooperation)
    limit = int(policy.get("raw_event_retention_limit") or DEFAULT_COOPERATION_POLICY["raw_event_retention_limit"])
    if limit <= 0:
        return
    cutoff_result = await session.execute(
        select(BrowserCooperationEventORM.sequence)
        .where(BrowserCooperationEventORM.browser_workspace_id == workspace.id)
        .order_by(BrowserCooperationEventORM.sequence.desc())
        .offset(limit)
        .limit(1)
    )
    cutoff = cutoff_result.scalar_one_or_none()
    if cutoff is None:
        return
    await session.execute(
        delete(BrowserCooperationEventORM).where(
            BrowserCooperationEventORM.browser_workspace_id == workspace.id,
            BrowserCooperationEventORM.sequence <= int(cutoff),
        )
    )
