"""Session routes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.application.services.session_panel import SessionPanelService
from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.api.routes.sessions.browser_interaction import (
    register_browser_interaction_routes,
)
from personagent.interfaces.api.routes.sessions.browser_viewport import (
    _browser_worker as _browser_worker,
)
from personagent.interfaces.api.routes.sessions.browser_viewport import (
    register_browser_viewport_routes,
)
from personagent.interfaces.api.routes.sessions.cooperation import (
    register_cooperation_routes,
)
from personagent.interfaces.api.routes.sessions.models import (
    SessionTitleVerifyRequest,
)
from personagent.interfaces.api.routes.sessions.workspace_data import (
    register_workspace_data_routes,
)
from personagent.interfaces.api.workspace_grants import resolve_workspace_root
from personagent.interfaces.config.di_container import get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)

register_browser_viewport_routes(router)
register_cooperation_routes(router)
register_browser_interaction_routes(router)
register_workspace_data_routes(router)


# ---------------------------------------------------------------------------
# Panel & title routes
# ---------------------------------------------------------------------------


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
    workspace_id: str | None = Query(default=None),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return the aggregated session panel snapshot for one conversation."""

    conversation = await _load_conversation(conversation_id, session)
    return await SessionPanelService(
        _resolve_optional_workspace(workspace_root, workspace_id)
    ).panel_snapshot(conversation)


@router.get("/{conversation_id}/project/details")
async def get_session_project_detail(
    conversation_id: str,
    type: str = Query(..., description="Detail type: commit, push, pr or branch."),
    id: str = Query(..., description="Project item identifier."),
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    session: AsyncSession = DB_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    """Return detail content for a project item in the floating panel window."""

    await _load_conversation(conversation_id, session)
    return SessionPanelService(_resolve_optional_workspace(workspace_root, workspace_id)).project_detail(type, id)


# ---------------------------------------------------------------------------
# Shared helpers (used by panel routes and browser_workspace via late-binding)
# ---------------------------------------------------------------------------


def _resolve_optional_workspace(workspace_root: str | None, workspace_id: str | None) -> str | None:
    if not workspace_root and not workspace_id:
        return None
    try:
        return str(resolve_workspace_root(workspace_id=workspace_id, workspace_root=workspace_root))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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


async def _save_conversation(conversation, session: AsyncSession):
    container = get_container()
    repo = await container.get_conversation_repo(session)
    return await repo.update(conversation)


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_event_source(value: str) -> str:
    source = str(value or "").strip().lower()
    return source if source in {"user", "agent", "system"} else "user"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
