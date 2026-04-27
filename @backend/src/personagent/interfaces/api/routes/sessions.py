"""Session panel routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.session_panel import SessionPanelService
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)


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
        raise HTTPException(status_code=400, detail="conversation_id inválido.") from exc
    conversation = await repo.get_by_id(parsed)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation
