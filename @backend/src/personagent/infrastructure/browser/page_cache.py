"""Disk-backed cache for extracted browser page content."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personagent.infrastructure.artifacts import artifact_root, safe_segment

DEFAULT_PAGE_CACHE_TTL_SECONDS = float(
    os.getenv("PERSONAGENT_BROWSER_PAGE_CACHE_TTL_SECONDS", "1800")
)
DEFAULT_PAGE_CACHE_PER_CONVERSATION = int(
    os.getenv("PERSONAGENT_BROWSER_PAGE_CACHE_PER_CONVERSATION", "8")
)
DEFAULT_PAGE_CACHE_GLOBAL_ENTRIES = int(
    os.getenv("PERSONAGENT_BROWSER_PAGE_CACHE_GLOBAL_ENTRIES", "128")
)


@dataclass(slots=True)
class PageCacheEntry:
    conversation_id: str
    cache_key: str
    page_id: str | None
    url: str
    title: str
    content_chars: int
    chunk_size: int
    chunk_count: int
    directory: Path
    created_at: float
    expires_at: float
    last_access: float

    def public_metadata(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "cache_key": self.cache_key,
            "page_id": self.page_id,
            "window_id": self.page_id,
            "url": self.url,
            "title": self.title,
            "content_chars": self.content_chars,
            "chunk_size": self.chunk_size,
            "chunk_count": self.chunk_count,
            "expires_at": self.expires_at,
        }


class BrowserPageCache:
    """LRU/TTL page cache with content chunks stored on disk."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        ttl_seconds: float = DEFAULT_PAGE_CACHE_TTL_SECONDS,
        per_conversation_limit: int = DEFAULT_PAGE_CACHE_PER_CONVERSATION,
        global_limit: int = DEFAULT_PAGE_CACHE_GLOBAL_ENTRIES,
    ) -> None:
        self.root = artifact_root(root) / "page-cache"
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.per_conversation_limit = max(1, int(per_conversation_limit))
        self.global_limit = max(1, int(global_limit))
        self._entries: dict[tuple[str, str], PageCacheEntry] = {}
        self._latest: dict[str, str] = {}

    def configure(
        self,
        *,
        root: str | Path | None = None,
        ttl_seconds: float | None = None,
        per_conversation_limit: int | None = None,
        global_limit: int | None = None,
    ) -> None:
        next_root = artifact_root(root) / "page-cache" if root is not None else self.root
        if next_root != self.root:
            self.root = next_root
            self._entries.clear()
            self._latest.clear()
        if ttl_seconds is not None:
            self.ttl_seconds = max(1.0, float(ttl_seconds))
        if per_conversation_limit is not None:
            self.per_conversation_limit = max(1, int(per_conversation_limit))
        if global_limit is not None:
            self.global_limit = max(1, int(global_limit))
        self.cleanup()

    def store(
        self,
        *,
        conversation_id: str,
        cache_key: str,
        url: str,
        title: str,
        page_id: str | None,
        content_chars: int,
        chunk_size: int,
        chunks: list[str],
        chunk_ranges: list[tuple[int, int]],
        links: list[dict[str, Any]],
        links_summary: dict[str, Any],
        buttons: list[dict[str, Any]],
    ) -> PageCacheEntry:
        now = time.time()
        safe_conversation = safe_segment(conversation_id, fallback="conversation")
        safe_cache_key = safe_segment(cache_key, fallback="page")
        directory = self.root / safe_conversation / safe_cache_key
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        chunks_dir = directory / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        for index, chunk in enumerate(chunks, start=1):
            (chunks_dir / f"{index:05d}.txt").write_text(chunk, encoding="utf-8")
        metadata = {
            "conversation_id": safe_conversation,
            "cache_key": safe_cache_key,
            "page_id": page_id,
            "window_id": page_id,
            "url": url,
            "title": title,
            "content_chars": content_chars,
            "chunk_size": chunk_size,
            "chunk_count": len(chunks),
            "chunk_ranges": chunk_ranges,
            "links": links,
            "links_summary": links_summary,
            "buttons": buttons,
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        entry = PageCacheEntry(
            conversation_id=safe_conversation,
            cache_key=safe_cache_key,
            page_id=page_id,
            url=url,
            title=title,
            content_chars=content_chars,
            chunk_size=chunk_size,
            chunk_count=len(chunks),
            directory=directory,
            created_at=now,
            expires_at=now + self.ttl_seconds,
            last_access=now,
        )
        self._entries[(safe_conversation, safe_cache_key)] = entry
        self._latest[safe_conversation] = safe_cache_key
        self._enforce_limits(now)
        return entry

    def latest_key(self, conversation_id: str) -> str | None:
        self.cleanup()
        return self._latest.get(safe_segment(conversation_id, fallback="conversation"))

    def resolve_key(self, conversation_id: str, raw_cache_key: Any) -> str | None:
        if isinstance(raw_cache_key, str) and raw_cache_key.strip():
            return safe_segment(raw_cache_key, fallback="")
        return self.latest_key(conversation_id)

    def get(self, conversation_id: str, cache_key: str) -> PageCacheEntry | None:
        now = time.time()
        safe_conversation = safe_segment(conversation_id, fallback="conversation")
        safe_cache_key = safe_segment(cache_key, fallback="")
        entry = self._entries.get((safe_conversation, safe_cache_key))
        if entry is None:
            entry = self._hydrate_entry(safe_conversation, safe_cache_key)
        if entry is None:
            return None
        if entry.expires_at <= now or not entry.directory.is_dir():
            self.evict(safe_conversation, safe_cache_key)
            return None
        entry.last_access = now
        self._latest[safe_conversation] = safe_cache_key
        return entry

    def metadata(self, entry: PageCacheEntry) -> dict[str, Any]:
        path = entry.directory / "metadata.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def read_chunks(self, entry: PageCacheEntry, start_index: int, count: int) -> list[str]:
        chunks: list[str] = []
        chunks_dir = entry.directory / "chunks"
        for index in range(start_index, start_index + count):
            path = chunks_dir / f"{index:05d}.txt"
            if not path.is_file():
                break
            chunks.append(path.read_text(encoding="utf-8"))
        entry.last_access = time.time()
        return chunks

    def evict(self, conversation_id: str, cache_key: str) -> None:
        safe_conversation = safe_segment(conversation_id, fallback="conversation")
        safe_cache_key = safe_segment(cache_key, fallback="")
        entry = self._entries.pop((safe_conversation, safe_cache_key), None)
        directory = entry.directory if entry else self.root / safe_conversation / safe_cache_key
        shutil.rmtree(directory, ignore_errors=True)
        if self._latest.get(safe_conversation) == safe_cache_key:
            self._latest.pop(safe_conversation, None)

    def clear_conversation(self, conversation_id: str, *, page_id: str | None = None) -> None:
        safe_conversation = safe_segment(conversation_id, fallback="conversation")
        candidates = [
            (conv, key, entry)
            for (conv, key), entry in list(self._entries.items())
            if conv == safe_conversation and (page_id is None or entry.page_id == page_id)
        ]
        if not candidates and page_id is None:
            shutil.rmtree(self.root / safe_conversation, ignore_errors=True)
            self._latest.pop(safe_conversation, None)
            return
        for conv, key, _entry in candidates:
            self.evict(conv, key)

    def cleanup(self) -> None:
        self._enforce_limits(time.time())

    def _hydrate_entry(self, conversation_id: str, cache_key: str) -> PageCacheEntry | None:
        metadata_path = self.root / conversation_id / cache_key / "metadata.json"
        if not metadata_path.is_file():
            return None
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        entry = PageCacheEntry(
            conversation_id=conversation_id,
            cache_key=cache_key,
            page_id=str(data.get("page_id") or "") or None,
            url=str(data.get("url") or ""),
            title=str(data.get("title") or ""),
            content_chars=int(data.get("content_chars") or 0),
            chunk_size=int(data.get("chunk_size") or 0),
            chunk_count=int(data.get("chunk_count") or 0),
            directory=metadata_path.parent,
            created_at=float(data.get("created_at") or 0),
            expires_at=float(data.get("expires_at") or 0),
            last_access=time.time(),
        )
        self._entries[(conversation_id, cache_key)] = entry
        return entry

    def _enforce_limits(self, now: float) -> None:
        for (conversation_id, cache_key), entry in list(self._entries.items()):
            if entry.expires_at <= now:
                self.evict(conversation_id, cache_key)
        by_conversation: dict[str, list[PageCacheEntry]] = {}
        for entry in self._entries.values():
            by_conversation.setdefault(entry.conversation_id, []).append(entry)
        for entries in by_conversation.values():
            for entry in sorted(entries, key=lambda item: item.last_access, reverse=True)[
                self.per_conversation_limit :
            ]:
                self.evict(entry.conversation_id, entry.cache_key)
        while len(self._entries) > self.global_limit:
            oldest = min(self._entries.values(), key=lambda item: item.last_access)
            self.evict(oldest.conversation_id, oldest.cache_key)


_PAGE_CACHE = BrowserPageCache()


def get_browser_page_cache() -> BrowserPageCache:
    return _PAGE_CACHE
