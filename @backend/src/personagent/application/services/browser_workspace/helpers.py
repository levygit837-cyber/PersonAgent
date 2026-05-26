"""Pure utility helpers for browser workspace operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _conversation_uuid(conversation) -> UUID:
    value = getattr(conversation, "id", None)
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _runtime_from_user_agent(user_agent: Any) -> str:
    agent = str(user_agent or "").lower()
    if agent.startswith("lightpanda/"):
        return "lightpanda"
    if agent:
        return "chrome_cdp"
    return ""


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_event_source(value: str) -> str:
    return value if value in {"user", "agent", "system"} else "user"


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _compact_element_map(raw_map: Any) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in _coerce_list(raw_map):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        compact.append(
            {
                "node_id": node_id,
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": str(item.get("text") or "")[:240],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": _coerce_list(item.get("selector_chain")),
                "shadow_path": _coerce_list(item.get("shadow_path")),
                "stable_key": str(item.get("stable_key") or ""),
                "interactable": bool(item.get("interactable")),
            }
        )
        if len(compact) >= 220:
            break
    return compact
