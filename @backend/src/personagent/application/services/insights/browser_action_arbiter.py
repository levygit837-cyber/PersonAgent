"""Browser Action Channel arbiter for agent-initiated browser mutations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from personagent.application.services.browser_cooperation import (
    BROWSER_COOPERATION_DEFAULT_MODE,
    BROWSER_COOPERATION_METADATA_KEY,
)
from personagent.domain.tools import (
    ToolArguments,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolUseContext,
)

HUMAN_ACTIVITY_COOLDOWN_SECONDS = 3
DESTRUCTIVE_ACTIVITY_COOLDOWN_SECONDS = 10
_DESTRUCTIVE_RE = re.compile(
    r"(submit|save|delete|remove|checkout|purchase|buy|pay|confirm|login|sign in|upload|download|close)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BrowserArbiterDecision:
    behavior: ToolPermissionBehavior
    reason: str
    decision: str
    metadata: dict[str, Any]

    def to_permission_result(self) -> ToolPermissionResult:
        return ToolPermissionResult(
            behavior=self.behavior,
            message=self.reason,
            metadata=self.metadata,
        )


class BrowserActionArbiter:
    """Apply cooperation-mode rules before an agent mutates the browser."""

    def decide(
        self,
        *,
        tool_name: str,
        arguments: ToolArguments,
        context: ToolUseContext,
    ) -> BrowserArbiterDecision:
        state = self._active_state(context)
        if not state:
            return self._allow("Browser Cooperation is disabled.", tool_name, arguments, {})

        mode = str(state.get("agent_control") or state.get("mode") or BROWSER_COOPERATION_DEFAULT_MODE)
        if mode == "observe_only":
            return self._ask(
                "Browser Cooperation is in observe_only mode. Agent browser actions require approval.",
                "observe_only_requires_approval",
                tool_name,
                arguments,
                state,
            )
        if mode == "suggest_before_action":
            return self._ask(
                "Browser Cooperation is in suggest_before_action mode. Approve the proposed browser action to execute it.",
                "suggestion_requires_approval",
                tool_name,
                arguments,
                state,
            )

        if mode != "agent_control":
            return self._ask(
                "Browser Cooperation mode is unknown; browser action requires approval.",
                "unknown_mode_requires_approval",
                tool_name,
                arguments,
                state,
            )

        age = self._last_user_activity_age_seconds(state)
        destructive = self._is_destructive(tool_name, arguments)
        if age is not None and age <= HUMAN_ACTIVITY_COOLDOWN_SECONDS:
            return self._ask(
                "The user interacted with the browser recently. Approve this action before the agent continues.",
                "recent_user_activity",
                tool_name,
                arguments,
                state,
                extra={"last_user_activity_age_seconds": age},
            )
        if destructive and age is not None and age <= DESTRUCTIVE_ACTIVITY_COOLDOWN_SECONDS:
            return self._ask(
                "This browser action may be destructive and the user was recently active. Approval is required.",
                "destructive_recent_activity",
                tool_name,
                arguments,
                state,
                extra={"last_user_activity_age_seconds": age, "destructive": True},
            )
        if destructive and self._requires_explicit_confirmation(tool_name, arguments):
            return self._ask(
                "This browser action can submit, close, upload, download, or change important state. Approval is required.",
                "destructive_action_requires_approval",
                tool_name,
                arguments,
                state,
                extra={"destructive": True},
            )
        return self._allow("Browser action allowed by agent_control mode.", tool_name, arguments, state)

    def _active_state(self, context: ToolUseContext) -> dict[str, Any]:
        root = context.metadata.get(BROWSER_COOPERATION_METADATA_KEY)
        if not isinstance(root, Mapping):
            return {}
        preferred = root.get(context.conversation_id)
        if isinstance(preferred, Mapping) and preferred.get("enabled"):
            return dict(preferred)
        for item in root.values():
            if isinstance(item, Mapping) and item.get("enabled"):
                return dict(item)
        return {}

    def _last_user_activity_age_seconds(self, state: Mapping[str, Any]) -> float | None:
        raw = state.get("last_user_activity_at")
        if not raw:
            return None
        try:
            last = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        now = datetime.now(UTC)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return max(0.0, (now - last).total_seconds())

    def _is_destructive(self, tool_name: str, arguments: ToolArguments) -> bool:
        if tool_name in {"BrowserCloseTab"}:
            return True
        if tool_name == "BrowserScript":
            return True
        if tool_name == "BrowserType" and bool(arguments.get("submit")):
            return True
        action = str(arguments.get("action") or tool_name or "")
        target_text = " ".join(
            str(arguments.get(key) or "")
            for key in ("node_id", "value", "text", "key", "url")
        )
        if tool_name == "BrowserClick" and not arguments.get("node_id"):
            return True
        return bool(_DESTRUCTIVE_RE.search(f"{action} {target_text}"))

    def _requires_explicit_confirmation(self, tool_name: str, arguments: ToolArguments) -> bool:
        if tool_name in {"BrowserCloseTab", "BrowserScript"}:
            return True
        if tool_name == "BrowserAct" and str(arguments.get("action") or "") in {
            "submit",
            "upload",
            "drop",
        }:
            return True
        if tool_name == "BrowserType" and bool(arguments.get("submit")):
            return True
        if tool_name == "BrowserClick" and not arguments.get("node_id"):
            return True
        action = str(arguments.get("action") or "")
        text = " ".join(str(arguments.get(key) or "") for key in ("node_id", "value", "text"))
        return bool(_DESTRUCTIVE_RE.search(f"{action} {text}"))

    def _allow(
        self,
        reason: str,
        tool_name: str,
        arguments: ToolArguments,
        state: Mapping[str, Any],
    ) -> BrowserArbiterDecision:
        return BrowserArbiterDecision(
            behavior=ToolPermissionBehavior.ALLOW,
            reason=reason,
            decision="allow",
            metadata=self._metadata("allow", tool_name, arguments, state),
        )

    def _ask(
        self,
        reason: str,
        decision: str,
        tool_name: str,
        arguments: ToolArguments,
        state: Mapping[str, Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> BrowserArbiterDecision:
        return BrowserArbiterDecision(
            behavior=ToolPermissionBehavior.ASK,
            reason=f"permission_required: {reason}",
            decision=decision,
            metadata=self._metadata(decision, tool_name, arguments, state, extra=extra),
        )

    def _metadata(
        self,
        decision: str,
        tool_name: str,
        arguments: ToolArguments,
        state: Mapping[str, Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = {
            "node_id": arguments.get("node_id"),
            "page_id": arguments.get("page_id") or arguments.get("window_id"),
            "x": arguments.get("x"),
            "y": arguments.get("y"),
            "action": arguments.get("action") or tool_name,
        }
        return {
            "browser_action_arbiter": {
                "decision": decision,
                "mode": state.get("agent_control") or state.get("mode"),
                "event_channel": "browser_to_agent",
                "action_channel": "agent_to_arbiter_to_browser",
                "browser_id": state.get("browser_id"),
                "url": state.get("url"),
                "tool_name": tool_name,
                "target": {key: value for key, value in target.items() if value is not None},
                **(extra or {}),
            }
        }
