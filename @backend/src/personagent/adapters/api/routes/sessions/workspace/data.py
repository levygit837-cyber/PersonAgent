"""Browser Workspace data routes — annotations, timeline, tab mentions."""

from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

import personagent.adapters.api.routes.sessions as _sessions
from personagent.adapters.api.routes.sessions.panel.models import (
    SessionBrowserAnnotationRequest,
)
from personagent.adapters.api.routes.sessions.workspace.infra import (
    _browser_workspace,
    _browser_workspace_service,
    _record_timeline_event,
    _workspace_payload,
)

# ---------------------------------------------------------------------------
# Browser mention helpers
# ---------------------------------------------------------------------------


def _normalize_browser_mention_query(query: str) -> str:
    normalized = str(query or "").strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if normalized.startswith("browser:"):
        normalized = normalized[len("browser:"):]
    elif normalized == "browser":
        normalized = ""
    return normalized.strip()


def _browser_mention_score(
    query: str,
    domain: str,
    url: str,
    title: str,
    active: bool,
    index: int,
) -> float:
    score = 0.0 if active else 1.0
    if not query:
        return score + index * 0.01
    if domain.lower() == query:
        return score
    if domain.lower().startswith(query):
        return score + 0.1
    if query in domain.lower():
        return score + 0.2
    if title.lower().startswith(query):
        return score + 0.4
    if query in title.lower():
        return score + 0.6
    if query in url.lower():
        return score + 0.8
    return score + 2.0


def _domain_from_url(url: str) -> str:
    try:
        return str(urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def _browser_tab_mention_suggestions(
    payload: dict[str, Any],
    *,
    browser_id: str,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    workspace_state = _sessions._coerce_dict(payload.get("workspace_state"))
    tabs = _sessions._coerce_list(payload.get("tabs"))
    active_tab_id = str(payload.get("active_tab_id") or workspace_state.get("active_tab_id") or browser_id)
    if not tabs and str(workspace_state.get("current_url") or ""):
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": str(workspace_state.get("current_url") or ""),
                "title": str(workspace_state.get("current_title") or ""),
                "runtime": str(workspace_state.get("runtime") or "lightpanda"),
                "active": True,
                "is_active": True,
                "state": {},
            }
        ]
    normalized_query = _normalize_browser_mention_query(query)
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tab in enumerate(tabs[:50]):
        tab_id = str(tab.get("tab_id") or tab.get("id") or active_tab_id or browser_id)
        url = str(tab.get("url") or tab.get("final_url") or "")
        title = str(tab.get("title") or "")
        domain = _domain_from_url(url)
        haystack = " ".join([domain, url, title, tab_id]).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        if tab_id in seen:
            continue
        seen.add(tab_id)
        active = bool(tab.get("active") or tab.get("is_active") or tab_id == active_tab_id)
        score = _browser_mention_score(normalized_query, domain, url, title, active, index)
        label_domain = domain or "tab"
        suggestions.append(
            {
                "type": "browser_tab",
                "id": f"browser_tab:{browser_id}:{tab_id}",
                "label": f"@Browser:{label_domain}",
                "token": f"@Browser:{label_domain}",
                "browser_id": browser_id,
                "tab_id": tab_id,
                "page_id": tab_id,
                "window_id": tab_id,
                "url": url,
                "title": title,
                "runtime": str(tab.get("runtime") or workspace_state.get("runtime") or ""),
                "active": active,
                "is_active": active,
                "display_path": title or url or tab_id,
                "domain": domain,
                "state": _sessions._coerce_dict(tab.get("state")),
                "updated_at": str(tab.get("updated_at") or ""),
                "score": score,
            }
        )
    return sorted(suggestions, key=lambda item: (float(item.get("score") or 99), str(item.get("display_path") or "")))[:limit]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_workspace_data_routes(router) -> None:
    """Register workspace data endpoints on the sessions router."""

    @router.post("/{conversation_id}/browser/{browser_id}/annotations")
    async def create_conversation_browser_annotation(
        conversation_id: str,
        browser_id: str,
        request: SessionBrowserAnnotationRequest,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Persist an annotation linked to a Browser Workspace element."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        service = _browser_workspace_service(session)
        if service is not None:
            return await service.create_annotation(
                conversation,
                browser_id=browser_id,
                node_id=request.node_id,
                body=request.body,
                quote=request.quote,
                url=request.url,
                title=request.title,
                selector=request.selector,
                frame_id=request.frame_id,
                selector_chain=request.selector_chain,
                shadow_path=request.shadow_path,
                tab_id=request.tab_id,
            )
        workspace = _browser_workspace(conversation)
        annotation = {
            "id": f"ann_{uuid4().hex[:12]}",
            "browser_id": browser_id,
            "tab_id": request.tab_id or browser_id,
            "node_id": request.node_id,
            "body": request.body.strip(),
            "quote": (request.quote or "").strip(),
            "url": (request.url or "").strip(),
            "title": (request.title or "").strip(),
            "selector": (request.selector or "").strip(),
            "frame_id": (request.frame_id or "main").strip(),
            "selector_chain": request.selector_chain or [],
            "shadow_path": request.shadow_path or [],
            "created_at": _sessions._now_iso(),
            "updated_at": _sessions._now_iso(),
        }
        annotations = _sessions._coerce_list(workspace.get("annotations"))
        annotations.append(annotation)
        workspace["annotations"] = annotations[-100:]
        await _record_timeline_event(
            session,
            conversation,
            browser_id=browser_id,
            event_type="annotation",
            source="user",
            label="Added annotation",
            payload={"node_id": request.node_id, "annotation_id": annotation["id"]},
        )
        await _sessions._save_conversation(conversation, session)
        return {"annotation": annotation, **_workspace_payload(conversation, browser_id)}

    @router.delete("/{conversation_id}/browser/{browser_id}/annotations/{annotation_id}")
    async def delete_conversation_browser_annotation(
        conversation_id: str,
        browser_id: str,
        annotation_id: str,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Delete a persisted Browser Workspace annotation."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        service = _browser_workspace_service(session)
        if service is not None:
            return await service.delete_annotation(
                conversation,
                browser_id=browser_id,
                annotation_id=annotation_id,
            )
        workspace = _browser_workspace(conversation)
        annotations = [
            item
            for item in _sessions._coerce_list(workspace.get("annotations"))
            if str(item.get("id") or "") != annotation_id
        ]
        workspace["annotations"] = annotations
        await _record_timeline_event(
            session,
            conversation,
            browser_id=browser_id,
            event_type="annotation_deleted",
            source="user",
            label="Deleted annotation",
            payload={"annotation_id": annotation_id},
        )
        await _sessions._save_conversation(conversation, session)
        return _workspace_payload(conversation, browser_id)

    @router.delete("/{conversation_id}/browser/{browser_id}/timeline")
    async def clear_conversation_browser_timeline(
        conversation_id: str,
        browser_id: str,
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Clear Browser Workspace timeline events for the current conversation."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        service = _browser_workspace_service(session)
        if service is not None:
            return await service.clear_timeline(conversation, browser_id=browser_id)
        workspace = _browser_workspace(conversation)
        workspace["timeline_events"] = [
            item
            for item in _sessions._coerce_list(workspace.get("timeline_events"))
            if str(item.get("browser_id") or "") != browser_id
        ]
        await _sessions._save_conversation(conversation, session)
        return _workspace_payload(conversation, browser_id)

    @router.get("/{conversation_id}/browser/mentions")
    async def list_conversation_browser_mentions(
        conversation_id: str,
        q: str = Query(default=""),
        limit: int = Query(default=20, ge=1, le=50),
        session: AsyncSession = _sessions.DB_SESSION_DEPENDENCY,
    ) -> list[dict[str, Any]]:
        """Return Browser tab mention suggestions for the shared conversation browser."""

        conversation = await _sessions._load_conversation(conversation_id, session)
        metadata_workspace = _browser_workspace(conversation)
        browser_id = str(metadata_workspace.get("active_browser_id") or conversation_id)
        service = _browser_workspace_service(session)
        if service is not None:
            payload = await service.payload(conversation, browser_id)
        else:
            payload = _workspace_payload(conversation, browser_id)
        return _browser_tab_mention_suggestions(
            payload,
            browser_id=browser_id,
            query=q,
            limit=limit,
        )
