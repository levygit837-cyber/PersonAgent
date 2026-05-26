from __future__ import annotations

import asyncio
import json
from typing import Any

from personagent.infrastructure.browser.actions._constants import (
    _BROWSER_SCRIPT_CDP_ALLOWLIST,
    _MAX_BROWSER_SCRIPT_CHARS,
)
from personagent.infrastructure.browser.models import BrowserError
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)


class _ScriptMixin:
    async def script(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        mode: str = "evaluate",
        script: str | None = None,
        args: Any | None = None,
        cdp_method: str | None = None,
        cdp_params: dict[str, Any] | None = None,
        timeout_ms: int = 5_000,
    ) -> dict[str, Any]:
        """Run allowlisted page JS or selected CDP methods for advanced browser control."""

        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        normalized_mode = str(mode or "evaluate").strip().lower()
        safe_timeout_ms = min(max(int(timeout_ms), 1), 30_000)
        current_url = _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "about:blank"))
        if normalized_mode == "evaluate":
            if not isinstance(script, str) or not script.strip():
                raise BrowserError("BrowserScript evaluate requires a non-empty script.")
            if len(script) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(f"BrowserScript script is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters.")
            value = await asyncio.wait_for(
                self._w._evaluate_page(page, script, args),
                timeout=safe_timeout_ms / 1000,
            )
            method = "Runtime.evaluate"
        elif normalized_mode == "cdp":
            method = str(cdp_method or "").strip()
            if method not in _BROWSER_SCRIPT_CDP_ALLOWLIST:
                raise BrowserError(
                    "BrowserScript cdp_method must be one of: "
                    + ", ".join(sorted(_BROWSER_SCRIPT_CDP_ALLOWLIST))
                    + "."
                )
            raw_params = cdp_params or {}
            if len(json.dumps(raw_params, ensure_ascii=False, default=str)) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript cdp_params is too large; max {_MAX_BROWSER_SCRIPT_CHARS} serialized characters."
                )
            expression = raw_params.get("expression") if isinstance(raw_params, dict) else None
            if isinstance(expression, str) and len(expression) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript Runtime.evaluate expression is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters."
                )
            value = await asyncio.wait_for(
                self._w._cdp_command_for_page(
                    page,
                    url=current_url,
                    method=method,
                    params=raw_params,
                ),
                timeout=safe_timeout_ms / 1000,
            )
        else:
            raise BrowserError("BrowserScript mode must be one of: evaluate, cdp.")
        result_text, result, truncated = self._w._bounded_script_result(value)
        return {
            "type": "browser_script",
            "page_id": resolved_page_id,
            "window_id": resolved_page_id,
            "url": current_url,
            "title": await self._w.page_helpers.safe_title(page),
            "runtime": await self._w._page_runtime(page),
            "render_mode": "html_mirror" if await self._w._is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or resolved_page_id,
            "navigated": False,
            "mode": normalized_mode,
            "cdp_method": method if normalized_mode == "cdp" else None,
            "result": result,
            "result_text": result_text,
            "truncated": truncated,
        }
