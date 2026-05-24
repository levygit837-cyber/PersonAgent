"""Content caching, chunking, and extraction response helpers.

Extracted from ``helpers.py`` as part of browser_tools helpers Slice B.
Groups functions that share the ``_PAGE_CACHE`` collaborator and the
content-chunking verb.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any

from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.tools.browser_tools.link_helpers import (
    _coerce_links,
    _curate_links,
    _extract_markdown_links,
)

# ---------------------------------------------------------------------------
# Constants & singletons
# ---------------------------------------------------------------------------

_DEFAULT_CHUNK_SIZE = 3_000
_EXTRACT_INLINE_CONTENT_CHARS = 8_000
_MAX_CHUNK_COUNT = 6
_PAGE_CACHE = get_browser_page_cache()
_BROWSER_EXTRACT_IN_FLIGHT: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}

# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------


def _coerce_page_or_window_id(page_id: Any, window_id: Any) -> str | None:
    if isinstance(page_id, str) and page_id.strip():
        return page_id.strip()
    if isinstance(window_id, str) and window_id.strip():
        return window_id.strip()
    return None


# ---------------------------------------------------------------------------
# Content chunking & trimming
# ---------------------------------------------------------------------------


def _split_content_chunks(content: str, chunk_size: int) -> tuple[list[str], list[tuple[int, int]]]:
    chunks: list[str] = []
    ranges: list[tuple[int, int]] = []
    index = 0
    total = len(content)
    while index < total:
        hard_end = min(index + chunk_size, total)
        end = hard_end
        if hard_end < total:
            boundary = max(
                content.rfind("\n\n", index, hard_end),
                content.rfind("\n", index, hard_end),
                content.rfind(". ", index, hard_end),
            )
            if boundary > index + int(chunk_size * 0.55):
                end = boundary + (2 if content.startswith("\n\n", boundary) else 1)
        chunk = content[index:end].strip()
        if chunk:
            chunks.append(chunk)
            ranges.append((index, end))
        index = max(end, index + 1)
    return chunks, ranges


def _trim_content(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    boundary = max(
        content.rfind("\n\n", 0, max_chars),
        content.rfind("\n", 0, max_chars),
        content.rfind(". ", 0, max_chars),
    )
    if boundary > int(max_chars * 0.6):
        return content[: boundary + 1].rstrip()
    return content[:max_chars].rstrip()


# ---------------------------------------------------------------------------
# Page content caching
# ---------------------------------------------------------------------------


def _cache_page_content(conversation_id: str, data: dict[str, Any]) -> dict[str, Any]:
    content = str(data.get("content") or "")
    if not content:
        return {}
    url = str(data.get("url") or "")
    title = str(data.get("title") or "")
    digest = sha256(f"{url}\n{title}\n{content[:256]}".encode()).hexdigest()[:12]
    cache_key = f"page_{digest}"
    chunks, ranges = _split_content_chunks(content, _DEFAULT_CHUNK_SIZE)
    raw_links = _coerce_links(data.get("links"))
    if not raw_links:
        raw_links = _extract_markdown_links(content)
    links, links_summary = _curate_links(raw_links, content=content, source_url=url)
    page_id = _coerce_page_or_window_id(data.get("page_id"), data.get("window_id"))
    buttons = data.get("buttons") if isinstance(data.get("buttons"), list) else []
    entry = _PAGE_CACHE.store(
        conversation_id=conversation_id,
        cache_key=cache_key,
        url=url,
        title=title,
        page_id=page_id,
        content_chars=len(content),
        chunk_size=_DEFAULT_CHUNK_SIZE,
        chunks=chunks,
        chunk_ranges=ranges,
        links=links,
        links_summary=links_summary,
        buttons=buttons,
    )
    return {
        "cache_key": cache_key,
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunk_count": len(chunks),
        "page_id": entry.page_id,
        "window_id": entry.page_id,
        "links": links,
        "links_summary": links_summary,
        "buttons": buttons,
    }


# ---------------------------------------------------------------------------
# Extracted content response preparation
# ---------------------------------------------------------------------------


def _prepare_extracted_content_response(
    *,
    conversation_id: str,
    data: dict[str, Any],
    include_links: bool,
) -> dict[str, Any]:
    content = str(data.get("content") or "").strip()
    data["content"] = content
    data["content_chars"] = len(content)
    data["chunk_size"] = _DEFAULT_CHUNK_SIZE
    if not content:
        data.update(
            {
                "cache_key": None,
                "chunk_count": 0,
                "chunks_available": False,
                "content_available_in_chunks": False,
                "content_unavailable": True,
                "links": [],
                "links_summary": {
                    "total": 0,
                    "returned": 0,
                    "suppressed": False,
                    "reason": "no_readable_content",
                },
                "buttons": [],
                "message": (
                    "No readable page content was extracted. Try BrowserGetHtml, another source, "
                    "or opening the page in the browser before extracting again."
                ),
            }
        )
        return data

    cache_metadata = _cache_page_content(conversation_id, data)
    data.update(cache_metadata)
    if not include_links:
        data["links"] = []
    if len(content) > _EXTRACT_INLINE_CONTENT_CHARS:
        preview = _trim_content(content, _EXTRACT_INLINE_CONTENT_CHARS)
        data["content"] = preview
        data["content_preview"] = preview
        data["inline_content_truncated"] = True
        data["content_available_in_chunks"] = True
    else:
        data["content_preview"] = content
        data["inline_content_truncated"] = False
        data["content_available_in_chunks"] = False
    data["chunks_available"] = bool(data.get("chunk_count"))
    return data


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


async def _run_deduped_browser_extract(
    browser_id: str,
    target_key: str,
    factory: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], bool]:
    key_value = str(target_key or "").strip()
    if not key_value:
        return await factory(), False
    key = (browser_id, key_value)
    task = _BROWSER_EXTRACT_IN_FLIGHT.get(key)
    owner = task is None
    if task is None:
        task = asyncio.create_task(factory())
        _BROWSER_EXTRACT_IN_FLIGHT[key] = task
    try:
        data = await task
        return dict(data), not owner
    finally:
        if owner and _BROWSER_EXTRACT_IN_FLIGHT.get(key) is task:
            _BROWSER_EXTRACT_IN_FLIGHT.pop(key, None)


def _cached_extracted_content_response(
    entry: Any,
    *,
    max_chars: int,
    include_links: bool,
) -> dict[str, Any]:
    metadata = _PAGE_CACHE.metadata(entry)
    chunk_count = max(1, min(entry.chunk_count, _MAX_CHUNK_COUNT))
    chunks = _PAGE_CACHE.read_chunks(entry, 1, chunk_count)
    content = "\n\n".join(chunks).strip()
    if len(content) > max_chars:
        content = _trim_content(content, max_chars)
    returned_links = metadata.get("links", []) if include_links and isinstance(metadata.get("links"), list) else []
    links_summary = metadata.get("links_summary") if isinstance(metadata.get("links_summary"), dict) else {}
    buttons = metadata.get("buttons") if isinstance(metadata.get("buttons"), list) else []
    return {
        "type": "browser_extract_content",
        "browser_id": entry.conversation_id,
        "url": entry.url,
        "title": entry.title,
        "page_id": entry.page_id,
        "window_id": entry.page_id,
        "content": content,
        "content_preview": content,
        "content_chars": entry.content_chars,
        "chunk_size": entry.chunk_size or _DEFAULT_CHUNK_SIZE,
        "chunk_count": entry.chunk_count,
        "cache_key": entry.cache_key,
        "links": returned_links,
        "links_summary": links_summary,
        "buttons": buttons,
        "truncated": entry.content_chars > len(content),
        "inline_content_truncated": entry.content_chars > len(content),
        "content_available_in_chunks": entry.chunk_count > 1,
        "chunks_available": entry.chunk_count > 0,
        "already_read": True,
        "read_status": "cached",
        "duplicate_read_avoided": True,
    }


# ---------------------------------------------------------------------------
# Cache key resolution
# ---------------------------------------------------------------------------


def _resolve_cache_key(conversation_id: str, raw_cache_key: Any) -> str | None:
    return _PAGE_CACHE.resolve_key(conversation_id, raw_cache_key)
