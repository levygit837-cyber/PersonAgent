"""Browser Cooperation event tracking and agent-context contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personagent.infrastructure.persistence.models import (
    BrowserCooperationEventORM,
    BrowserWorkspaceORM,
)

BROWSER_COOPERATION_METADATA_KEY = "browser_cooperation"
BROWSER_COOPERATION_DEFAULT_MODE = "observe_only"
BROWSER_COOPERATION_MODES = {"observe_only", "suggest_before_action", "agent_control"}
MAX_INGEST_EVENTS = 100
MAX_RECENT_ACTIONS = 12
MAX_NOTIFICATIONS = 12
MAX_VISIBLE_BUTTONS = 16
MAX_PAYLOAD_CHARS = 4_000
_SENSITIVE_FIELD_RE = re.compile(
    r"(password|passcode|passwd|pwd|token|secret|api[_-]?key|auth|session|cookie|"
    r"credit|card|cc-|cc_|cvv|cvc|expiry|iban|routing|ssn|cpf|email)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,30}$")
_CARD_RE = re.compile(r"(?:\d[ -]?){13,19}")
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


@dataclass(frozen=True, slots=True)
class BrowserEventEnvelope:
    """Normalized Browser -> Agent event envelope."""

    event_id: str
    sequence: int
    conversation_id: str
    browser_id: str
    kind: str
    source: str = "user"
    timestamp: str | None = None
    tab_id: str | None = None
    page_id: str | None = None
    url: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    importance: str = "low"
    semantic_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "conversation_id": self.conversation_id,
            "browser_id": self.browser_id,
            "tab_id": self.tab_id,
            "page_id": self.page_id,
            "source": self.source,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "url": self.url,
            "target": self.target,
            "payload": self.payload,
            "importance": self.importance,
            "semantic_label": self.semantic_label,
        }


class BrowserCooperationService:
    """Persist Browser Cooperation state and normalized event logs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_cooperation(
        self,
        conversation,
        *,
        browser_id: str,
        enabled: bool,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Enable/disable cooperation and store the current control mode."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        state = _coerce_dict(workspace.state)
        current = _cooperation_state_from_workspace(workspace, browser_id)
        next_mode = _normalize_mode(mode or current.get("mode") or BROWSER_COOPERATION_DEFAULT_MODE)
        cooperation = {
            **current,
            "enabled": bool(enabled),
            "mode": next_mode,
            "agent_control": next_mode,
            "browser_id": browser_id,
            "updated_at": _now_iso(),
        }
        state["cooperation"] = cooperation
        workspace.state = state
        await self._session.commit()
        _mirror_browser_cooperation(conversation, browser_id, cooperation)
        return {
            "cooperation": cooperation,
            "state_patch": {"cooperation": cooperation},
            "agent_context": build_browser_agent_context(cooperation),
        }

    async def ingest_events(
        self,
        conversation,
        *,
        browser_id: str,
        events: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Normalize, redact, persist, and summarize Browser -> Agent events."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        state = _coerce_dict(workspace.state)
        cooperation = _cooperation_state_from_workspace(workspace, browser_id)
        if not cooperation.get("enabled"):
            cooperation = {
                **cooperation,
                "enabled": False,
                "mode": _normalize_mode(cooperation.get("mode")),
                "agent_control": _normalize_mode(cooperation.get("agent_control") or cooperation.get("mode")),
                "browser_id": browser_id,
                "updated_at": _now_iso(),
            }
            state["cooperation"] = cooperation
            workspace.state = state
            await self._session.commit()
            _mirror_browser_cooperation(conversation, browser_id, cooperation)
            return {
                "accepted_count": 0,
                "dropped_count": len(events),
                "state_patch": {"cooperation": cooperation},
                "notifications": [],
            }

        normalized_inputs = [
            event for event in events[:MAX_INGEST_EVENTS] if isinstance(event, Mapping)
        ]
        existing_ids = await self._existing_event_ids(
            workspace,
            [
                str(event.get("event_id") or event.get("id") or "").strip()
                for event in normalized_inputs
                if str(event.get("event_id") or event.get("id") or "").strip()
            ],
        )
        next_sequence = await self._next_cooperation_sequence(workspace)
        accepted: list[BrowserEventEnvelope] = []
        dropped = len(events) - len(normalized_inputs)
        for raw in normalized_inputs:
            event_id = str(raw.get("event_id") or raw.get("id") or f"bev_{uuid4().hex[:12]}").strip()
            if event_id in existing_ids:
                dropped += 1
                continue
            envelope = _normalize_event(
                raw,
                conversation_id=str(_conversation_uuid(conversation)),
                browser_id=browser_id,
                sequence=next_sequence,
            )
            next_sequence += 1
            accepted.append(envelope)
            existing_ids.add(event_id)
            self._session.add(
                BrowserCooperationEventORM(
                    event_id=envelope.event_id,
                    browser_workspace_id=workspace.id,
                    conversation_id=_conversation_uuid(conversation),
                    browser_id=browser_id,
                    tab_id=envelope.tab_id,
                    page_id=envelope.page_id,
                    source=envelope.source,
                    kind=envelope.kind,
                    url=envelope.url,
                    target=envelope.target,
                    payload=envelope.payload,
                    importance=envelope.importance,
                    semantic_label=envelope.semantic_label,
                    sequence=envelope.sequence,
                    occurred_at=_parse_timestamp(envelope.timestamp),
                )
            )

        if accepted:
            cooperation = _apply_events_to_cooperation_state(cooperation, accepted)
        cooperation = {
            **cooperation,
            "enabled": True,
            "mode": _normalize_mode(cooperation.get("mode")),
            "agent_control": _normalize_mode(cooperation.get("agent_control") or cooperation.get("mode")),
            "browser_id": browser_id,
            "updated_at": _now_iso(),
        }
        state["cooperation"] = cooperation
        workspace.state = state
        await self._session.commit()
        _mirror_browser_cooperation(conversation, browser_id, cooperation)
        return {
            "accepted_count": len(accepted),
            "dropped_count": dropped,
            "state_patch": {"cooperation": cooperation},
            "notifications": cooperation.get("notifications", [])[-MAX_NOTIFICATIONS:],
        }

    async def record_canonical_event(
        self,
        conversation,
        *,
        browser_id: str,
        kind: str,
        source: str,
        label: str,
        payload: dict[str, Any] | None = None,
        tab_id: str | None = None,
        page_id: str | None = None,
        url: str | None = None,
    ) -> dict[str, Any] | None:
        """Record a backend-originated browser event when cooperation is enabled."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        cooperation = _cooperation_state_from_workspace(workspace, browser_id)
        if not cooperation.get("enabled"):
            return None
        event_url = url or (str(payload.get("url") or "") if isinstance(payload, dict) else "")
        return await self.ingest_events(
            conversation,
            browser_id=browser_id,
            events=[
                {
                    "event_id": f"canon_{uuid4().hex[:12]}",
                    "kind": kind,
                    "source": source,
                    "tab_id": tab_id,
                    "page_id": page_id,
                    "url": event_url,
                    "payload": {"label": label, **(payload or {})},
                    "semantic_label": label,
                    "importance": "high",
                }
            ],
        )

    async def _get_or_create_workspace(self, conversation, browser_id: str) -> BrowserWorkspaceORM:
        conversation_id = _conversation_uuid(conversation)
        result = await self._session.execute(
            select(BrowserWorkspaceORM).where(
                BrowserWorkspaceORM.conversation_id == conversation_id,
                BrowserWorkspaceORM.browser_id == browser_id,
            )
        )
        workspace = result.scalar_one_or_none()
        if workspace is not None:
            return workspace
        workspace = BrowserWorkspaceORM(
            conversation_id=conversation_id,
            browser_id=browser_id,
            workspace_id=str(_coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""),
            active_runtime="lightpanda",
            active_tab_id=browser_id,
            state={},
        )
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def _next_cooperation_sequence(self, workspace: BrowserWorkspaceORM) -> int:
        result = await self._session.execute(
            select(func.max(BrowserCooperationEventORM.sequence)).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace.id
            )
        )
        value = result.scalar_one_or_none()
        return int(value or 0) + 1

    async def _existing_event_ids(
        self,
        workspace: BrowserWorkspaceORM,
        event_ids: list[str],
    ) -> set[str]:
        if not event_ids:
            return set()
        result = await self._session.execute(
            select(BrowserCooperationEventORM.event_id).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace.id,
                BrowserCooperationEventORM.event_id.in_(event_ids),
            )
        )
        return {str(item) for item in result.scalars().all()}


def browser_agent_context_reminder(metadata: Mapping[str, Any]) -> str | None:
    """Return a compact model-visible Browser Cooperation context block."""

    contexts = []
    for state in _iter_enabled_cooperation_states(metadata):
        contexts.append(build_browser_agent_context(state))
    if not contexts:
        return None
    return (
        "# Browser Cooperation Context\n\n"
        "The browser Event Channel is observe-only context unless the user explicitly asks you "
        "to act. Mutating browser actions must go through the Action Channel and may require "
        "approval from the BrowserActionArbiter.\n\n"
        "```json\n"
        + json.dumps(contexts[:3], ensure_ascii=False, indent=2)
        + "\n```"
    )


def build_browser_agent_context(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the compact BrowserAgentContext JSON object."""

    page_state = _coerce_dict(state.get("page_state"))
    return {
        "event_channel": "browser_to_agent",
        "action_channel": "agent_to_arbiter_to_browser",
        "agent_control": _normalize_mode(state.get("agent_control") or state.get("mode")),
        "browser_id": str(state.get("browser_id") or ""),
        "url": str(state.get("url") or page_state.get("url") or ""),
        "title": str(state.get("title") or page_state.get("title") or ""),
        "user_recent_actions": _coerce_list(state.get("recent_actions"))[-MAX_RECENT_ACTIONS:],
        "page_state": {
            "modal_open": bool(page_state.get("modal_open", False)),
            "focused_field": page_state.get("focused_field"),
            "visible_primary_buttons": _coerce_list(page_state.get("visible_primary_buttons"))[:MAX_VISIBLE_BUTTONS],
            "scroll": _coerce_dict(page_state.get("scroll")),
            "route": page_state.get("route"),
        },
        "pending_action_proposals": _coerce_list(state.get("pending_action_proposals"))[:5],
    }


def _iter_enabled_cooperation_states(metadata: Mapping[str, Any]):
    raw = _coerce_dict(metadata.get(BROWSER_COOPERATION_METADATA_KEY))
    for item in raw.values():
        state = _coerce_dict(item)
        if state.get("enabled"):
            yield state


def _cooperation_state_from_workspace(workspace: BrowserWorkspaceORM, browser_id: str) -> dict[str, Any]:
    state = _coerce_dict(workspace.state)
    cooperation = _coerce_dict(state.get("cooperation"))
    return {
        "enabled": bool(cooperation.get("enabled", False)),
        "mode": _normalize_mode(cooperation.get("mode")),
        "agent_control": _normalize_mode(cooperation.get("agent_control") or cooperation.get("mode")),
        "browser_id": str(cooperation.get("browser_id") or browser_id),
        "url": str(cooperation.get("url") or workspace.current_url or ""),
        "title": str(cooperation.get("title") or workspace.current_title or ""),
        "page_state": _coerce_dict(cooperation.get("page_state")),
        "recent_actions": _coerce_list(cooperation.get("recent_actions"))[-MAX_RECENT_ACTIONS:],
        "notifications": _coerce_list(cooperation.get("notifications"))[-MAX_NOTIFICATIONS:],
        "pending_action_proposals": _coerce_list(cooperation.get("pending_action_proposals"))[:5],
        "last_user_activity_at": cooperation.get("last_user_activity_at"),
        "updated_at": cooperation.get("updated_at"),
    }


def _mirror_browser_cooperation(conversation, browser_id: str, cooperation: Mapping[str, Any]) -> None:
    metadata = getattr(conversation, "metadata", None)
    if not isinstance(metadata, dict):
        return
    root = metadata.get(BROWSER_COOPERATION_METADATA_KEY)
    if not isinstance(root, dict):
        root = {}
        metadata[BROWSER_COOPERATION_METADATA_KEY] = root
    root[browser_id] = {
        "enabled": bool(cooperation.get("enabled")),
        "mode": _normalize_mode(cooperation.get("mode")),
        "agent_control": _normalize_mode(cooperation.get("agent_control") or cooperation.get("mode")),
        "browser_id": browser_id,
        "url": str(cooperation.get("url") or ""),
        "title": str(cooperation.get("title") or ""),
        "page_state": _coerce_dict(cooperation.get("page_state")),
        "recent_actions": _coerce_list(cooperation.get("recent_actions"))[-MAX_RECENT_ACTIONS:],
        "notifications": _coerce_list(cooperation.get("notifications"))[-MAX_NOTIFICATIONS:],
        "pending_action_proposals": _coerce_list(cooperation.get("pending_action_proposals"))[:5],
        "last_user_activity_at": cooperation.get("last_user_activity_at"),
        "updated_at": cooperation.get("updated_at"),
    }


def _normalize_event(
    raw: Mapping[str, Any],
    *,
    conversation_id: str,
    browser_id: str,
    sequence: int,
) -> BrowserEventEnvelope:
    kind = _safe_kind(raw.get("kind") or raw.get("type") or "event")
    target = _cap_json(_coerce_dict(raw.get("target")), max_chars=MAX_PAYLOAD_CHARS)
    payload = _redact_payload(kind, target, _coerce_dict(raw.get("payload")))
    importance = _normalize_importance(raw.get("importance"), kind)
    semantic_label = str(raw.get("semantic_label") or raw.get("label") or "").strip()
    if not semantic_label:
        semantic_label = _semantic_label(kind, target, payload)
    return BrowserEventEnvelope(
        event_id=str(raw.get("event_id") or raw.get("id") or f"bev_{uuid4().hex[:12]}").strip(),
        sequence=sequence,
        conversation_id=conversation_id,
        browser_id=browser_id,
        tab_id=_optional_string(raw.get("tab_id") or raw.get("tabId")),
        page_id=_optional_string(raw.get("page_id") or raw.get("pageId") or raw.get("window_id")),
        source=_safe_source(raw.get("source")),
        kind=kind,
        timestamp=_optional_string(raw.get("timestamp") or raw.get("occurred_at") or raw.get("created_at")),
        url=str(raw.get("url") or payload.get("url") or "").strip()[:2_000],
        target=target,
        payload=payload,
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
    state["notifications"] = notifications[-MAX_NOTIFICATIONS:]
    state["updated_at"] = _now_iso()
    return state


def _redact_payload(kind: str, target: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _cap_json(_coerce_dict(payload), max_chars=MAX_PAYLOAD_CHARS)
    sensitive = _is_sensitive_target(target) or _payload_has_sensitive_value(data)
    for key in ("value", "text", "input", "typed_text", "selected_text"):
        if key not in data:
            continue
        value = data.get(key)
        if sensitive:
            data[key] = "[REDACTED]"
            data[f"{key}_redacted"] = True
            if isinstance(value, str):
                data[f"{key}_hash"] = sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
        elif isinstance(value, str):
            data[key] = {
                "preview": _single_line(value)[:120],
                "char_count": len(value),
                "hash": sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16],
            }
    if kind == "keydown" and isinstance(data.get("key"), str) and len(str(data["key"])) == 1:
        data["key"] = "[character]"
    return data


def _is_sensitive_target(target: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(target.get(key) or "")
        for key in ("input_type", "type", "autocomplete", "name", "id", "label", "aria_label", "placeholder")
    )
    return bool(_SENSITIVE_FIELD_RE.search(text))


def _payload_has_sensitive_value(payload: Mapping[str, Any]) -> bool:
    for key in ("value", "text", "input", "typed_text", "selected_text"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        compact = value.strip()
        if _EMAIL_RE.match(compact) or _CARD_RE.search(compact):
            return True
    return False


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


def _normalize_mode(value: Any) -> str:
    mode = str(value or BROWSER_COOPERATION_DEFAULT_MODE).strip()
    return mode if mode in BROWSER_COOPERATION_MODES else BROWSER_COOPERATION_DEFAULT_MODE


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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _conversation_uuid(conversation) -> UUID:
    value = getattr(conversation, "id", None)
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cap_json(value: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return value
    return {
        "truncated": True,
        "preview": serialized[:max_chars],
        "original_char_count": len(serialized),
    }


def _dedupe_keep_order(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
