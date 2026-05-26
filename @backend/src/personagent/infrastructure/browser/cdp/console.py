"""Console & cooperation-event capture for the browser worker.

Extracted from ``lightpanda.py`` (Slice 9).  The ``BrowserConsole``
helper owns:

* Playwright ``console`` / ``pageerror`` event listeners
* Console-entry recording and per-page ring-buffer management
* JS-level console capture (install + drain)
* Cooperation-event capture for the ``__personagentBrowserEvent``
  bridge (install, drain, record)
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from personagent.infrastructure.browser.models import BrowserConsoleEntry
from personagent.infrastructure.browser.scripts.capture import (
    _CONSOLE_CAPTURE_SCRIPT,
    _CONSOLE_DRAIN_SCRIPT,
    _COOPERATION_CAPTURE_SCRIPT,
    _COOPERATION_DRAIN_SCRIPT,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

_MAX_CONSOLE_ENTRIES_PER_PAGE = 200


class BrowserConsole:
    """Manages console listeners, console entry recording, and cooperation events."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Console listeners
    # ------------------------------------------------------------------

    def attach_page_console_listeners(
        self, conversation_id: str, page_id: str, page: Any
    ) -> None:
        on_event = getattr(page, "on", None)
        if not callable(on_event):
            return
        key = (conversation_id, page_id, id(page))
        if key in self._w._console_listener_keys:
            return
        self._w._console_listener_keys.add(key)

        def handle_console(message: Any) -> None:
            level = self._console_message_attr(message, "type") or "log"
            text = self._console_message_attr(message, "text") or str(message)
            location = self._console_message_attr(message, "location")
            url = ""
            if isinstance(location, Mapping):
                url = str(location.get("url") or "")
            self.record_console_entry(
                conversation_id,
                page_id,
                level=str(level),
                text=str(text),
                source="console",
                url=url,
            )

        def handle_page_error(error: Any) -> None:
            self.record_console_entry(
                conversation_id,
                page_id,
                level="error",
                text=str(error),
                source="pageerror",
                url=_clean_browser_url(str(getattr(page, "url", "") or "")),
            )

        with suppress(Exception):
            on_event("console", handle_console)
        with suppress(Exception):
            on_event("pageerror", handle_page_error)

    @staticmethod
    def console_message_attr(message: Any, name: str) -> Any:
        value = getattr(message, name, None)
        if callable(value):
            with suppress(Exception):
                return value()
        return value

    # keep a private alias so internal closures can use it
    _console_message_attr = console_message_attr

    def record_console_entry(
        self,
        conversation_id: str,
        page_id: str,
        *,
        level: str,
        text: str,
        source: str,
        url: str = "",
    ) -> None:
        self._w._console_sequence += 1
        page_cache = (
            self._w._console_cache
            .setdefault(conversation_id, {})
            .setdefault(page_id, [])
        )
        page_cache.append(
            BrowserConsoleEntry(
                entry_id=self._w._console_sequence,
                page_id=page_id,
                level=(level or "log").lower(),
                text=str(text or "")[:8_000],
                source=source,
                url=url,
            )
        )
        del page_cache[:-_MAX_CONSOLE_ENTRIES_PER_PAGE]

    # ------------------------------------------------------------------
    # JS-level console capture
    # ------------------------------------------------------------------

    async def install_console_capture(self, page: Any) -> None:
        with suppress(Exception):
            await self._w._evaluate_page(page, _CONSOLE_CAPTURE_SCRIPT)

    async def drain_page_console_entries(
        self,
        page: Any,
        conversation_id: str,
        page_id: str,
    ) -> None:
        await self.install_console_capture(page)
        entries = await self._w._evaluate_page(page, _CONSOLE_DRAIN_SCRIPT)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            self.record_console_entry(
                conversation_id,
                page_id,
                level=str(entry.get("level") or "log"),
                text=str(entry.get("text") or ""),
                source=str(entry.get("source") or "console"),
                url=str(entry.get("url") or ""),
            )

    # ------------------------------------------------------------------
    # Cooperation events
    # ------------------------------------------------------------------

    async def install_cooperation_capture(
        self, page: Any, browser_id: str, page_id: str
    ) -> None:
        key = (browser_id, page_id, id(page))
        if key not in self._w._cooperation_listener_keys:
            expose_function = getattr(page, "expose_function", None)
            if callable(expose_function):
                with suppress(Exception):
                    await expose_function(
                        "__personagentBrowserEvent",
                        lambda event: self.record_cooperation_event(
                            browser_id, page_id, event
                        ),
                    )
            self._w._cooperation_listener_keys.add(key)
        with suppress(Exception):
            await self._w._evaluate_page(
                page,
                _COOPERATION_CAPTURE_SCRIPT,
                {"browserId": browser_id, "pageId": page_id},
            )

    async def drain_cooperation_events(
        self,
        page: Any,
        browser_id: str,
        page_id: str,
    ) -> list[dict[str, Any]]:
        await self.install_cooperation_capture(page, browser_id, page_id)
        entries: list[dict[str, Any]] = []
        cached = (
            self._w._cooperation_event_cache
            .setdefault(browser_id, {})
            .setdefault(page_id, [])
        )
        if cached:
            entries.extend(cached[:200])
            del cached[:200]
        with suppress(Exception):
            drained = await self._w._evaluate_page(
                page, _COOPERATION_DRAIN_SCRIPT
            )
            if isinstance(drained, list):
                entries.extend(
                    item for item in drained if isinstance(item, dict)
                )
        return entries[-200:]

    def record_cooperation_event(
        self, browser_id: str, page_id: str, event: Any
    ) -> None:
        if not isinstance(event, Mapping):
            return
        payload = dict(event)
        payload.setdefault("source", "user")
        payload.setdefault("channel", "event")
        payload.setdefault("trace_role", "user")
        payload.setdefault("page_id", page_id)
        payload.setdefault("tab_id", page_id)
        page_cache = (
            self._w._cooperation_event_cache
            .setdefault(browser_id, {})
            .setdefault(page_id, [])
        )
        page_cache.append(payload)
        if len(page_cache) > 500:
            del page_cache[: len(page_cache) - 500]
