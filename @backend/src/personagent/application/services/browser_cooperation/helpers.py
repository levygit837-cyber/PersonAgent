"""Constants, data types, agent-context builders, proposals, and shared utilities."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

BROWSER_COOPERATION_METADATA_KEY = "browser_cooperation"
BROWSER_COOPERATION_DEFAULT_MODE = "observe_only"
BROWSER_COOPERATION_MODES = {"observe_only", "suggest_before_action", "agent_control"}
MAX_INGEST_EVENTS = 100
MAX_RECENT_ACTIONS = 12
MAX_NOTIFICATIONS = 12
MAX_VISIBLE_BUTTONS = 16
MAX_PAYLOAD_CHARS = 4_000
MAX_USEFUL_TIMELINE = 200
MAX_RAW_EVENTS_PREVIEW = 80
MAX_AGENT_EVENTS = 12
MAX_PENDING_PROPOSALS = 12
DEFAULT_COOPERATION_POLICY = {
    "raw_event_retention_limit": 5000,
    "raw_event_retention_days": 7,
    "visible_timeline_limit": 200,
    "agent_context_recent_limit": 12,
    "store_raw_payloads": False,
}
_TRACE_CHANNELS = {"event", "action", "proposal", "trace"}
_TRACE_ROLES = {"user", "agent", "system", "browser"}
_VISIBILITY = {"raw", "useful", "debug"}


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
    channel: str = "event"
    trace_role: str = "user"
    visibility: str = "raw"
    raw_kind: str | None = None
    coordinates: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    trace_effect: str | None = None
    correlation_id: str | None = None
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
            "channel": self.channel,
            "trace_role": self.trace_role,
            "visibility": self.visibility,
            "raw_kind": self.raw_kind,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "url": self.url,
            "target": self.target,
            "payload": self.payload,
            "coordinates": self.coordinates,
            "duration_ms": self.duration_ms,
            "trace_effect": self.trace_effect,
            "correlation_id": self.correlation_id,
            "importance": self.importance,
            "semantic_label": self.semantic_label,
        }


def build_browser_agent_context(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the compact BrowserAgentContext JSON object."""

    page_state = _coerce_dict(state.get("page_state"))
    recent_limit = int(_policy_from_state(state).get("agent_context_recent_limit") or MAX_RECENT_ACTIONS)
    return {
        "event_channel": "browser_to_agent",
        "action_channel": "agent_to_arbiter_to_browser",
        "agent_control": _normalize_mode(state.get("agent_control") or state.get("mode")),
        "browser_id": str(state.get("browser_id") or ""),
        "url": str(state.get("url") or page_state.get("url") or ""),
        "title": str(state.get("title") or page_state.get("title") or ""),
        "user_recent_actions": _coerce_list(state.get("recent_actions"))[-recent_limit:],
        "useful_timeline": _coerce_list(state.get("useful_timeline"))[-recent_limit:],
        "recent_user_events": _coerce_list(state.get("recent_user_events"))[-recent_limit:],
        "recent_agent_events": _coerce_list(state.get("recent_agent_events"))[-recent_limit:],
        "page_state": {
            "modal_open": bool(page_state.get("modal_open", False)),
            "focused_field": page_state.get("focused_field"),
            "visible_primary_buttons": _coerce_list(page_state.get("visible_primary_buttons"))[:MAX_VISIBLE_BUTTONS],
            "scroll": _coerce_dict(page_state.get("scroll")),
            "route": page_state.get("route"),
            "selected_element": page_state.get("selected_element"),
            "active_proposal_id": page_state.get("active_proposal_id"),
        },
        "pending_action_proposals": _coerce_list(state.get("pending_action_proposals"))[:MAX_PENDING_PROPOSALS],
    }


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


def shared_browser_workspace_reminder(metadata: Mapping[str, Any]) -> str | None:
    """Return always-on context for the shared Browser workspace."""

    workspace = _coerce_dict(metadata.get("browser_workspace"))
    current_url = str(workspace.get("current_url") or "").strip()
    tabs = [
        _compact_shared_browser_tab(tab)
        for tab in _coerce_list(workspace.get("tabs"))
        if isinstance(tab, Mapping)
    ]
    tabs = [tab for tab in tabs if tab.get("url") or tab.get("page_id")]
    active_tab_id = str(workspace.get("active_tab_id") or "").strip()
    active_browser_id = str(workspace.get("active_browser_id") or "").strip()
    if not current_url and not tabs and not active_tab_id:
        return None
    payload = {
        "browser_scope": "shared_panel_and_agent_browser",
        "browser_id": active_browser_id,
        "active_tab_id": active_tab_id,
        "current_url": current_url,
        "current_title": str(workspace.get("current_title") or "").strip(),
        "tabs": tabs[:5],
    }
    return (
        "# Shared Browser Workspace Context\n\n"
        "The user's Browser panel and your Browser tools are connected to the same Browser "
        "workspace for this conversation. When the user refers to browser actions, tabs, "
        "URLs, scroll position, or the open page, treat that as the shared panel browser, "
        "not a private browser owned only by the model. Use BrowserListTabs to refresh the "
        "shared tab state and use page_id/window_id from the shared tab list when a tab is "
        "already open.\n\n"
        "```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n```"
    )


def attach_browser_action_proposal(
    metadata: dict[str, Any],
    *,
    pending: Mapping[str, Any],
    arbiter_metadata: Mapping[str, Any],
    message: str,
) -> dict[str, Any] | None:
    """Attach a Browser Arbiter proposal to conversation metadata for the Browser UI."""
    from personagent.application.services.browser_cooperation.redaction import _redact_json

    browser_id = str(arbiter_metadata.get("browser_id") or "")
    if not browser_id:
        return None
    root = metadata.get(BROWSER_COOPERATION_METADATA_KEY)
    if not isinstance(root, dict):
        root = {}
        metadata[BROWSER_COOPERATION_METADATA_KEY] = root
    state = _coerce_dict(root.get(browser_id))
    proposal_id = f"proposal_{pending.get('approval_id') or uuid4().hex[:12]}"
    proposal = {
        "proposal_id": proposal_id,
        "approval_id": str(pending.get("approval_id") or ""),
        "tool_call_id": str(pending.get("tool_call_id") or ""),
        "tool_name": str(pending.get("tool_name") or arbiter_metadata.get("tool_name") or ""),
        "arguments": _redact_json(_coerce_dict(pending.get("arguments"))),
        "target": _coerce_dict(arbiter_metadata.get("target")),
        "reason": message,
        "status": "awaiting_approval",
        "mode": arbiter_metadata.get("mode"),
        "created_at": _now_iso(),
    }
    proposals = [
        item
        for item in _coerce_list(state.get("pending_action_proposals"))
        if str(_coerce_dict(item).get("proposal_id") or "") != proposal_id
    ]
    proposals.insert(0, proposal)
    page_state = _coerce_dict(state.get("page_state"))
    page_state["active_proposal_id"] = proposal_id
    state = {
        **state,
        "enabled": bool(state.get("enabled", True)),
        "mode": _normalize_mode(state.get("mode")),
        "agent_control": _normalize_mode(state.get("agent_control") or state.get("mode")),
        "browser_id": browser_id,
        "url": str(arbiter_metadata.get("url") or state.get("url") or ""),
        "page_state": page_state,
        "pending_action_proposals": proposals[:MAX_PENDING_PROPOSALS],
        "updated_at": _now_iso(),
    }
    root[browser_id] = state
    return proposal


def _compact_shared_browser_tab(tab: Mapping[str, Any]) -> dict[str, Any]:
    page_id = str(tab.get("page_id") or tab.get("window_id") or tab.get("tab_id") or tab.get("id") or "")
    state = _coerce_dict(tab.get("state"))
    return {
        "page_id": page_id,
        "window_id": page_id,
        "tab_id": page_id,
        "url": str(tab.get("url") or tab.get("final_url") or ""),
        "title": str(tab.get("title") or ""),
        "active": bool(tab.get("active") or tab.get("is_active")),
        "runtime": str(tab.get("runtime") or ""),
        "scroll": _coerce_dict(tab.get("scroll") or state.get("scroll")),
    }


def _iter_enabled_cooperation_states(metadata: Mapping[str, Any]):
    raw = _coerce_dict(metadata.get(BROWSER_COOPERATION_METADATA_KEY))
    for item in raw.values():
        state = _coerce_dict(item)
        if state.get("enabled"):
            yield state


def _normalize_mode(value: Any) -> str:
    mode = str(value or BROWSER_COOPERATION_DEFAULT_MODE).strip()
    return mode if mode in BROWSER_COOPERATION_MODES else BROWSER_COOPERATION_DEFAULT_MODE


def _policy_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = _coerce_dict(state.get("policy"))
    policy = {**DEFAULT_COOPERATION_POLICY, **raw}
    for key in ("raw_event_retention_limit", "raw_event_retention_days", "visible_timeline_limit", "agent_context_recent_limit"):
        try:
            policy[key] = max(1, int(policy[key]))
        except (TypeError, ValueError, KeyError):
            policy[key] = DEFAULT_COOPERATION_POLICY[key]
    policy["store_raw_payloads"] = bool(policy.get("store_raw_payloads", False))
    return policy


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
