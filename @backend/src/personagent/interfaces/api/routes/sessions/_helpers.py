"""Shared helpers used across session route modules.

Accessed via late-binding (``import sessions as _sessions``) from
sub-modules so that test monkeypatches on ``sessions.get_container``
are resolved at call time.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.interfaces.api.workspace_grants import resolve_workspace_root


def _resolve_optional_workspace(workspace_root: str | None, workspace_id: str | None) -> str | None:
    if not workspace_root and not workspace_id:
        return None
    try:
        return str(resolve_workspace_root(workspace_id=workspace_id, workspace_root=workspace_root))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _container():
    """Late-binding lookup so test monkeypatches on sessions.get_container are resolved."""
    from personagent.interfaces.api.routes import sessions as _sess
    return _sess.get_container()


async def _load_conversation(conversation_id: str, session: AsyncSession):
    repo = await _container().get_conversation_repo(session)
    try:
        parsed = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
    conversation = await repo.get_by_id(parsed)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


async def _save_conversation(conversation, session: AsyncSession):
    repo = await _container().get_conversation_repo(session)
    return await repo.update(conversation)


async def _send_ws_json_safely(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except RuntimeError:
        return False


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
