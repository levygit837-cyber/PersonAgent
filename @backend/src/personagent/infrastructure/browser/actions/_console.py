from __future__ import annotations

from contextlib import suppress
from typing import Any

from personagent.infrastructure.browser.actions._constants import (
    _MAX_CONSOLE_ENTRIES_PER_PAGE,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)


class _ConsoleMixin:
    async def read_console(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        levels: list[str] | None = None,
        since_id: int | None = None,
        limit: int = 100,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Read a bounded ring buffer of captured console events for a browser page."""

        session = await self._w.session_manager.get_session(conversation_id)
        target_page_id = str(page_id or session.current_page_id or session.last_open_page_id or "").strip()
        if not target_page_id:
            last_open = self._w._last_open_cache.get(conversation_id)
            target_page_id = last_open.page_id if last_open is not None else conversation_id
        page = session.pages.get(target_page_id) or self._w.session_manager.preferred_session_page(session)
        with suppress(Exception):
            await self._w.console.drain_page_console_entries(page, conversation_id, target_page_id)
        allowed_levels = {str(level).lower() for level in levels or [] if str(level).strip()}
        page_entries = list(self._w._console_cache.get(conversation_id, {}).get(target_page_id, []))
        if since_id is not None:
            page_entries = [entry for entry in page_entries if entry.entry_id > int(since_id)]
        if allowed_levels:
            page_entries = [entry for entry in page_entries if entry.level.lower() in allowed_levels]
        safe_limit = min(max(int(limit), 1), _MAX_CONSOLE_ENTRIES_PER_PAGE)
        selected = page_entries[-safe_limit:]
        if clear:
            self._w._console_cache.get(conversation_id, {}).pop(target_page_id, None)
        return {
            "type": "browser_console",
            "page_id": target_page_id,
            "window_id": target_page_id,
            "url": _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "")),
            "title": await self._w.page_helpers.safe_title(page),
            "runtime": await self._w._browser_runtime.page_runtime(page),
            "render_mode": "html_mirror" if await self._w._browser_runtime.is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or target_page_id,
            "navigated": False,
            "entries": [entry.to_dict() for entry in selected],
            "next_since_id": selected[-1].entry_id if selected else since_id,
            "cleared": bool(clear),
        }
