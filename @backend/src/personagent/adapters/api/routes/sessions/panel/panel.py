"""Session panel and title routes."""

from typing import Any

from fastapi import HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

import personagent.adapters.api.routes.sessions as _sessions
from personagent.adapters.api.routes.sessions.panel.models import (
    SessionTitleVerifyRequest,
)
from personagent.application.services.session.session_panel import SessionPanelService


def register_panel_routes(router) -> None:
    """Register session panel and title endpoints on the sessions router."""

    @router.post("/titles/verify")
    async def verify_session_titles(
        request: SessionTitleVerifyRequest,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Run cached LLM title verification across persisted sessions."""

        container = _sessions.get_container()
        service = getattr(container, "get_session_title_service", lambda: None)()
        if service is None:
            raise HTTPException(status_code=409, detail="Session title verification is disabled.")
        repo = await container.get_conversation_repo(session)
        result = await service.verify_all(
            repo,
            limit=request.limit,
            offset=request.offset,
            batch_size=request.batch_size,
            force=request.force,
            dry_run=request.dry_run,
        )
        return result.to_dict()

    @router.post("/titles/dedupe")
    async def dedupe_session_titles(
        force: bool = Query(default=True),
        dry_run: bool = Query(default=False),
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Repair duplicate or near-duplicate persisted session titles."""

        container = _sessions.get_container()
        service = getattr(container, "get_session_title_service", lambda: None)()
        if service is None:
            raise HTTPException(status_code=409, detail="Session title verification is disabled.")
        repo = await container.get_conversation_repo(session)
        result = await service.maybe_repair_duplicate_titles(repo, force=force, dry_run=dry_run)
        return result.to_dict()

    @router.get("/{conversation_id}/panel")
    async def get_session_panel(
        conversation_id: str,
        workspace_root: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Return the aggregated session panel snapshot for one conversation."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        return await SessionPanelService(
            _sessions._resolve_optional_workspace(workspace_root, workspace_id)
        ).panel_snapshot(conversation)

    @router.get("/{conversation_id}/project/details")
    async def get_session_project_detail(
        conversation_id: str,
        type: str = Query(..., description="Detail type: commit, push, pr or branch."),
        id: str = Query(..., description="Project item identifier."),
        workspace_root: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Return detail content for a project item in the floating panel window."""

        await _sessions._load_conversation(conversation_id, session)
        return SessionPanelService(_sessions._resolve_optional_workspace(workspace_root, workspace_id)).project_detail(type, id)
