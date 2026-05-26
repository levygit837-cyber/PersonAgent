"""Operational memory API routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from personagent.adapters.api.routes.memory._router import (
    CONTAINER_DEPENDENCY,
    EVENT_LIMIT_QUERY,
    logger,
    router,
)
from personagent.adapters.api.routes.memory.models import (
    OperationalRecallRequest,
    OperationalReindexRequest,
)
from personagent.adapters.composition import DIContainer


@router.get("/{project_slug}/operational/status")
async def get_operational_memory_status(
    project_slug: str,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Operational RAG memory status."""
    service = container.get_operational_memory_service()
    if service is None:
        return {"project_slug": project_slug, "enabled": False}
    status = await service.status(project_slug)
    try:
        status["embedding_runtime"] = container.get_embedding_process_manager().runtime_status()
    except Exception:
        logger.warning("embedding_runtime_status_failed", exc_info=True)
    status["enabled"] = True
    return status


@router.post("/{project_slug}/operational/recall")
async def preview_operational_memory_recall(
    project_slug: str,
    request: OperationalRecallRequest,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Preview the operational memory block that would enter the prompt."""
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    package = await service.recall_package_for_prompt(
        project_slug=project_slug,
        query=request.query,
        provider=request.provider,
        model=request.model,
        top_k=request.top_k,
        conversation_id=request.conversation_id,
        current_conversation_id=request.current_conversation_id,
        session_id=request.session_id,
        workspace_root=request.workspace_root,
        source_types=request.source_types,
        file_paths=request.file_paths,
        created_after=request.created_after,
        created_before=request.created_before,
        latest_only=request.latest_only,
        active_only=request.active_only,
        include_statuses=request.include_statuses,
        budget_tokens=request.budget_tokens,
    )
    return {
        "project_slug": project_slug,
        "query": request.query,
        "top_k": request.top_k,
        "formatted": package.formatted,
        "items": [_structured_memory_item_payload(item) for item in package.items],
        "filters_applied": package.filters_applied,
        "budget_used": package.budget_used,
        "budget_tokens": package.budget_tokens,
        "omitted_count": package.omitted_count,
        "latency_ms": package.latency_ms,
        "recall_scope": package.recall_scope,
        "query_intent": package.query_intent,
        "candidate_count": package.candidate_count,
        "token_usage": package.token_usage,
        "included_reasons": package.included_reasons,
        "discarded_candidates": package.discarded_candidates if request.debug else [],
        "ranking_breakdown": package.ranking_breakdown if request.debug else {},
    }


@router.get("/{project_slug}/operational/events")
async def list_operational_memory_events(
    project_slug: str,
    limit: int = EVENT_LIMIT_QUERY,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """List recent operational events."""
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    events = await service.repository.list_recent_events(project_slug, limit=limit)
    return {"project_slug": project_slug, "events": events, "count": len(events)}


@router.post("/{project_slug}/operational/reindex")
async def reindex_operational_memory(
    project_slug: str,
    request: OperationalReindexRequest,
    container: DIContainer = CONTAINER_DEPENDENCY,
) -> dict[str, Any]:
    """Accept an operational reindex request.

    v1 already indexes in real time; this endpoint reserves the public contract
    for backfill/reembedding jobs.
    """
    service = container.get_operational_memory_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Operational memory is disabled")
    result = await service.backfill_structured_memory(project_slug, limit=request.limit)
    return {
        "project_slug": project_slug,
        "status": "accepted",
        "source": request.source,
        "backfill": result,
        "message": "Structured operational-memory backfill completed for stored raw chunks.",
    }


def _structured_memory_item_payload(item: Any) -> dict[str, Any]:
    return {
        "type": item.type.value if hasattr(item.type, "value") else str(item.type),
        "summary": item.summary,
        "evidence": item.evidence,
        "paths": item.paths,
        "source_ids": item.source_ids,
        "event_types": item.event_types,
        "score": item.score,
        "status": item.status,
        "trust_level": getattr(item, "trust_level", "medium"),
        "importance": getattr(item, "importance", 0.5),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "metadata": item.metadata,
    }
