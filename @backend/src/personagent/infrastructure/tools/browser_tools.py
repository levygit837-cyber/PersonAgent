"""LightPanda browser tools for the main chat agent."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.web_tools import validate_web_url


def create_browser_tools(worker: LightPandaBrowserWorker) -> list[Tool]:
    """Create all LightPanda browser tools."""

    return [
        create_browser_search_tool(worker),
        create_browser_open_tool(worker),
        create_browser_list_tabs_tool(worker),
        create_browser_extract_content_tool(worker),
        create_browser_read_content_chunk_tool(),
        create_browser_get_html_tool(worker),
        create_browser_get_element_map_tool(worker),
        create_browser_act_tool(worker),
    ]


_DEFAULT_CHUNK_SIZE = 3_000
_EXTRACT_INLINE_CONTENT_CHARS = 8_000
_MAX_CHUNK_COUNT = 6
_MAX_RETURNED_LINKS = 20
_LINK_SUPPRESSION_THRESHOLD = 24
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_LOW_QUALITY_LINK_TEXT = {
    "about",
    "advertise",
    "all",
    "author",
    "careers",
    "category",
    "contact",
    "deals",
    "follow",
    "games",
    "home",
    "login",
    "more",
    "privacy",
    "read more",
    "search",
    "see all",
    "see more",
    "share",
    "shop",
    "sign in",
    "sign up",
    "subscribe",
    "tag",
    "terms",
    "topics",
}
_LOW_QUALITY_PATH_MARKERS = (
    "/about",
    "/advert",
    "/author/",
    "/authors/",
    "/category/",
    "/contact",
    "/deals",
    "/gift",
    "/login",
    "/newsletter",
    "/privacy",
    "/search",
    "/shop",
    "/sitemap",
    "/tag/",
    "/tags/",
    "/terms",
    "/topics/",
    "/vetted/",
)
_PAGE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_LATEST_CACHE_KEY: dict[str, str] = {}
_BROWSER_OPEN_URL_KEYS = ("url", "result_url", "final_url", "href", "link")
_BROWSER_OPEN_INDEX_KEYS = (
    "result_index",
    "index",
    "resultIndex",
    "position",
    "result_number",
    "result",
)
_BROWSER_OPEN_DIRECT_INDEX_KEYS = tuple(
    key for key in _BROWSER_OPEN_INDEX_KEYS if key != "result"
)
_BROWSER_OPEN_SEARCH_ID_KEYS = ("search_id", "searchId")


def create_browser_search_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return _deny("BrowserSearch requires a non-empty 'query' string.")
        max_results = arguments.get("max_results", 5)
        if not _is_int(max_results) or int(max_results) < 1 or int(max_results) > 10:
            return _deny("BrowserSearch max_results must be an integer between 1 and 10.")
        return validate_web_url(worker.search_url(query), context)

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        query = str(arguments["query"]).strip()
        max_results = min(max(1, int(arguments.get("max_results") or 5)), 10)
        provider = getattr(worker, "search_provider_label", "the configured search provider")
        await _progress(
            context, call, f"Searching {provider} with browser CDP...", {"query": query}
        )
        try:
            data = await worker.search(
                conversation_id=context.conversation_id,
                query=query,
                max_results=max_results,
            )
        except Exception as exc:
            return _error(call, "BrowserSearch", str(exc), exc)
        return _json_result(call, "BrowserSearch", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserSearch",
            description=(
                "Search the configured provider using the local browser CDP session and return organic results. "
                "Use this before opening a result URL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to run on the configured provider.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser bing google chrome lightpanda search web research",
            is_read_only=True,
            is_open_world=True,
            timeout_ms=90_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: True,
    )


def create_browser_open_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        target = _normalize_browser_open_arguments(arguments)
        url = target["url"]
        result_index = target["result_index"]
        search_id = target["search_id"]
        if target["invalid_search_id"]:
            return _deny("BrowserOpen search_id must be a string when provided.")
        if url:
            return validate_web_url(url, context)
        if result_index is not None and result_index < 1:
            return _deny("BrowserOpen result_index must be 1 or greater.")
        if target["invalid_result_index"]:
            return _deny("BrowserOpen result_index must be an integer.")
        if result_index is None and search_id:
            return None
        if result_index is None:
            return _deny(
                "BrowserOpen requires 'url', 'result_index', or 'search_id'. "
                "When only search_id is provided, it opens the first result from that search."
            )
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        target = _normalize_browser_open_arguments(arguments)
        target_url = target["url"]
        target_result_index = target["result_index"]
        target_search_id = target["search_id"]
        if target_url and target_result_index is not None:
            target_result_index = None
        if target_url is None and target_result_index is None and target_search_id:
            target_result_index = 1
        await _progress(
            context,
            call,
            "Opening page with LightPanda...",
            {
                "url": target_url,
                "result_index": target_result_index,
                "search_id": target_search_id,
                "recovered_from": target["recovered_from"],
            },
        )
        try:
            data = await worker.open(
                conversation_id=context.conversation_id,
                url=target_url,
                result_index=target_result_index,
                search_id=target_search_id,
                tool_call_id=call.id,
            )
            final_validation = validate_web_url(str(data.get("final_url") or ""), context)
            if final_validation is not None:
                return _error(
                    call, "BrowserOpen", final_validation.message or "Final URL is blocked."
                )
        except Exception as exc:
            return _error(call, "BrowserOpen", str(exc), exc)
        return _json_result(call, "BrowserOpen", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserOpen",
            description=(
                "Open a URL, a 1-based result_index from recent cached BrowserSearch results, "
                "or the first result from a provided search_id. Returns page_id/window_id for "
                "later extraction. If url and result_index are both provided, url wins."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTP or HTTPS URL to open. May be paired with search_id to record which BrowserSearch result it came from.",
                    },
                    "result_index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-based index from a recent BrowserSearch result list.",
                    },
                    "index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Alias for result_index.",
                    },
                    "search_id": {
                        "type": "string",
                        "description": "Optional search_id returned by BrowserSearch. With result_index it disambiguates the cache; with url the backend matches the URL to that search when possible; alone it opens result_index 1.",
                    },
                    "href": {
                        "type": "string",
                        "description": "Alias for url when the model copied a search-result href.",
                    },
                    "link": {
                        "type": "string",
                        "description": "Alias for url.",
                    },
                },
                "additionalProperties": True,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser open url navigate lightpanda",
            is_read_only=True,
            is_open_world=True,
            timeout_ms=90_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: True,
    )


def create_browser_list_tabs_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserListTabs max_tabs must be an integer between 1 and 50.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        max_tabs = min(max(1, int(arguments.get("max_tabs") or 20)), 50)
        await _progress(
            context,
            call,
            "Listing browser tabs...",
            {"max_tabs": max_tabs},
        )
        try:
            data = await worker.list_tabs(
                conversation_id=context.conversation_id,
                max_tabs=max_tabs,
            )
        except Exception as exc:
            return _error(call, "BrowserListTabs", str(exc), exc)
        return _json_result(call, "BrowserListTabs", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserListTabs",
            description=(
                "List browser tabs/pages opened by BrowserOpen in the current chat conversation. "
                "Use this to recover page_id values and keep long research sessions consistent."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "max_tabs": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 20,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser list tabs pages page_id research opened urls",
            is_read_only=True,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: True,
    )


def create_browser_extract_content_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_error = _validate_page_or_window_id(
            page_id,
            window_id,
            tool_name="BrowserExtractContent",
        )
        if target_error is not None:
            return target_error
        target_id = _coerce_page_or_window_id(page_id, window_id)
        if isinstance(url, str) and url.strip() and target_id:
            return _deny(
                "BrowserExtractContent requires either 'url' or 'page_id/window_id', not both."
            )
        if isinstance(url, str) and url.strip():
            validation = validate_web_url(url, context)
            if validation is not None:
                return validation
        max_chars = arguments.get("max_chars", context.limits.get("result_max_chars", 20_000))
        if not _is_int(max_chars) or int(max_chars) < 1 or int(max_chars) > 200_000:
            return _deny("BrowserExtractContent max_chars must be between 1 and 200000.")
        include_links = arguments.get("include_links", False)
        if not isinstance(include_links, bool):
            return _deny("BrowserExtractContent include_links must be a boolean.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_id = _coerce_page_or_window_id(page_id, window_id)
        max_chars = int(
            arguments.get("max_chars") or context.limits.get("result_max_chars", 20_000)
        )
        include_links = bool(arguments.get("include_links", False))
        await _progress(
            context,
            call,
            "Extracting page content with LightPanda...",
            {"url": url, "page_id": page_id, "window_id": window_id},
        )
        try:
            data = await worker.extract_content(
                conversation_id=context.conversation_id,
                url=str(url).strip() if isinstance(url, str) and url.strip() else None,
                page_id=target_id,
                max_chars=max_chars,
                include_links=include_links,
            )
        except Exception as exc:
            return _error(call, "BrowserExtractContent", str(exc), exc)
        data = dict(data)
        data = _prepare_extracted_content_response(
            conversation_id=context.conversation_id,
            data=data,
            include_links=include_links,
        )
        return _json_result(call, "BrowserExtractContent", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserExtractContent",
            description=(
                "Return organized markdown/text content from the current LightPanda page or "
                "from a provided URL/page_id. The tool prepares the rendered page, closes common "
                "dismissible overlays, scrolls incrementally to load lazy content, and defaults "
                "to the last BrowserOpen page in the conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional HTTP or HTTPS URL."},
                    "page_id": {
                        "type": "string",
                        "description": "Optional page_id returned by BrowserOpen. Defaults to the last BrowserOpen page.",
                    },
                    "window_id": {
                        "type": "string",
                        "description": "Optional window_id returned by BrowserOpen or BrowserListTabs. Alias of page_id.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200000,
                        "default": 20000,
                    },
                    "include_links": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser extract content markdown lightpanda page",
            max_result_size_chars=24_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda args: bool(
            str(args.get("url") or "").strip()
            or str(args.get("page_id") or "").strip()
            or str(args.get("window_id") or "").strip()
        ),
    )


def create_browser_read_content_chunk_tool() -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        cache_key = arguments.get("cache_key")
        if cache_key is not None and (not isinstance(cache_key, str) or not cache_key.strip()):
            return _deny("BrowserReadContentChunk cache_key must be a non-empty string.")
        if not _resolve_cache_key(context.conversation_id, cache_key):
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
        cache_key = _resolve_cache_key(context.conversation_id, arguments.get("cache_key"))
        if not cache_key:
            return _error(call, "BrowserReadContentChunk", "No cached browser page.")
        entry = _PAGE_CACHE.get(context.conversation_id, {}).get(cache_key)
        if not entry:
            return _error(call, "BrowserReadContentChunk", f"No cached page for {cache_key}.")

        chunks = entry["chunks"]
        if not chunks:
            return _error(call, "BrowserReadContentChunk", f"No readable chunks for {cache_key}.")
        requested_index = int(arguments.get("chunk_index") or 1)
        requested_count = int(arguments.get("chunk_count") or 1)
        include_links = bool(arguments.get("include_links", False))
        start_index = min(max(1, int(arguments.get("chunk_index") or 1)), len(chunks))
        count = min(max(1, int(arguments.get("chunk_count") or 1)), _MAX_CHUNK_COUNT)
        selected = chunks[start_index - 1 : start_index - 1 + count]
        ranges = entry.get("chunk_ranges") if isinstance(entry.get("chunk_ranges"), list) else []
        links_summary = entry.get("links_summary", {})
        returned_links = entry.get("links", []) if include_links else []
        data = {
            "type": "browser_content_chunks",
            "cache_key": cache_key,
            "url": entry["url"],
            "title": entry["title"],
            "page_id": entry.get("page_id"),
            "window_id": entry.get("page_id"),
            "content_chars": entry.get("content_chars", 0),
            "chunk_size": entry.get("chunk_size", _DEFAULT_CHUNK_SIZE),
            "requested_chunk_index": requested_index,
            "requested_chunk_count": requested_count,
            "chunk_index": start_index,
            "chunk_count": len(selected),
            "total_chunks": len(chunks),
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
            "buttons": entry.get("buttons", []),
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


def create_browser_get_html_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_error = _validate_page_or_window_id(
            page_id,
            window_id,
            tool_name="BrowserGetHtml",
        )
        if target_error is not None:
            return target_error
        target_id = _coerce_page_or_window_id(page_id, window_id)
        if isinstance(url, str) and url.strip() and target_id:
            return _deny("BrowserGetHtml requires either 'url' or 'page_id/window_id', not both.")
        if isinstance(url, str) and url.strip():
            validation = validate_web_url(url, context)
            if validation is not None:
                return validation
        max_chars = arguments.get("max_chars", context.limits.get("result_max_chars", 20_000))
        if not _is_int(max_chars) or int(max_chars) < 1 or int(max_chars) > 500_000:
            return _deny("BrowserGetHtml max_chars must be between 1 and 500000.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_id = _coerce_page_or_window_id(page_id, window_id)
        max_chars = int(
            arguments.get("max_chars") or context.limits.get("result_max_chars", 20_000)
        )
        await _progress(
            context,
            call,
            "Reading raw page HTML with LightPanda...",
            {"url": url, "page_id": page_id, "window_id": window_id},
        )
        try:
            data = await worker.get_html(
                conversation_id=context.conversation_id,
                url=str(url).strip() if isinstance(url, str) and url.strip() else None,
                page_id=target_id,
                max_chars=max_chars,
            )
        except Exception as exc:
            return _error(call, "BrowserGetHtml", str(exc), exc)
        return _json_result(call, "BrowserGetHtml", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserGetHtml",
            description=(
                "Return raw HTML from a provided URL/page_id or, by default, the last "
                "BrowserOpen page in the conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional HTTP or HTTPS URL."},
                    "page_id": {
                        "type": "string",
                        "description": "Optional page_id returned by BrowserOpen. Defaults to the last BrowserOpen page.",
                    },
                    "window_id": {
                        "type": "string",
                        "description": "Optional window_id returned by BrowserOpen or BrowserListTabs. Alias of page_id.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500000,
                        "default": 20000,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser html raw lightpanda page source",
            max_result_size_chars=80_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda args: bool(
            str(args.get("url") or "").strip()
            or str(args.get("page_id") or "").strip()
            or str(args.get("window_id") or "").strip()
        ),
    )


def create_browser_get_element_map_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        width = arguments.get("width", 1024)
        height = arguments.get("height", 720)
        if not _is_int(width) or int(width) < 320 or int(width) > 2400:
            return _deny("BrowserGetElementMap width must be between 320 and 2400.")
        if not _is_int(height) or int(height) < 240 or int(height) > 1800:
            return _deny("BrowserGetElementMap height must be between 240 and 1800.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        width = min(max(320, int(arguments.get("width") or 1024)), 2400)
        height = min(max(240, int(arguments.get("height") or 720)), 1800)
        await _progress(context, call, "Mapping browser elements...", {"width": width, "height": height})
        try:
            view = await worker.view_snapshot(
                browser_id=context.conversation_id,
                width=width,
                height=height,
            )
        except Exception as exc:
            return _error(call, "BrowserGetElementMap", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_element_map",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "css_fidelity": view.get("css_fidelity") or "",
            "element_count": len(elements),
            "elements": elements,
        }
        return _json_result(call, "BrowserGetElementMap", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserGetElementMap",
            description=(
                "Return the current browser page's mapped links, buttons, inputs, forms, and "
                "important content blocks. Use node_id values with BrowserAct."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
                    "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser element map node_id ui automation",
            max_result_size_chars=24_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=30_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_act_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        node_id = arguments.get("node_id")
        action = arguments.get("action")
        if not isinstance(node_id, str) or not node_id.strip():
            return _deny("BrowserAct requires a non-empty node_id.")
        if action not in {"click", "fill", "submit", "select", "press"}:
            return _deny("BrowserAct action must be click, fill, submit, select, or press.")
        if action in {"fill", "select"} and not isinstance(arguments.get("value"), str):
            return _deny("BrowserAct fill/select requires a string value.")
        if action == "press" and not isinstance(arguments.get("key", arguments.get("value", "")), str):
            return _deny("BrowserAct press requires key or value.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        node_id = str(arguments["node_id"]).strip()
        action = str(arguments["action"]).strip()
        width = min(max(320, int(arguments.get("width") or 1024)), 2400)
        height = min(max(240, int(arguments.get("height") or 720)), 1800)
        value = arguments.get("value") if isinstance(arguments.get("value"), str) else None
        key = arguments.get("key") if isinstance(arguments.get("key"), str) else None
        await _progress(
            context,
            call,
            f"Running browser action {action}...",
            {"node_id": node_id, "action": action},
        )
        try:
            view = await worker.view_act(
                browser_id=context.conversation_id,
                node_id=node_id,
                action=action,
                value=value,
                key=key,
                width=width,
                height=height,
            )
        except Exception as exc:
            return _error(call, "BrowserAct", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_action",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "node_id": node_id,
            "action": action,
            "last_action": view.get("last_action") or {},
            "element_count": len(elements),
            "elements": elements[:60],
        }
        return _json_result(call, "BrowserAct", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserAct",
            description=(
                "Execute an action on the current browser page using a node_id from BrowserGetElementMap. "
                "Supports click, fill, submit, select, and press."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "Element node_id from BrowserGetElementMap."},
                    "action": {
                        "type": "string",
                        "enum": ["click", "fill", "submit", "select", "press"],
                    },
                    "value": {"type": "string", "description": "Text/value for fill, select, or press."},
                    "key": {"type": "string", "description": "Keyboard key for press."},
                    "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
                    "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
                },
                "required": ["node_id", "action"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser act click fill submit select press automation node_id",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


async def _progress(
    context: ToolUseContext,
    call: ToolCall,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    await context.emit_progress(
        ToolProgress(
            tool_call_id=call.id,
            tool_name=call.name,
            status=ToolExecutionStatus.RUNNING,
            message=message,
            data=data or {},
        )
    )


def _json_result(call: ToolCall, tool_name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.COMPLETED,
        data=data,
    )


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


def _summarize_element_map(raw_map: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    if not isinstance(raw_map, list):
        return elements
    for item in raw_map:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        elements.append(
            {
                "node_id": node_id,
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": " ".join(str(item.get("text") or "").split())[:180],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "form_action": str(item.get("form_action") or ""),
                "input_type": str(item.get("input_type") or ""),
            }
        )
        if len(elements) >= 120:
            break
    return elements


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
    entry = {
        "url": url,
        "title": title,
        "page_id": _coerce_page_or_window_id(data.get("page_id"), data.get("window_id")),
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunks": chunks,
        "chunk_ranges": ranges,
        "links": links,
        "links_summary": links_summary,
        "buttons": data.get("buttons") if isinstance(data.get("buttons"), list) else [],
    }
    _PAGE_CACHE.setdefault(conversation_id, {})[cache_key] = entry
    _LATEST_CACHE_KEY[conversation_id] = cache_key
    return {
        "cache_key": cache_key,
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunk_count": len(chunks),
        "page_id": entry.get("page_id"),
        "window_id": entry.get("page_id"),
        "links": entry["links"],
        "links_summary": entry["links_summary"],
        "buttons": entry["buttons"],
    }


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


def _extract_markdown_links(content: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in _MARKDOWN_LINK_PATTERN.finditer(content):
        links.append({"text": " ".join(match.group(1).split()), "url": match.group(2).strip()})
    return links


def _coerce_links(raw_links: Any) -> list[dict[str, str]]:
    if not isinstance(raw_links, list):
        return []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_links:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "text": " ".join(str(item.get("text") or "").split())})
    return links


def _curate_links(
    raw_links: list[dict[str, str]],
    *,
    content: str,
    source_url: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    unique_links = _coerce_links(raw_links)
    low_quality = [link for link in unique_links if _is_low_quality_link(link, source_url)]
    suppress = False
    reason = ""
    if len(unique_links) >= _LINK_SUPPRESSION_THRESHOLD:
        low_quality_ratio = len(low_quality) / max(1, len(unique_links))
        markdown_link_count = len(_MARKDOWN_LINK_PATTERN.findall(content))
        if low_quality_ratio >= 0.55 or markdown_link_count >= _LINK_SUPPRESSION_THRESHOLD:
            suppress = True
            reason = "link_dense_navigation_or_low_quality_links"
    returned = [] if suppress else unique_links[:_MAX_RETURNED_LINKS]
    return returned, {
        "total": len(unique_links),
        "returned": len(returned),
        "suppressed": suppress,
        "reason": reason,
        "max_returned": _MAX_RETURNED_LINKS,
    }


def _is_low_quality_link(link: dict[str, str], source_url: str) -> bool:
    url = str(link.get("url") or "")
    text = " ".join(str(link.get("text") or "").lower().split())
    parsed = urlparse(url)
    source = urlparse(source_url)
    path = parsed.path.lower()
    if not text or text in _LOW_QUALITY_LINK_TEXT:
        return True
    if any(marker in path for marker in _LOW_QUALITY_PATH_MARKERS):
        return True
    if parsed.netloc == source.netloc and path in {"", "/"}:
        return True
    return len(text) <= 3 and not any(char.isdigit() for char in text)


def _resolve_cache_key(conversation_id: str, raw_cache_key: Any) -> str | None:
    if isinstance(raw_cache_key, str) and raw_cache_key.strip():
        return raw_cache_key.strip()
    return _LATEST_CACHE_KEY.get(conversation_id)


def _normalize_browser_open_arguments(arguments: ToolArguments) -> dict[str, Any]:
    """Recover common model argument variants while preserving canonical behavior."""

    url, url_key = _first_non_empty_string_with_key(arguments, _BROWSER_OPEN_URL_KEYS)
    search_id, search_id_key, invalid_search_id = _first_string_with_key(
        arguments,
        _BROWSER_OPEN_SEARCH_ID_KEYS,
    )
    raw_result_index, index_key = _first_present_with_key(
        arguments,
        _BROWSER_OPEN_DIRECT_INDEX_KEYS,
    )
    recovered_from: list[str] = []
    raw_result = arguments.get("result")

    if isinstance(raw_result, Mapping):
        if not url:
            url, url_key = _first_non_empty_string_with_key(raw_result, _BROWSER_OPEN_URL_KEYS)
        if not search_id and not invalid_search_id:
            search_id, search_id_key, invalid_search_id = _first_string_with_key(
                raw_result,
                _BROWSER_OPEN_SEARCH_ID_KEYS,
            )
        if raw_result_index is None:
            raw_result_index, index_key = _first_present_with_key(
                raw_result,
                _BROWSER_OPEN_INDEX_KEYS,
            )
    elif raw_result is not None and raw_result_index is None:
        raw_result_index = raw_result
        index_key = "result"

    if isinstance(raw_result, str) and raw_result.strip().startswith(("http://", "https://")):
        if not url:
            url = raw_result.strip()
            url_key = "result"
        if index_key == "result":
            raw_result_index = None
            index_key = ""

    result_index = int(raw_result_index) if _is_int(raw_result_index) else None
    invalid_result_index = raw_result_index is not None and result_index is None
    if url_key and url_key != "url":
        recovered_from.append(url_key)
    if index_key and index_key != "result_index":
        recovered_from.append(index_key)
    if search_id_key and search_id_key != "search_id":
        recovered_from.append(search_id_key)
    if search_id and result_index is None and not url:
        recovered_from.append("search_id_only_default_result_1")

    return {
        "url": url,
        "result_index": result_index,
        "search_id": search_id,
        "invalid_result_index": invalid_result_index,
        "invalid_search_id": invalid_search_id,
        "recovered_from": sorted(set(recovered_from)),
    }


def _first_present_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[Any | None, str]:
    for key in keys:
        if key in values:
            return values[key], key
    return None, ""


def _first_non_empty_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str]:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    return None, ""


def _first_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str, bool]:
    for key in keys:
        if key not in values:
            continue
        value = values[key]
        if value is None:
            continue
        if not isinstance(value, str):
            return None, key, True
        if value.strip():
            return value.strip(), key, False
    return None, "", False


def _coerce_page_or_window_id(page_id: Any, window_id: Any) -> str | None:
    if isinstance(page_id, str) and page_id.strip():
        return page_id.strip()
    if isinstance(window_id, str) and window_id.strip():
        return window_id.strip()
    return None


def _validate_page_or_window_id(
    page_id: Any,
    window_id: Any,
    *,
    tool_name: str,
) -> ToolPermissionResult | None:
    if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
        return _deny(f"{tool_name} page_id must be a non-empty string.")
    if window_id is not None and (not isinstance(window_id, str) or not window_id.strip()):
        return _deny(f"{tool_name} window_id must be a non-empty string.")
    if (
        isinstance(page_id, str)
        and page_id.strip()
        and isinstance(window_id, str)
        and window_id.strip()
        and page_id.strip() != window_id.strip()
    ):
        return _deny(f"{tool_name} requires either page_id or window_id, not both.")
    return None


def _error(
    call: ToolCall,
    tool_name: str,
    message: str,
    exc: Exception | None = None,
) -> ToolResult:
    data = {"type": _error_type(tool_name), "error": message}
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        data["details"] = {key: value for key, value in details.items() if value}
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data,
    )


def _error_type(tool_name: str) -> str:
    return {
        "BrowserSearch": "browser_search",
        "BrowserOpen": "browser_open",
        "BrowserListTabs": "browser_tabs",
        "BrowserExtractContent": "browser_extract_content",
        "BrowserReadContentChunk": "browser_content_chunks",
        "BrowserGetHtml": "browser_get_html",
        "BrowserGetElementMap": "browser_element_map",
        "BrowserAct": "browser_action",
    }.get(tool_name, "browser")


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float) and not value.is_integer():
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True
