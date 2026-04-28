"""Session panel routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.session_panel import SessionPanelService
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)


class SessionTitleVerifyRequest(BaseModel):
    """Request for batch session-title verification."""

    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    batch_size: int | None = Field(default=None, ge=1, le=50)
    force: bool = False
    dry_run: bool = False


@router.post("/titles/verify")
async def verify_session_titles(
    request: SessionTitleVerifyRequest,
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Run cached LLM title verification across persisted sessions."""

    container = get_container()
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
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Repair duplicate or near-duplicate persisted session titles."""

    container = get_container()
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
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return the aggregated session panel snapshot for one conversation."""

    conversation = await _load_conversation(conversation_id, session)
    return await SessionPanelService(workspace_root).panel_snapshot(conversation)


@router.get("/{conversation_id}/project/details")
async def get_session_project_detail(
    conversation_id: str,
    type: str = Query(..., description="Detail type: commit, push, pr or branch."),
    id: str = Query(..., description="Project item identifier."),
    workspace_root: str | None = Query(default=None),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return detail content for a project item in the floating panel window."""

    await _load_conversation(conversation_id, session)
    return SessionPanelService(workspace_root).project_detail(type, id)


async def _load_conversation(conversation_id: str, session: AsyncSession):
    container = get_container()
    repo = await container.get_conversation_repo(session)
    try:
        parsed = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
    conversation = await repo.get_by_id(parsed)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation
