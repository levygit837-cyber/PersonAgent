"""State extraction, mirroring, and merging for browser cooperation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from personagent.application.services.browser_cooperation.helpers import (
    MAX_AGENT_EVENTS,
    MAX_NOTIFICATIONS,
    MAX_PENDING_PROPOSALS,
    MAX_RECENT_ACTIONS,
    MAX_USEFUL_TIMELINE,
    _coerce_dict,
    _coerce_list,
    _normalize_mode,
    _policy_from_state,
)


def _cooperation_state_from_workspace(workspace: dict[str, Any], browser_id: str) -> dict[str, Any]:
    state = _coerce_dict(workspace.get("state"))
    cooperation = _coerce_dict(state.get("cooperation"))
    return {
        "enabled": bool(cooperation.get("enabled", False)),
        "mode": _normalize_mode(cooperation.get("mode")),
        "agent_control": _normalize_mode(cooperation.get("agent_control") or cooperation.get("mode")),
        "browser_id": str(cooperation.get("browser_id") or browser_id),
        "url": str(cooperation.get("url") or workspace.get("current_url") or ""),
        "title": str(cooperation.get("title") or workspace.get("current_title") or ""),
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
    root = metadata.get("browser_cooperation")
    if not isinstance(root, dict):
        root = {}
        metadata["browser_cooperation"] = root
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
    root = _coerce_dict(metadata.get("browser_cooperation"))
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
