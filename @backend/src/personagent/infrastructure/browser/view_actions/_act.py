from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from personagent.infrastructure.browser.models import BrowserError
from personagent.infrastructure.browser.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.view_actions._script import (
    _BROWSER_ACT_SCRIPT,
)


class _ActMixin:
    async def view_act(
        self,
        *,
        browser_id: str,
        node_id: str,
        action: str,
        width: int,
        height: int,
        value: str | None = None,
        key: str | None = None,
        target_node_id: str | None = None,
        timeout_ms: int | None = None,
        files: list[str] | None = None,
        text: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        """Execute a mapped DOM action and return the updated browser workspace view."""

        normalized_node_id = str(node_id or "").strip()
        normalized_action = str(action or "").strip().lower()
        if not normalized_node_id:
            raise BrowserError("BrowserAct requires node_id.")
        supported_actions = {
            "click",
            "fill",
            "submit",
            "select",
            "press",
            "hover",
            "wait",
            "drag",
            "drop",
            "upload",
            "select_text",
            "scroll_to",
            "screenshot",
        }
        if normalized_action not in supported_actions:
            raise BrowserError(f"BrowserAct action must be one of: {', '.join(sorted(supported_actions))}.")
        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w._set_page_viewport(page, viewport_width, viewport_height)
        previous_target = self._w._element_target(browser_id, normalized_node_id)
        previous_target_action = self._w._element_target(browser_id, str(target_node_id or "").strip())
        raw_map = await self._w.snapshot.browser_element_map(page)
        self._w._element_map_cache[browser_id] = self._w.snapshot.enrich_browser_element_map(
            raw_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        target = self._w._element_target(browser_id, normalized_node_id) or previous_target
        target_action = self._w._element_target(browser_id, str(target_node_id or "").strip()) or previous_target_action
        cached_selector = str(target.get("selector") or "")
        target_selector = str(target_action.get("selector") or "")
        action_context = await self._w._action_context_for_element(page, target)
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if normalized_action == "upload":
            result = await self._w._upload_files(action_context, cached_selector, files or [])
        else:
            result = await self._w._evaluate_page(
                action_context,
                _BROWSER_ACT_SCRIPT,
                {
                    "nodeId": normalized_node_id,
                    "selector": cached_selector,
                    "shadowPath": target.get("shadow_path") if isinstance(target.get("shadow_path"), list) else [],
                    "action": normalized_action,
                    "value": value,
                    "key": key,
                    "targetSelector": target_selector,
                    "targetShadowPath": target_action.get("shadow_path")
                    if isinstance(target_action.get("shadow_path"), list)
                    else [],
                    "timeoutMs": timeout_ms,
                    "text": text,
                    "x": x,
                    "y": y,
                    "targetText": target.get("text"),
                    "targetHref": target.get("href"),
                    "targetRole": target.get("role"),
                    "targetTag": target.get("tag"),
                },
            )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        navigated = bool(after_url and after_url != before_url)
        if (not isinstance(result, Mapping) or not result.get("ok")) and not navigated:
            reason = ""
            if isinstance(result, Mapping):
                reason = str(result.get("reason") or "")
            raise BrowserError(reason or "Browser action failed.")
        await self._w._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        view = await self._w.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
            wait_for_styles=False,
        )
        view["last_action"] = {
            "node_id": normalized_node_id,
            "action": normalized_action,
            "value": value if normalized_action in {"fill", "select"} else None,
            "key": key if normalized_action == "press" else None,
            "target_node_id": target_node_id,
            "timeout_ms": timeout_ms,
            "files": files if normalized_action == "upload" else None,
            "text": text if normalized_action == "select_text" else None,
            "target": self._w._browser_action_target_payload(target, fallback_node_id=normalized_node_id),
            "result": dict(result) if isinstance(result, Mapping) else result,
        }
        return view
