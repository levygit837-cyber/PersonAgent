"""Browser Cooperation event tracking and agent-context contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
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
_SENSITIVE_FIELD_RE = re.compile(
    r"(password|passcode|passwd|pwd|token|secret|api[_-]?key|auth|session|cookie|"
    r"credit|card|cc-|cc_|cvv|cvc|expiry|iban|routing|ssn|cpf|email)",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "auth",
    "code",
    "email",
    "key",
    "password",
    "refresh_token",
    "session",
    "state",
    "token",
}
_EMAIL_RE = re.compile(r"^[^@\s]{1,120}@[^@\s]{1,120}\.[^@\s]{2,30}$")
_CARD_RE = re.compile(r"(?:\d[ -]?){13,19}")
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}$")
_LONG_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{32,}$")
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
            "policy": _policy_from_state(current),
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
                "policy": _policy_from_state(cooperation),
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
        seen_batch_keys: set[tuple[str, str, str, str, int]] = set()
        for raw in normalized_inputs:
            event_id = str(raw.get("event_id") or raw.get("id") or f"bev_{uuid4().hex[:12]}").strip()
            if event_id in existing_ids:
                dropped += 1
                continue
            dedupe_key = _event_dedupe_key(raw)
            if dedupe_key in seen_batch_keys:
                dropped += 1
                continue
            seen_batch_keys.add(dedupe_key)
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
                    channel=envelope.channel,
                    trace_role=envelope.trace_role,
                    visibility=envelope.visibility,
                    raw_kind=envelope.raw_kind,
                    kind=envelope.kind,
                    url=envelope.url,
                    target=envelope.target,
                    payload=envelope.payload,
                    coordinates=envelope.coordinates,
                    duration_ms=envelope.duration_ms,
                    trace_effect=envelope.trace_effect,
                    correlation_id=envelope.correlation_id,
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
            "policy": _policy_from_state(cooperation),
            "updated_at": _now_iso(),
        }
        state["cooperation"] = cooperation
        workspace.state = state
        await self._enforce_retention(workspace, cooperation)
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
        cooperation = _merge_metadata_cooperation(
            _cooperation_state_from_workspace(workspace, browser_id),
            conversation,
            browser_id,
        )
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
                    "channel": "action" if source == "agent" else "event",
                    "trace_role": source,
                    "visibility": "useful",
                    "raw_kind": kind,
                    "trace_effect": _trace_effect_for_kind(kind),
                    "tab_id": tab_id,
                    "page_id": page_id,
                    "url": event_url,
                    "payload": {"label": label, **(payload or {})},
                    "semantic_label": label,
                    "importance": "high",
                }
            ],
        )

    async def get_snapshot(
        self,
        conversation,
        *,
        browser_id: str,
        raw_limit: int = MAX_RAW_EVENTS_PREVIEW,
    ) -> dict[str, Any]:
        """Return the current realtime cooperation snapshot for the Browser UI."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        cooperation = _merge_metadata_cooperation(
            _cooperation_state_from_workspace(workspace, browser_id),
            conversation,
            browser_id,
        )
        raw_events = await self._latest_raw_events(workspace, limit=raw_limit)
        return {
            "type": "snapshot",
            "cooperation": cooperation,
            "state_patch": {"cooperation": cooperation},
            "page_state": _coerce_dict(cooperation.get("page_state")),
            "useful_timeline": _coerce_list(cooperation.get("useful_timeline"))[-MAX_USEFUL_TIMELINE:],
            "raw_events": raw_events,
            "recent_user_events": _coerce_list(cooperation.get("recent_user_events"))[-MAX_RECENT_ACTIONS:],
            "recent_agent_events": _coerce_list(cooperation.get("recent_agent_events"))[-MAX_AGENT_EVENTS:],
            "pending_action_proposals": _coerce_list(cooperation.get("pending_action_proposals"))[:MAX_PENDING_PROPOSALS],
        }

    async def resolve_proposal(
        self,
        conversation,
        *,
        browser_id: str,
        proposal_id: str,
        status: str,
    ) -> dict[str, Any]:
        """Mark a persisted Browser Arbiter proposal as approved, denied, or dismissed."""

        workspace = await self._get_or_create_workspace(conversation, browser_id)
        state = _coerce_dict(workspace.state)
        cooperation = _merge_metadata_cooperation(
            _cooperation_state_from_workspace(workspace, browser_id),
            conversation,
            browser_id,
        )
        resolved_status = status if status in {"approved", "denied", "dismissed"} else "dismissed"
        proposals: list[dict[str, Any]] = []
        resolved: dict[str, Any] | None = None
        for item in _coerce_list(cooperation.get("pending_action_proposals")):
            proposal = _coerce_dict(item)
            if str(proposal.get("proposal_id") or "") == proposal_id:
                proposal = {
                    **proposal,
                    "status": resolved_status,
                    "resolved_at": _now_iso(),
                }
                resolved = proposal
            proposals.append(proposal)
        cooperation = {
            **cooperation,
            "pending_action_proposals": proposals[:MAX_PENDING_PROPOSALS],
            "page_state": {
                **_coerce_dict(cooperation.get("page_state")),
                "active_proposal_id": None,
            },
            "updated_at": _now_iso(),
        }
        state["cooperation"] = cooperation
        workspace.state = state
        await self._session.commit()
        _mirror_browser_cooperation(conversation, browser_id, cooperation)
        return {
            "type": "proposal.resolved",
            "proposal": resolved or {"proposal_id": proposal_id, "status": resolved_status},
            "state_patch": {"cooperation": cooperation},
        }

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

    async def _latest_raw_events(
        self,
        workspace: BrowserWorkspaceORM,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(BrowserCooperationEventORM)
            .where(BrowserCooperationEventORM.browser_workspace_id == workspace.id)
            .order_by(BrowserCooperationEventORM.sequence.desc())
            .limit(max(1, min(limit, 200)))
        )
        events = [
            _orm_event_to_dict(event)
            for event in reversed(result.scalars().all())
        ]
        return events

    async def _enforce_retention(
        self,
        workspace: BrowserWorkspaceORM,
        cooperation: Mapping[str, Any],
    ) -> None:
        policy = _policy_from_state(cooperation)
        limit = int(policy.get("raw_event_retention_limit") or DEFAULT_COOPERATION_POLICY["raw_event_retention_limit"])
        if limit <= 0:
            return
        cutoff_result = await self._session.execute(
            select(BrowserCooperationEventORM.sequence)
            .where(BrowserCooperationEventORM.browser_workspace_id == workspace.id)
            .order_by(BrowserCooperationEventORM.sequence.desc())
            .offset(limit)
            .limit(1)
        )
        cutoff = cutoff_result.scalar_one_or_none()
        if cutoff is None:
            return
        await self._session.execute(
            delete(BrowserCooperationEventORM).where(
                BrowserCooperationEventORM.browser_workspace_id == workspace.id,
                BrowserCooperationEventORM.sequence <= int(cutoff),
            )
        )


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
        "useful_timeline": _coerce_list(cooperation.get("useful_timeline"))[-MAX_USEFUL_TIMELINE:],
        "recent_user_events": _coerce_list(cooperation.get("recent_user_events"))[-MAX_RECENT_ACTIONS:],
        "recent_agent_events": _coerce_list(cooperation.get("recent_agent_events"))[-MAX_AGENT_EVENTS:],
        "notifications": _coerce_list(cooperation.get("notifications"))[-MAX_NOTIFICATIONS:],
        "pending_action_proposals": _coerce_list(cooperation.get("pending_action_proposals"))[:MAX_PENDING_PROPOSALS],
        "policy": _policy_from_state(cooperation),
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
        "useful_timeline": _coerce_list(cooperation.get("useful_timeline"))[-MAX_USEFUL_TIMELINE:],
        "recent_user_events": _coerce_list(cooperation.get("recent_user_events"))[-MAX_RECENT_ACTIONS:],
        "recent_agent_events": _coerce_list(cooperation.get("recent_agent_events"))[-MAX_AGENT_EVENTS:],
        "notifications": _coerce_list(cooperation.get("notifications"))[-MAX_NOTIFICATIONS:],
        "pending_action_proposals": _coerce_list(cooperation.get("pending_action_proposals"))[:MAX_PENDING_PROPOSALS],
        "policy": _policy_from_state(cooperation),
        "last_user_activity_at": cooperation.get("last_user_activity_at"),
        "updated_at": cooperation.get("updated_at"),
    }


def _merge_metadata_cooperation(
    cooperation: Mapping[str, Any],
    conversation,
    browser_id: str,
) -> dict[str, Any]:
    metadata = getattr(conversation, "metadata", None)
    if not isinstance(metadata, Mapping):
        return dict(cooperation)
    root = _coerce_dict(metadata.get(BROWSER_COOPERATION_METADATA_KEY))
    mirrored = _coerce_dict(root.get(browser_id))
    if not mirrored:
        return dict(cooperation)
    page_state = {
        **_coerce_dict(cooperation.get("page_state")),
        **_coerce_dict(mirrored.get("page_state")),
    }
    return {
        **dict(cooperation),
        **mirrored,
        "page_state": page_state,
        "policy": _policy_from_state({**dict(cooperation), **mirrored}),
    }


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


def _redact_payload(kind: str, target: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _redact_json(_coerce_dict(payload), sensitive_parent=False)
    data = _cap_json(data, max_chars=MAX_PAYLOAD_CHARS)
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
            elif isinstance(value, Mapping):
                if value.get("hash"):
                    data[f"{key}_hash"] = value.get("hash")
                if value.get("char_count") is not None:
                    data[f"{key}_char_count"] = value.get("char_count")
        elif isinstance(value, str):
            data[key] = {
                "preview": _single_line(value)[:120],
                "char_count": len(value),
                "hash": sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16],
            }
    if kind == "keydown" and isinstance(data.get("key"), str) and len(str(data["key"])) == 1:
        data["key"] = "[character]"
    if isinstance(data.get("url"), str):
        data["url"] = _redact_url(str(data["url"]))
    if isinstance(data.get("from_url"), str):
        data["from_url"] = _redact_url(str(data["from_url"]))
    return data


def _redact_target(target: Mapping[str, Any]) -> dict[str, Any]:
    sensitive = _is_sensitive_target(target)
    data = _redact_json(dict(target), sensitive_parent=False)
    if isinstance(data.get("href"), str):
        data["href"] = _redact_url(str(data["href"]))
    if isinstance(data.get("form_action"), str):
        data["form_action"] = _redact_url(str(data["form_action"]))
    if sensitive:
        data["sensitive"] = True
        for key in ("text", "label", "placeholder", "aria_label", "name", "id"):
            if isinstance(data.get(key), str) and data.get(key):
                data[key] = "[REDACTED]"
    return data


def _redact_json(value: Any, *, sensitive_parent: bool = False) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            sensitive = sensitive_parent or bool(_SENSITIVE_FIELD_RE.search(text_key))
            if sensitive:
                redacted[text_key] = _redacted_value(item)
            else:
                redacted[text_key] = _redact_json(item, sensitive_parent=False)
        return redacted
    if isinstance(value, list):
        return [_redact_json(item, sensitive_parent=sensitive_parent) for item in value[:80]]
    if isinstance(value, str):
        if _looks_sensitive_string(value):
            return _redacted_value(value)
        return value
    return value


def _redacted_value(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, str):
        return "[REDACTED]"
    return {
        "redacted": True,
        "char_count": len(value),
        "hash": sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16],
    }


def _looks_sensitive_string(value: str) -> bool:
    compact = value.strip()
    if not compact:
        return False
    return bool(
        _EMAIL_RE.match(compact)
        or _CARD_RE.search(compact)
        or _JWT_RE.match(compact)
        or _LONG_TOKEN_RE.match(compact)
    )


def _is_sensitive_target(target: Mapping[str, Any]) -> bool:
    if target.get("sensitive") is True:
        return True
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


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return value[:2_000]
    if not parsed.query:
        return value[:2_000]
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS or _SENSITIVE_FIELD_RE.search(key) or _looks_sensitive_string(item):
            query.append((key, "[REDACTED]"))
        else:
            query.append((key, item))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))[:2_000]


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


def attach_browser_action_proposal(
    metadata: dict[str, Any],
    *,
    pending: Mapping[str, Any],
    arbiter_metadata: Mapping[str, Any],
    message: str,
) -> dict[str, Any] | None:
    """Attach a Browser Arbiter proposal to conversation metadata for the Browser UI."""

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
