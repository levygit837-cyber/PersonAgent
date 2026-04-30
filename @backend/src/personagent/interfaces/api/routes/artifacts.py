"""Serve local PersonAgent artifacts through controlled internal URLs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from personagent.infrastructure.artifacts import load_artifact
from personagent.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{conversation_id}/{category}/{artifact_id}")
async def get_artifact(conversation_id: str, category: str, artifact_id: str) -> FileResponse:
    settings = get_settings()
    try:
        artifact = load_artifact(
            category=category,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            root=settings.personagent_artifact_root,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found or expired.") from exc
    return FileResponse(
        artifact.path,
        media_type=artifact.mime_type,
        filename=artifact.artifact_id,
        content_disposition_type="inline",
    )
