"""ORM-to-dict mapping for browser cooperation events."""

from __future__ import annotations

from typing import Any

from personagent.application.services.browser_cooperation.helpers import _coerce_dict
from personagent.infrastructure.persistence.models import BrowserCooperationEventORM


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
        "target": _coerce_dict(event.target),
        "payload": _coerce_dict(event.payload),
        "coordinates": _coerce_dict(getattr(event, "coordinates", {})),
        "duration_ms": getattr(event, "duration_ms", None),
        "trace_effect": getattr(event, "trace_effect", None),
        "correlation_id": getattr(event, "correlation_id", None),
        "importance": event.importance,
        "semantic_label": event.semantic_label or "",
    }
