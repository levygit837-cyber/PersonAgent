"""Session cleanup — expire, enforce limits, and release resources."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.page.cache import get_browser_page_cache

logger = structlog.get_logger(__name__)


class _SessionCleanupMixin:
    """Methods for cleaning up and releasing browser sessions."""

    async def cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._w._sessions.items()
            if now - session.updated_at > self._w.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self.close_session(conversation_id, self._w._sessions[conversation_id])
        self._w.search_result_cache.cleanup_search_cache(now)

    async def enforce_session_limit(self) -> None:
        while len(self._w._sessions) > self._w.max_sessions:
            conversation_id, session = min(
                self._w._sessions.items(),
                key=lambda item: item[1].updated_at,
            )
            await self.close_session(conversation_id, session)

    async def reset_browser(self) -> None:
        async with self._w._lock:
            await self.close_sessions()

    async def close_sessions(self) -> None:
        for conversation_id, session in list(self._w._sessions.items()):
            await self.close_session(conversation_id, session)

    async def close_session(self, conversation_id: str, session: _BrowserSession) -> None:
        self._w._sessions.pop(conversation_id, None)
        self._w._element_map_cache.pop(conversation_id, None)
        self._w._console_cache.pop(conversation_id, None)
        self._w._cooperation_event_cache.pop(conversation_id, None)
        get_browser_page_cache().clear_conversation(conversation_id)
        self._w._snapshot_cache.clear_conversation(conversation_id)
        for page in self.session_pages(session):
            await self.best_effort_resource_call("browser_page_close", page.close)
        await self.best_effort_resource_call("browser_context_close", session.context.close)
        await self.release_browser(session.browser)

    async def release_browser(self, browser: Any) -> None:
        await self.best_effort_resource_call("browser_close", browser.close)

    async def best_effort_resource_call(
        self,
        label: str,
        operation: Any,
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await asyncio.wait_for(
                    result,
                    timeout=min(max(self._w.timeout_ms / 1000, 0.5), 2),
                )
        except Exception as exc:
            logger.debug("lightpanda_resource_close_failed", label=label, error=str(exc))
