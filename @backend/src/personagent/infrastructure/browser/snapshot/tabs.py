"""Tab-snapshot helpers for browser snapshots."""

from __future__ import annotations

from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)


async def panel_session_tabs(
    worker: Any,
    *,
    max_tabs: int,
    exclude_conversation_id: str,
) -> list[dict[str, Any]]:
    tabs: list[dict[str, Any]] = []
    sessions = sorted(
        worker._sessions.items(),
        key=lambda item: getattr(item[1], "updated_at", 0.0),
        reverse=True,
    )
    for browser_id, session in sessions:
        if browser_id == exclude_conversation_id or not browser_id.startswith("browser:"):
            continue
        current_url = _clean_browser_url(
            str(
                session.current_url
                or worker._current_url_cache.get(browser_id)
                or getattr(session.page, "url", "")
                or ""
            )
        )
        if not current_url or current_url == "about:blank":
            continue
        title = ""
        with suppress(Exception):
            title = await worker.page_helpers.safe_title(session.page)
        page_id = session.current_page_id or session.last_open_page_id or browser_id
        parsed = urlparse(current_url)
        tabs.append(
            {
                "index": len(tabs) + 1,
                "browser_id": browser_id,
                "page_id": page_id,
                "window_id": page_id,
                "tab_id": page_id,
                "id": page_id,
                "url": current_url,
                "final_url": current_url,
                "domain": parsed.netloc,
                "title": title,
                "summary": title or parsed.netloc or current_url,
                "source_search_id": None,
                "opener_tool_call_id": None,
                "extraction_count": 0,
                "is_last_open": True,
                "is_current_page": True,
                "active": True,
                "is_active": True,
                "history": [current_url],
                "source": "shared_panel_session",
            }
        )
        if len(tabs) >= max_tabs:
            break
    return tabs


def browser_tabs_snapshot(
    worker: Any,
    browser_id: str,
    session: Any,
    *,
    current_url: str,
    title: str,
    runtime: str,
) -> list[dict[str, Any]]:
    opened_pages = worker._opened_pages_cache.get(browser_id, [])
    active_tab_id = session.current_page_id or browser_id
    tabs: list[dict[str, Any]] = []
    for index, opened_page in enumerate(opened_pages[:50], start=1):
        tabs.append(
            {
                "tab_id": opened_page.page_id,
                "id": opened_page.page_id,
                "url": opened_page.final_url or opened_page.url,
                "title": opened_page.title or title,
                "runtime": runtime,
                "active": opened_page.page_id == active_tab_id,
                "is_active": opened_page.page_id == active_tab_id,
                "history": [opened_page.final_url or opened_page.url],
                "index": index,
            }
        )
    if not tabs:
        tabs.append(
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": current_url,
                "title": title,
                "runtime": runtime,
                "active": True,
                "is_active": True,
                "history": [current_url] if current_url and current_url != "about:blank" else [],
                "index": 1,
            }
        )
    return tabs
