"""Shared browser infrastructure models."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


class BrowserError(RuntimeError):
    """Base error for browser infrastructure failures."""


class BrowserUnavailableError(BrowserError):
    """Raised when the browser service cannot be used."""


class BrowserBlockedError(BrowserError):
    """Raised when the target site blocks browser automation."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        reason: str = "",
        url: str = "",
        title: str = "",
        sample: str = "",
    ) -> None:
        super().__init__(message)
        self.details = {
            "provider": provider,
            "reason": reason,
            "url": url,
            "title": title,
            "sample": sample,
        }


@dataclass(slots=True)
class BrowserSearchResult:
    """Search result stored in a conversation browser session."""

    index: int
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }


@dataclass(slots=True)
class BrowserSearchSnapshot:
    """Recent search results kept independently from the live browser page."""

    search_id: str
    query: str
    search_url: str
    provider: str
    results: list[BrowserSearchResult]
    created_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class BrowserOpenedPage:
    """Logical browser page opened during a conversation research session."""

    page_id: str
    url: str
    final_url: str
    title: str = ""
    source_search_id: str | None = None
    opener_tool_call_id: str | None = None
    opened_at: float = field(default_factory=time.monotonic)
    extraction_count: int = 0
    last_extracted_at: float | None = None

    @property
    def window_id(self) -> str:
        """Public browser-window identifier. Kept equal to page_id for compatibility."""

        return self.page_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "window_id": self.window_id,
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "source_search_id": self.source_search_id,
            "opener_tool_call_id": self.opener_tool_call_id,
            "extraction_count": self.extraction_count,
        }


@dataclass(slots=True)
class BrowserConsoleEntry:
    """Bounded console event captured for one logical browser page."""

    entry_id: int
    page_id: str
    level: str
    text: str
    source: str
    url: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.entry_id,
            "page_id": self.page_id,
            "level": self.level,
            "text": self.text,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class BrowserSession:
    browser: Any
    context: Any
    page: Any
    pages: dict[str, Any] = field(default_factory=dict)
    search_results: list[BrowserSearchResult] = field(default_factory=list)
    current_url: str | None = None
    last_open_url: str | None = None
    last_open_page_id: str | None = None
    current_page_id: str | None = None
    new_pages_supported: bool = True
    new_page_unavailable_logged: bool = False
    new_page_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.updated_at = time.monotonic()
