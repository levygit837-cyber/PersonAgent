"""BrowserReadContentChunk tool factory."""

from __future__ import annotations

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolGroup,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.browser.building import (
    _DEFAULT_CHUNK_SIZE,
    _MAX_CHUNK_COUNT,
    _PAGE_CACHE,
    _browser_session_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _resolve_cache_key,
)


def create_browser_read_content_chunk_tool() -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        cache_key = arguments.get("cache_key")
        if cache_key is not None and (not isinstance(cache_key, str) or not cache_key.strip()):
            return _deny("BrowserReadContentChunk cache_key must be a non-empty string.")
        browser_id = _browser_session_id(context)
        resolved_cache_key = _resolve_cache_key(browser_id, cache_key)
        if not resolved_cache_key or _PAGE_CACHE.get(browser_id, resolved_cache_key) is None:
            return _deny("No cached browser page. Run BrowserExtractContent first.")
        chunk_index = arguments.get("chunk_index", 1)
        if not _is_int(chunk_index) or int(chunk_index) < 1:
            return _deny("BrowserReadContentChunk chunk_index must be 1 or greater.")
        chunk_count = arguments.get("chunk_count", 1)
        if not _is_int(chunk_count) or int(chunk_count) < 1 or int(chunk_count) > _MAX_CHUNK_COUNT:
            return _deny(
                f"BrowserReadContentChunk chunk_count must be between 1 and {_MAX_CHUNK_COUNT}."
            )
        include_links = arguments.get("include_links", False)
        if not isinstance(include_links, bool):
            return _deny("BrowserReadContentChunk include_links must be a boolean.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        browser_id = _browser_session_id(context)
        cache_key = _resolve_cache_key(browser_id, arguments.get("cache_key"))
        if not cache_key:
            return _error(call, "BrowserReadContentChunk", "No cached browser page.")
        entry = _PAGE_CACHE.get(browser_id, cache_key)
        if not entry:
            return _error(call, "BrowserReadContentChunk", f"No cached page for {cache_key}.")

        if entry.chunk_count <= 0:
            return _error(call, "BrowserReadContentChunk", f"No readable chunks for {cache_key}.")
        requested_index = int(arguments.get("chunk_index") or 1)
        requested_count = int(arguments.get("chunk_count") or 1)
        include_links = bool(arguments.get("include_links", False))
        start_index = min(max(1, int(arguments.get("chunk_index") or 1)), entry.chunk_count)
        count = min(max(1, int(arguments.get("chunk_count") or 1)), _MAX_CHUNK_COUNT)
        selected = _PAGE_CACHE.read_chunks(entry, start_index, count)
        metadata = _PAGE_CACHE.metadata(entry)
        ranges = metadata.get("chunk_ranges") if isinstance(metadata.get("chunk_ranges"), list) else []
        links_summary = metadata.get("links_summary", {})
        returned_links = metadata.get("links", []) if include_links else []
        data = {
            "type": "browser_content_chunks",
            "browser_id": browser_id,
            "cache_key": cache_key,
            "url": entry.url,
            "title": entry.title,
            "page_id": entry.page_id,
            "window_id": entry.page_id,
            "content_chars": entry.content_chars,
            "chunk_size": entry.chunk_size or _DEFAULT_CHUNK_SIZE,
            "requested_chunk_index": requested_index,
            "requested_chunk_count": requested_count,
            "chunk_index": start_index,
            "chunk_count": len(selected),
            "total_chunks": entry.chunk_count,
            "returned_chars": sum(len(content) for content in selected),
            "chunks": [
                {
                    "index": start_index + offset,
                    "char_start": ranges[start_index + offset - 1][0]
                    if start_index + offset - 1 < len(ranges)
                    else None,
                    "char_end": ranges[start_index + offset - 1][1]
                    if start_index + offset - 1 < len(ranges)
                    else None,
                    "char_count": len(content),
                    "content": content,
                }
                for offset, content in enumerate(selected)
            ],
            "links": returned_links,
            "links_summary": links_summary,
            "buttons": metadata.get("buttons", []),
        }
        return _json_result(call, "BrowserReadContentChunk", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserReadContentChunk",
            description=(
                "Read one or more chunks from the last cached BrowserExtractContent page "
                "without returning the entire page content."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "cache_key": {
                        "type": "string",
                        "description": "Optional cache key returned by BrowserExtractContent. Defaults to the latest cached page.",
                    },
                    "chunk_index": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 1,
                        "description": "1-based chunk index.",
                    },
                    "chunk_count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_CHUNK_COUNT,
                        "default": 1,
                        "description": (
                            "Number of consecutive chunks to return, capped to keep tool output bounded."
                        ),
                    },
                    "include_links": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return curated links only when they were not suppressed as navigation/link-list noise.",
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser cached content chunk page research",
            max_result_size_chars=18_000,
            is_read_only=True,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: True,
    )
