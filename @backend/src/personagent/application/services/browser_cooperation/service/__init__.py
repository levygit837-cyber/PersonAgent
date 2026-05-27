"""BrowserCooperationService — persistence layer for browser cooperation state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from personagent.application.services.browser_cooperation.event_processing import (
    _apply_events_to_cooperation_state,
    _event_dedupe_key,
    _normalize_event,
    _trace_effect_for_kind,
)
from personagent.application.services.browser_cooperation.helpers import (
    MAX_AGENT_EVENTS,
    MAX_INGEST_EVENTS,
    MAX_NOTIFICATIONS,
    MAX_PENDING_PROPOSALS,
    MAX_RAW_EVENTS_PREVIEW,
    MAX_RECENT_ACTIONS,
    MAX_USEFUL_TIMELINE,
    _coerce_dict,
    _coerce_list,
    _conversation_uuid,
    _normalize_mode,
    _now_iso,
    _parse_timestamp,
    _policy_from_state,
    build_browser_agent_context,
)
from personagent.application.services.browser_cooperation.ports import (
    BrowserCooperationRepository,
)

from .._state import (
    _cooperation_state_from_workspace,
    _merge_metadata_cooperation,
    _mirror_browser_cooperation,
)


class BrowserCooperationService:
    """Persist Browser Cooperation state and normalized event logs."""

    def __init__(self, repository: BrowserCooperationRepository) -> None:
        self._repository = repository

    async def set_cooperation(
        self,
        conversation,
        *,
        browser_id: str,
        enabled: bool,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Enable/disable cooperation and store the current control mode."""

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        state = _coerce_dict(workspace.get("state"))
        current = _cooperation_state_from_workspace(workspace, browser_id)
        next_mode = _normalize_mode(mode or current.get("mode") or "observe_only")
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
        await self._repository.update_workspace_state(workspace["id"], state)
        await self._repository.commit()
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

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        state = _coerce_dict(workspace.get("state"))
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
            await self._repository.update_workspace_state(workspace["id"], state)
            await self._repository.commit()
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
        existing_ids = await self._repository.existing_event_ids(
            workspace["id"],
            [
                str(event.get("event_id") or event.get("id") or "").strip()
                for event in normalized_inputs
                if str(event.get("event_id") or event.get("id") or "").strip()
            ],
        )
        next_sequence = await self._repository.next_sequence(workspace["id"])
        accepted: list[Any] = []
        dropped = len(events) - len(normalized_inputs)
        seen_batch_keys: set[tuple[str, str, str, str, int]] = set()
        orm_events: list[dict[str, Any]] = []
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
                conversation_id=conversation_id,
                browser_id=browser_id,
                sequence=next_sequence,
            )
            next_sequence += 1
            accepted.append(envelope)
            existing_ids.add(event_id)
            orm_events.append(
                {
                    "event_id": envelope.event_id,
                    "browser_workspace_id": workspace["id"],
                    "conversation_id": conversation_id,
                    "browser_id": browser_id,
                    "tab_id": envelope.tab_id,
                    "page_id": envelope.page_id,
                    "source": envelope.source,
                    "channel": envelope.channel,
                    "trace_role": envelope.trace_role,
                    "visibility": envelope.visibility,
                    "raw_kind": envelope.raw_kind,
                    "kind": envelope.kind,
                    "url": envelope.url,
                    "target": envelope.target,
                    "payload": envelope.payload,
                    "coordinates": envelope.coordinates,
                    "duration_ms": envelope.duration_ms,
                    "trace_effect": envelope.trace_effect,
                    "correlation_id": envelope.correlation_id,
                    "importance": envelope.importance,
                    "semantic_label": envelope.semantic_label,
                    "sequence": envelope.sequence,
                    "occurred_at": _parse_timestamp(envelope.timestamp),
                }
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
        await self._repository.update_workspace_state(workspace["id"], state)
        if orm_events:
            await self._repository.persist_events(workspace["id"], orm_events)
        policy = _policy_from_state(cooperation)
        limit = int(policy.get("raw_event_retention_limit", 0))
        await self._repository.enforce_retention(workspace["id"], limit)
        await self._repository.commit()
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

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
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

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        cooperation = _merge_metadata_cooperation(
            _cooperation_state_from_workspace(workspace, browser_id),
            conversation,
            browser_id,
        )
        raw_events = await self._repository.latest_raw_events(workspace["id"], raw_limit)
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

        conversation_id = str(_conversation_uuid(conversation))
        workspace_id = str(
            _coerce_dict(getattr(conversation, "metadata", {})).get("workspace_id") or ""
        )
        workspace = await self._repository.get_or_create_workspace(
            conversation_id, browser_id, workspace_id
        )
        state = _coerce_dict(workspace.get("state"))
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
        await self._repository.update_workspace_state(workspace["id"], state)
        await self._repository.commit()
        _mirror_browser_cooperation(conversation, browser_id, cooperation)
        return {
            "type": "proposal.resolved",
            "proposal": resolved or {"proposal_id": proposal_id, "status": resolved_status},
            "state_patch": {"cooperation": cooperation},
        }


__all__ = ["BrowserCooperationService"]
