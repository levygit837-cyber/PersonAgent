"""Event normalization, state application, timeline building, and dedup logic."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from personagent.application.services.browser_cooperation.helpers import (
    MAX_AGENT_EVENTS,
    MAX_NOTIFICATIONS,
    MAX_PAYLOAD_CHARS,
    MAX_RECENT_ACTIONS,
    MAX_USEFUL_TIMELINE,
    MAX_VISIBLE_BUTTONS,
    BrowserEventEnvelope,
    _cap_json,
    _coerce_dict,
    _coerce_list,
    _dedupe_keep_order,
    _now_iso,
    _optional_string,
    _parse_timestamp,
    _policy_from_state,
    _single_line,
)
from personagent.application.services.browser_cooperation.redaction import (
    _redact_payload,
    _redact_target,
    _redact_url,
)

_HIGH_IMPORTANCE_KINDS = {
    "click",
    "input",
    "change",
    "submit",
    "route",
    "route_change",
    "navigation",
    "action",
    "mutation",
}
_TRACE_CHANNELS = {"event", "action", "proposal", "trace"}
_TRACE_ROLES = {"user", "agent", "system", "browser"}
_VISIBILITY = {"raw", "useful", "debug"}


def _normalize_event(
    raw: Mapping[str, Any],
    *,
    conversation_id: str,
    browser_id: str,
    sequence: int,
) -> BrowserEventEnvelope:
    raw_kind = _optional_string(raw.get("raw_kind") or raw.get("rawKind") or raw.get("kind") or raw.get("type"))
    kind = _safe_kind(raw.get("kind") or raw.get("type") or "event")
    source = _safe_source(raw.get("source"))
    trace_role = _safe_trace_role(raw.get("trace_role") or raw.get("traceRole") or source)
    target = _redact_target(_cap_json(_coerce_dict(raw.get("target")), max_chars=MAX_PAYLOAD_CHARS))
    payload = _redact_payload(kind, target, _coerce_dict(raw.get("payload")))
    importance = _normalize_importance(raw.get("importance"), kind)
    semantic_label = str(raw.get("semantic_label") or raw.get("label") or "").strip()
    if not semantic_label:
        semantic_label = _semantic_label(kind, target, payload)
    coordinates = _normalize_coordinates(raw.get("coordinates") or payload.get("coordinates") or raw)
    url = _redact_url(str(raw.get("url") or payload.get("url") or "").strip())
    return BrowserEventEnvelope(
        event_id=str(raw.get("event_id") or raw.get("id") or f"bev_{uuid4().hex[:12]}").strip(),
        sequence=sequence,
        conversation_id=conversation_id,
        browser_id=browser_id,
        tab_id=_optional_string(raw.get("tab_id") or raw.get("tabId")),
        page_id=_optional_string(raw.get("page_id") or raw.get("pageId") or raw.get("window_id")),
        source=source,
        channel=_safe_channel(raw.get("channel")),
        trace_role=trace_role,
        visibility=_safe_visibility(raw.get("visibility"), importance),
        raw_kind=raw_kind[:120] if raw_kind else None,
        kind=kind,
        timestamp=_optional_string(raw.get("timestamp") or raw.get("occurred_at") or raw.get("created_at")),
        url=url[:2_000],
        target=target,
        payload=payload,
        coordinates=coordinates,
        duration_ms=_optional_int(raw.get("duration_ms") or raw.get("durationMs") or payload.get("duration_ms")),
        trace_effect=_safe_trace_effect(raw.get("trace_effect") or raw.get("traceEffect") or payload.get("trace_effect") or _trace_effect_for_kind(kind)),
        correlation_id=_optional_string(raw.get("correlation_id") or raw.get("correlationId") or payload.get("correlation_id")),
        importance=importance,
        semantic_label=semantic_label[:300],
    )


def _apply_events_to_cooperation_state(
    cooperation: Mapping[str, Any],
    events: list[BrowserEventEnvelope],
) -> dict[str, Any]:
    state = dict(cooperation)
    page_state = _coerce_dict(state.get("page_state"))
    recent_actions = _coerce_list(state.get("recent_actions"))
    useful_timeline = _coerce_list(state.get("useful_timeline"))
    recent_user_events = _coerce_list(state.get("recent_user_events"))
    recent_agent_events = _coerce_list(state.get("recent_agent_events"))
    notifications = _coerce_list(state.get("notifications"))
    for event in events:
        if event.url:
            state["url"] = event.url
            page_state["url"] = event.url
            route = urlparse(event.url).path or "/"
            page_state["route"] = route
        if event.kind in {"focus", "input", "change"}:
            field = _target_label(event.target)
            if field:
                page_state["focused_field"] = field
        if event.kind == "blur":
            page_state["focused_field"] = None
        if event.kind == "scroll":
            page_state["scroll"] = {
                "x": event.payload.get("scroll_x", event.payload.get("x", 0)),
                "y": event.payload.get("scroll_y", event.payload.get("y", 0)),
            }
        if event.kind in {"click", "focus", "selectionchange", "extract", "screenshot"} and event.target:
            page_state["selected_element"] = _compact_event_target(event.target)
        incoming_state = _coerce_dict(event.payload.get("page_state"))
        if incoming_state:
            if "modal_open" in incoming_state:
                page_state["modal_open"] = bool(incoming_state.get("modal_open"))
            buttons = _coerce_list(incoming_state.get("visible_primary_buttons"))
            if buttons:
                page_state["visible_primary_buttons"] = [
                    str(button)[:120] for button in buttons[:MAX_VISIBLE_BUTTONS]
                ]
        if event.source == "user" and event.kind in {"click", "input", "change", "keydown", "scroll", "submit", "focus", "blur"}:
            state["last_user_activity_at"] = event.timestamp or _now_iso()
        if event.semantic_label and event.importance in {"medium", "high"}:
            recent_actions.append(event.semantic_label)
        useful_item = _event_to_useful_timeline_item(event)
        if useful_item:
            useful_timeline.append(useful_item)
        role_item = _event_to_role_item(event)
        if event.trace_role == "agent" or event.source == "agent":
            recent_agent_events.append(role_item)
        elif event.trace_role == "user" or event.source == "user":
            recent_user_events.append(role_item)
        if event.importance == "high" and event.semantic_label:
            notifications.append(
                {
                    "event_id": event.event_id,
                    "kind": event.kind,
                    "label": event.semantic_label,
                    "url": event.url,
                    "timestamp": event.timestamp or _now_iso(),
                }
            )
    state["page_state"] = page_state
    state["recent_actions"] = _dedupe_keep_order(recent_actions)[-MAX_RECENT_ACTIONS:]
    state["useful_timeline"] = _dedupe_timeline(useful_timeline)[-MAX_USEFUL_TIMELINE:]
    state["recent_user_events"] = recent_user_events[-MAX_RECENT_ACTIONS:]
    state["recent_agent_events"] = recent_agent_events[-MAX_AGENT_EVENTS:]
    state["notifications"] = notifications[-MAX_NOTIFICATIONS:]
    state["policy"] = _policy_from_state(state)
    state["updated_at"] = _now_iso()
    return state


def _event_dedupe_key(raw: Mapping[str, Any]) -> tuple[str, str, str, str, int]:
    target = _coerce_dict(raw.get("target"))
    timestamp = str(raw.get("timestamp") or raw.get("occurred_at") or "")
    bucket = 0
    parsed = _parse_timestamp(timestamp)
    if parsed is not None:
        bucket = int(parsed.timestamp() * 5)
    return (
        str(raw.get("correlation_id") or raw.get("correlationId") or ""),
        _safe_source(raw.get("source")),
        _safe_kind(raw.get("kind") or raw.get("type") or "event"),
        str(target.get("node_id") or target.get("selector") or ""),
        bucket,
    )


def _event_to_useful_timeline_item(event: BrowserEventEnvelope) -> dict[str, Any] | None:
    if event.visibility == "raw" and event.importance == "low":
        return None
    if not event.semantic_label and event.importance != "high":
        return None
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "role": event.trace_role or event.source,
        "source": event.source,
        "channel": event.channel,
        "kind": event.kind,
        "label": event.semantic_label or event.kind,
        "target": _compact_event_target(event.target),
        "trace_effect": event.trace_effect,
        "url": event.url,
        "timestamp": event.timestamp or _now_iso(),
    }


def _event_to_role_item(event: BrowserEventEnvelope) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "kind": event.kind,
        "label": event.semantic_label or event.kind,
        "target": _compact_event_target(event.target),
        "trace_effect": event.trace_effect,
        "coordinates": event.coordinates,
        "timestamp": event.timestamp or _now_iso(),
    }


def _compact_event_target(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "node_id": target.get("node_id"),
            "role": target.get("role"),
            "tag": target.get("tag"),
            "label": target.get("label") or target.get("aria_label") or target.get("text"),
            "selector": target.get("selector"),
            "bounds": target.get("bounds"),
        }.items()
        if value not in (None, "", {})
    }


def _dedupe_timeline(values: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        item = _coerce_dict(value)
        key = str(item.get("event_id") or item.get("label") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _semantic_label(kind: str, target: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    label = _target_label(target)
    if kind == "click":
        return f"clicked {label or 'the page'}"
    if kind in {"input", "change"}:
        value = payload.get("value")
        if isinstance(value, dict):
            detail = f"{value.get('char_count', 0)} chars"
        elif value == "[REDACTED]":
            detail = "a redacted value"
        else:
            detail = "a value"
        return f"updated {label or 'a field'} with {detail}"
    if kind == "submit":
        return f"submitted {label or 'a form'}"
    if kind in {"route", "route_change", "navigation"}:
        return f"navigated to {payload.get('url') or 'a new route'}"
    if kind == "scroll":
        return "scrolled the page"
    if kind == "focus":
        return f"focused {label or 'a field'}"
    if kind == "mutation":
        return "page content changed"
    return f"{kind.replace('_', ' ')} on {label}" if label else kind.replace("_", " ")


def _target_label(target: Mapping[str, Any]) -> str:
    for key in ("label", "aria_label", "text", "placeholder", "name", "id", "role", "selector", "node_id"):
        value = str(target.get(key) or "").strip()
        if value:
            return _single_line(value)[:120]
    return ""


def _normalize_importance(value: Any, kind: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"low", "medium", "high"}:
        return raw
    return "high" if kind in _HIGH_IMPORTANCE_KINDS else "low"


def _safe_kind(value: Any) -> str:
    kind = str(value or "event").strip().lower().replace("-", "_")
    return re.sub(r"[^a-z0-9_]+", "_", kind)[:80] or "event"


def _safe_source(value: Any) -> str:
    source = str(value or "user").strip().lower()
    return source if source in {"user", "agent", "system", "browser"} else "user"


def _safe_channel(value: Any) -> str:
    channel = str(value or "event").strip().lower()
    return channel if channel in _TRACE_CHANNELS else "event"


def _safe_trace_role(value: Any) -> str:
    role = str(value or "user").strip().lower()
    return role if role in _TRACE_ROLES else "user"


def _safe_visibility(value: Any, importance: str) -> str:
    visibility = str(value or "").strip().lower()
    if visibility in _VISIBILITY:
        return visibility
    return "useful" if importance in {"medium", "high"} else "raw"


def _safe_trace_effect(value: Any) -> str | None:
    effect = str(value or "").strip().lower().replace("-", "_")
    effect = re.sub(r"[^a-z0-9_]+", "_", effect)[:80]
    return effect or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_coordinates(value: Any) -> dict[str, Any]:
    data = _coerce_dict(value)
    result: dict[str, Any] = {}
    for key in ("x", "y", "client_x", "client_y", "page_x", "page_y"):
        if key in data:
            number = _optional_float(data.get(key))
            if number is not None:
                result[key] = number
    bounds = _coerce_dict(data.get("bounds"))
    if bounds:
        result["bounds"] = {
            key: number
            for key in ("x", "y", "width", "height")
            if (number := _optional_float(bounds.get(key))) is not None
        }
    return result


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trace_effect_for_kind(kind: str) -> str:
    if kind in {"click", "dblclick", "mousedown"}:
        return "click"
    if kind in {"input", "change", "keydown", "type"}:
        return "type"
    if kind == "scroll":
        return "scroll"
    if kind in {"extract", "read_content", "read_content_chunk", "get_html", "screenshot"}:
        return "extract"
    if kind in {"focus", "selectionchange"}:
        return "highlight"
    return "highlight"
