"""LightPanda browser tools for the main chat agent."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

from personagent.application.services.browser_action_arbiter import BrowserActionArbiter
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
from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.tools.web_tools import validate_web_url

_BROWSER_ACTION_ARBITER = BrowserActionArbiter()


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
        create_browser_click_tool(worker),
        create_browser_type_tool(worker),
        create_browser_screenshot_tool(worker),
        create_browser_close_tab_tool(worker),
        create_browser_read_console_tool(worker),
        create_browser_script_tool(worker),
        create_browser_scroll_tool(worker),
        create_browser_reload_tool(worker),
        create_browser_history_tool(worker),
        create_browser_switch_tab_tool(worker),
        create_browser_wait_tool(worker),
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
_PAGE_CACHE = get_browser_page_cache()
_BROWSER_EXTRACT_IN_FLIGHT: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
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
_BROWSER_ACTIONS = {
    "click",
    "fill",
    "submit",
    "select",
    "press",
    "hover",
    "wait",
    "drag",
    "drop",
    "upload",
    "select_text",
    "scroll_to",
    "screenshot",
}
_BROWSER_CONTROL_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}
_BROWSER_CONSOLE_LEVELS = {"debug", "error", "info", "log", "warning", "warn"}


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
                conversation_id=_browser_session_id(context),
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
        browser_id = _browser_session_id(context)
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
                "browser_id": browser_id,
                "url": target_url,
                "result_index": target_result_index,
                "search_id": target_search_id,
                "recovered_from": target["recovered_from"],
            },
        )
        try:
            data = await worker.open(
                conversation_id=browser_id,
                url=target_url,
                result_index=target_result_index,
                search_id=target_search_id,
                tool_call_id=call.id,
            )
            data = dict(data)
            data.setdefault("browser_id", browser_id)
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
                "later extraction. Reuses an already-open logical page for the same URL when "
                "possible, and returns already_read/read_status so duplicate reads can be avoided. "
                "If url and result_index are both provided, url wins."
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
            browser_id = _browser_session_id(context)
            data = await worker.list_tabs(
                conversation_id=browser_id,
                max_tabs=max_tabs,
            )
            data = _merge_shared_browser_workspace_tabs(
                data,
                context,
                browser_id=browser_id,
                max_tabs=max_tabs,
            )
        except Exception as exc:
            return _error(call, "BrowserListTabs", str(exc), exc)
        return _json_result(call, "BrowserListTabs", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserListTabs",
            description=(
                "List browser tabs/pages from the shared Browser panel and BrowserOpen state for "
                "the current chat conversation. Use this to recover browser_id/page_id values and "
                "keep browser work consistent with the visible panel. Each tab includes "
                "already_read/read_status/extraction_count; do not extract a tab again unless "
                "force_refresh is explicitly needed."
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
        max_chars = arguments.get("max_chars", _browser_result_max_chars(context))
        if not _is_int(max_chars) or int(max_chars) < 1:
            return _deny("BrowserExtractContent max_chars must be positive.")
        include_links = arguments.get("include_links", False)
        if not isinstance(include_links, bool):
            return _deny("BrowserExtractContent include_links must be a boolean.")
        force_refresh = arguments.get("force_refresh", False)
        if not isinstance(force_refresh, bool):
            return _deny("BrowserExtractContent force_refresh must be a boolean.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserExtractContent",
            block_url_argument=True,
        )
        if target_error:
            return _target_error_result(call, "BrowserExtractContent", target_error)
        browser_id = _browser_session_id(context)
        explicit_url = str(url).strip() if isinstance(url, str) and url.strip() else None
        explicit_target_id = _coerce_page_or_window_id(page_id, window_id) or _browser_target_page_id(
            _browser_target(context)
        )
        workspace_content_url = (
            _browser_workspace_current_url(context)
            if not explicit_url and not explicit_target_id
            else None
        )
        max_chars = int(arguments.get("max_chars") or _browser_result_max_chars(context))
        include_links = bool(arguments.get("include_links", False))
        force_refresh = bool(arguments.get("force_refresh", False))
        cached = None if force_refresh or not target_id else _PAGE_CACHE.latest_for_page(browser_id, target_id)
        if cached is not None:
            data = _cached_extracted_content_response(
                cached,
                max_chars=max_chars,
                include_links=include_links,
            )
            data.setdefault("browser_id", browser_id)
            return _json_result(call, "BrowserExtractContent", data)
        await _progress(
            context,
            call,
            "Extracting page content with LightPanda...",
            {"browser_id": browser_id, "url": url, "page_id": page_id, "window_id": window_id},
        )
        try:
            read_url = explicit_url if explicit_url and not target_id else workspace_content_url
            read_page_id = None if workspace_content_url else target_id
            data, duplicate_read_avoided = await _run_deduped_browser_extract(
                browser_id,
                read_page_id or read_url or "",
                lambda: worker.extract_content(
                    conversation_id=browser_id,
                    url=read_url,
                    page_id=read_page_id,
                    max_chars=max_chars,
                    include_links=include_links,
                ),
            )
        except Exception as exc:
            return _error(call, "BrowserExtractContent", str(exc), exc)
        data = dict(data)
        data.setdefault("browser_id", browser_id)
        data = _prepare_extracted_content_response(
            conversation_id=browser_id,
            data=data,
            include_links=include_links,
        )
        data.setdefault("already_read", False)
        data.setdefault("read_status", "read")
        data["duplicate_read_avoided"] = bool(duplicate_read_avoided or data.get("duplicate_read_avoided"))
        return _json_result(call, "BrowserExtractContent", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserExtractContent",
            description=(
                "Return organized markdown/text content from the current LightPanda page or "
                "from a provided URL/page_id. The tool prepares the rendered page, closes common "
                "dismissible overlays, scrolls incrementally to load lazy content, and defaults "
                "to the next unread BrowserOpen page in the conversation. It returns cached "
                "content for an already-read page_id unless force_refresh=true."
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
                        "default": 60000,
                    },
                    "include_links": {"type": "boolean", "default": False},
                    "force_refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Set true only when the page must be re-read even if this page_id already has cached content.",
                    },
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
        max_chars = arguments.get("max_chars", _browser_result_max_chars(context))
        if not _is_int(max_chars) or int(max_chars) < 1:
            return _deny("BrowserGetHtml max_chars must be positive.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = arguments.get("url")
        page_id = arguments.get("page_id")
        window_id = arguments.get("window_id")
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserGetHtml",
            block_url_argument=True,
        )
        if target_error:
            return _target_error_result(call, "BrowserGetHtml", target_error)
        browser_id = _browser_session_id(context)
        explicit_url = str(url).strip() if isinstance(url, str) and url.strip() else None
        explicit_target_id = _coerce_page_or_window_id(page_id, window_id) or _browser_target_page_id(
            _browser_target(context)
        )
        workspace_content_url = (
            _browser_workspace_current_url(context)
            if not explicit_url and not explicit_target_id
            else None
        )
        max_chars = int(arguments.get("max_chars") or _browser_result_max_chars(context))
        await _progress(
            context,
            call,
            "Reading raw page HTML with LightPanda...",
            {"browser_id": browser_id, "url": url, "page_id": page_id, "window_id": window_id},
        )
        try:
            data = await worker.get_html(
                conversation_id=browser_id,
                url=explicit_url if explicit_url and not target_id else workspace_content_url,
                page_id=None if workspace_content_url else target_id,
                max_chars=max_chars,
            )
        except Exception as exc:
            return _error(call, "BrowserGetHtml", str(exc), exc)
        data = dict(data)
        data.setdefault("browser_id", browser_id)
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
                        "default": 10000000,
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
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserGetElementMap",
        )
        if target_error is not None:
            return target_error
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
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserGetElementMap",
        )
        if target_error:
            return _target_error_result(call, "BrowserGetElementMap", target_error)
        browser_id = _browser_session_id(context)
        await _progress(
            context,
            call,
            "Mapping browser elements...",
            {"browser_id": browser_id, "page_id": target_id, "width": width, "height": height},
        )
        try:
            if target_id:
                await worker.switch_tab(
                    conversation_id=browser_id,
                    page_id=target_id,
                    max_tabs=20,
                )
            view = await worker.view_snapshot(
                browser_id=browser_id,
                width=width,
                height=height,
            )
            workspace_url = _browser_workspace_current_url(context)
            if _browser_view_is_about_blank(view) and workspace_url:
                view = await worker.view_navigate(
                    browser_id=browser_id,
                    url=workspace_url,
                    width=width,
                    height=height,
                    cache_mode="prefer_live",
                    wait_for_styles=True,
                )
        except Exception as exc:
            return _error(call, "BrowserGetElementMap", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_element_map",
            "browser_id": view.get("browser_id") or browser_id,
            "page_id": target_id or view.get("active_tab_id") or "",
            "window_id": target_id or view.get("active_tab_id") or "",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "runtime": view.get("runtime") or "",
            "render_mode": view.get("render_mode") or "",
            "css_fidelity": view.get("css_fidelity") or "",
            "tabs": view.get("tabs") or [],
            "active_tab_id": view.get("active_tab_id") or "",
            "element_count": len(elements),
            "elements": elements,
        }
        return _json_result(call, "BrowserGetElementMap", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserGetElementMap",
            description=(
                "Return the current browser page's mapped links, buttons, inputs, forms, and "
                "important content blocks. Use node_id values with BrowserClick, BrowserType, "
                "or BrowserAct for advanced compatibility actions."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
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


def create_browser_click_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserClick",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        x = arguments.get("x")
        y = arguments.get("y")
        if node_id is not None and (not isinstance(node_id, str) or not node_id.strip()):
            return _deny("BrowserClick node_id must be a non-empty string.")
        if not (isinstance(node_id, str) and node_id.strip()) and (
            not isinstance(x, int | float) or not isinstance(y, int | float)
        ):
            return _deny("BrowserClick requires node_id or numeric x/y coordinates.")
        size_error = _validate_browser_dimensions(arguments, "BrowserClick")
        if size_error is not None:
            return size_error
        button = arguments.get("button", "left")
        if button not in {"left", "middle", "right"}:
            return _deny("BrowserClick button must be left, middle, or right.")
        click_count = arguments.get("click_count", 1)
        if not _is_int(click_count) or int(click_count) < 1 or int(click_count) > 3:
            return _deny("BrowserClick click_count must be between 1 and 3.")
        modifiers = arguments.get("modifiers", [])
        if not isinstance(modifiers, list) or not all(isinstance(item, str) and item.strip() for item in modifiers):
            return _deny("BrowserClick modifiers must be an array of strings.")
        wait_after_ms = arguments.get("wait_after_ms", 250)
        if not _is_int(wait_after_ms) or int(wait_after_ms) < 0 or int(wait_after_ms) > 10_000:
            return _deny("BrowserClick wait_after_ms must be between 0 and 10000.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserClick",
        )
        if target_error:
            return _target_error_result(call, "BrowserClick", target_error)
        browser_id = _browser_session_id(context)
        node_id = str(arguments.get("node_id") or "").strip() or None
        await _progress(
            context,
            call,
            "Clicking browser page...",
            {"browser_id": browser_id, "page_id": target_id, "node_id": node_id, "x": arguments.get("x"), "y": arguments.get("y")},
        )
        try:
            data = await worker.click(
                conversation_id=browser_id,
                page_id=target_id,
                node_id=node_id,
                x=float(arguments["x"]) if isinstance(arguments.get("x"), int | float) else None,
                y=float(arguments["y"]) if isinstance(arguments.get("y"), int | float) else None,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
                button=str(arguments.get("button") or "left"),
                click_count=int(arguments.get("click_count") or 1),
                modifiers=[str(item) for item in arguments.get("modifiers", [])],
                wait_after_ms=int(arguments.get("wait_after_ms") or 250),
            )
        except Exception as exc:
            return _error(call, "BrowserClick", str(exc), exc)
        return _json_result(call, "BrowserClick", _prepare_browser_control_response(data))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserClick",
            description="Click a browser element by node_id from BrowserGetElementMap, or by viewport x/y coordinates.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "button": {"type": "string", "enum": ["left", "middle", "right"], "default": "left"},
                    "click_count": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                    "modifiers": {"type": "array", "items": {"type": "string"}, "default": []},
                    "wait_after_ms": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 250},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser click element node_id coordinate automation",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserClick", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_type_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserType",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        if node_id is not None and (not isinstance(node_id, str) or not node_id.strip()):
            return _deny("BrowserType node_id must be a non-empty string.")
        mode = arguments.get("mode", "type")
        if mode not in {"type", "fill", "press"}:
            return _deny("BrowserType mode must be type, fill, or press.")
        if mode in {"type", "fill"} and not isinstance(arguments.get("text"), str):
            return _deny("BrowserType type/fill requires text.")
        if mode == "press" and not isinstance(arguments.get("key", arguments.get("text")), str):
            return _deny("BrowserType press requires key or text.")
        if not isinstance(arguments.get("clear", False), bool):
            return _deny("BrowserType clear must be a boolean.")
        if not isinstance(arguments.get("submit", False), bool):
            return _deny("BrowserType submit must be a boolean.")
        delay_ms = arguments.get("delay_ms", 0)
        if not _is_int(delay_ms) or int(delay_ms) < 0 or int(delay_ms) > 1000:
            return _deny("BrowserType delay_ms must be between 0 and 1000.")
        return _validate_browser_dimensions(arguments, "BrowserType")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserType",
        )
        if target_error:
            return _target_error_result(call, "BrowserType", target_error)
        mode = str(arguments.get("mode") or "type")
        node_id = str(arguments.get("node_id") or "").strip() or None
        await _progress(context, call, f"Typing in browser ({mode})...", {"page_id": target_id, "node_id": node_id})
        try:
            data = await worker.type_input(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                node_id=node_id,
                mode=mode,
                text=arguments.get("text") if isinstance(arguments.get("text"), str) else None,
                key=arguments.get("key") if isinstance(arguments.get("key"), str) else None,
                clear=bool(arguments.get("clear", False)),
                delay_ms=int(arguments.get("delay_ms") or 0),
                submit=bool(arguments.get("submit", False)),
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserType", str(exc), exc)
        return _json_result(call, "BrowserType", _prepare_browser_control_response(data))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserType",
            description="Type, fill, or press a key in the browser, optionally targeting a node_id.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string"},
                    "mode": {"type": "string", "enum": ["type", "fill", "press"], "default": "type"},
                    "text": {"type": "string"},
                    "key": {"type": "string"},
                    "clear": {"type": "boolean", "default": False},
                    "delay_ms": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 0},
                    "submit": {"type": "boolean", "default": False},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser type fill press keyboard input node_id automation",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserType", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_screenshot_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScreenshot",
        )
        if target_error is not None:
            return target_error
        size_error = _validate_browser_dimensions(arguments, "BrowserScreenshot")
        if size_error is not None:
            return size_error
        if not isinstance(arguments.get("full_page", False), bool):
            return _deny("BrowserScreenshot full_page must be a boolean.")
        image_format = arguments.get("format", "png")
        if image_format not in {"png", "jpeg"}:
            return _deny("BrowserScreenshot format must be png or jpeg.")
        quality = arguments.get("quality")
        if quality is not None and (not _is_int(quality) or int(quality) < 1 or int(quality) > 100):
            return _deny("BrowserScreenshot quality must be between 1 and 100.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScreenshot",
        )
        if target_error:
            return _target_error_result(call, "BrowserScreenshot", target_error)
        await _progress(context, call, "Capturing browser screenshot...", {"page_id": target_id})
        try:
            data = await worker.screenshot(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
                full_page=bool(arguments.get("full_page", False)),
                image_format=str(arguments.get("format") or "png"),
                quality=int(arguments["quality"]) if _is_int(arguments.get("quality")) else None,
            )
        except Exception as exc:
            return _error(call, "BrowserScreenshot", str(exc), exc)
        return _json_result(call, "BrowserScreenshot", _prepare_browser_control_response(data, keep_image=True))

    return build_tool(
        definition=ToolDefinition(
            name="BrowserScreenshot",
            description="Capture pixels through Chrome/Chromium CDP, or return a LightPanda DOM-mirror fallback.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "full_page": {"type": "boolean", "default": False},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "quality": {"type": "integer", "minimum": 1, "maximum": 100},
                    **_viewport_schema(),
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser screenshot pixels image capture cdp lightpanda",
            max_result_size_chars=240_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_close_tab_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserCloseTab",
        )
        if target_error is not None:
            return target_error
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserCloseTab max_tabs must be between 1 and 50.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserCloseTab",
        )
        if target_error:
            return _target_error_result(call, "BrowserCloseTab", target_error)
        await _progress(context, call, "Closing browser tab...", {"page_id": target_id})
        try:
            browser_id = _browser_session_id(context)
            data = await worker.close_tab(
                conversation_id=browser_id,
                page_id=target_id,
                max_tabs=min(max(1, int(arguments.get("max_tabs") or 20)), 50),
            )
            closed_page_id = str(data.get("closed_page_id") or target_id or "").strip() or None
            _PAGE_CACHE.clear_conversation(browser_id, page_id=closed_page_id)
        except Exception as exc:
            return _error(call, "BrowserCloseTab", str(exc), exc)
        return _json_result(call, "BrowserCloseTab", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserCloseTab",
            description="Close a logical browser tab/page, clear its caches, and return the updated tab state.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "max_tabs": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser close tab page window cleanup",
            is_read_only=False,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserCloseTab", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_read_console_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserReadConsole",
        )
        if target_error is not None:
            return target_error
        levels = arguments.get("levels", [])
        if not isinstance(levels, list) or not all(isinstance(level, str) for level in levels):
            return _deny("BrowserReadConsole levels must be an array of strings.")
        invalid_levels = {level for level in levels if level.lower() not in _BROWSER_CONSOLE_LEVELS}
        if invalid_levels:
            return _deny("BrowserReadConsole levels may include debug, error, info, log, warn, or warning.")
        since_id = arguments.get("since_id")
        if since_id is not None and (not _is_int(since_id) or int(since_id) < 0):
            return _deny("BrowserReadConsole since_id must be a non-negative integer.")
        limit = arguments.get("limit", 100)
        if not _is_int(limit) or int(limit) < 1 or int(limit) > 200:
            return _deny("BrowserReadConsole limit must be between 1 and 200.")
        if not isinstance(arguments.get("clear", False), bool):
            return _deny("BrowserReadConsole clear must be a boolean.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserReadConsole",
        )
        if target_error:
            return _target_error_result(call, "BrowserReadConsole", target_error)
        await _progress(context, call, "Reading browser console...", {"page_id": target_id})
        try:
            data = await worker.read_console(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                levels=[str(level).lower() for level in arguments.get("levels", [])],
                since_id=int(arguments["since_id"]) if _is_int(arguments.get("since_id")) else None,
                limit=int(arguments.get("limit") or 100),
                clear=bool(arguments.get("clear", False)),
            )
        except Exception as exc:
            return _error(call, "BrowserReadConsole", str(exc), exc)
        return _json_result(call, "BrowserReadConsole", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserReadConsole",
            description="Read captured console logs, page errors, and CDP log entries for a browser page.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "levels": {"type": "array", "items": {"type": "string"}, "default": []},
                    "since_id": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
                    "clear": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser console logs pageerror debug error",
            max_result_size_chars=20_000,
            is_read_only=True,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda args: not bool(args.get("clear", False)),
        is_concurrency_safe=lambda args: not bool(args.get("clear", False)),
    )


def create_browser_script_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScript",
        )
        if target_error is not None:
            return target_error
        mode = arguments.get("mode", "evaluate")
        if mode not in {"evaluate", "cdp"}:
            return _deny("BrowserScript mode must be evaluate or cdp.")
        if mode == "evaluate":
            script = arguments.get("script")
            if not isinstance(script, str) or not script.strip():
                return _deny("BrowserScript evaluate requires a non-empty script.")
            if len(script) > 10_000:
                return _deny("BrowserScript script must be 10000 characters or fewer.")
        else:
            method = arguments.get("cdp_method")
            if method not in _BROWSER_CONTROL_CDP_ALLOWLIST:
                return _deny(
                    "BrowserScript cdp_method must be one of: "
                    + ", ".join(sorted(_BROWSER_CONTROL_CDP_ALLOWLIST))
                    + "."
                )
            cdp_params = arguments.get("cdp_params")
            if cdp_params is not None and not isinstance(cdp_params, dict):
                return _deny("BrowserScript cdp_params must be an object.")
            if isinstance(cdp_params, dict):
                if len(json.dumps(cdp_params, ensure_ascii=False, default=str)) > 10_000:
                    return _deny("BrowserScript cdp_params must be 10000 serialized characters or fewer.")
                expression = cdp_params.get("expression")
                if isinstance(expression, str) and len(expression) > 10_000:
                    return _deny("BrowserScript Runtime.evaluate expression must be 10000 characters or fewer.")
        timeout_ms = arguments.get("timeout_ms", 5000)
        if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 30_000:
            return _deny("BrowserScript timeout_ms must be between 1 and 30000.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScript",
        )
        if target_error:
            return _target_error_result(call, "BrowserScript", target_error)
        mode = str(arguments.get("mode") or "evaluate")
        await _progress(context, call, f"Running browser script ({mode})...", {"page_id": target_id})
        try:
            data = await worker.script(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                mode=mode,
                script=arguments.get("script") if isinstance(arguments.get("script"), str) else None,
                args=arguments.get("args"),
                cdp_method=arguments.get("cdp_method") if isinstance(arguments.get("cdp_method"), str) else None,
                cdp_params=arguments.get("cdp_params") if isinstance(arguments.get("cdp_params"), dict) else None,
                timeout_ms=int(arguments.get("timeout_ms") or 5000),
            )
        except Exception as exc:
            return _error(call, "BrowserScript", str(exc), exc)
        return _json_result(call, "BrowserScript", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserScript",
            description="Advanced allowlisted browser JS/CDP execution. Prefer explicit browser tools for normal actions.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "mode": {"type": "string", "enum": ["evaluate", "cdp"], "default": "evaluate"},
                    "script": {"type": "string"},
                    "args": {},
                    "cdp_method": {"type": "string", "enum": sorted(_BROWSER_CONTROL_CDP_ALLOWLIST)},
                    "cdp_params": {"type": "object", "additionalProperties": True},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 30000, "default": 5000},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser script javascript evaluate cdp runtime performance dom screenshot logs",
            max_result_size_chars=24_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=40_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserScript", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_scroll_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserScroll",
        )
        if target_error is not None:
            return target_error
        for key in ("delta_x", "delta_y"):
            if not isinstance(arguments.get(key, 0), int | float):
                return _deny(f"BrowserScroll {key} must be numeric.")
        return _validate_browser_dimensions(arguments, "BrowserScroll")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserScroll",
        )
        if target_error:
            return _target_error_result(call, "BrowserScroll", target_error)
        await _progress(context, call, "Scrolling browser page...", {"page_id": target_id})
        try:
            data = await worker.scroll(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                delta_x=float(arguments.get("delta_x", 0.0)),
                delta_y=float(arguments.get("delta_y", 600.0)),
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserScroll", str(exc), exc)
        return _json_result(call, "BrowserScroll", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserScroll",
        description="Scroll the active or selected browser page.",
        schema_properties={
            **_page_target_schema(),
            "delta_x": {"type": "number", "default": 0},
            "delta_y": {"type": "number", "default": 600},
            **_viewport_schema(),
        },
        search_hint="browser scroll page viewport automation",
        handler=handler,
        validate=validate,
    )


def create_browser_reload_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserReload",
        )
        return target_error or _validate_browser_dimensions(arguments, "BrowserReload")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserReload",
        )
        if target_error:
            return _target_error_result(call, "BrowserReload", target_error)
        await _progress(context, call, "Reloading browser page...", {"page_id": target_id})
        try:
            data = await worker.reload(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserReload", str(exc), exc)
        return _json_result(call, "BrowserReload", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserReload",
        description="Reload the active or selected browser page.",
        schema_properties={**_page_target_schema(), **_viewport_schema()},
        search_hint="browser reload refresh page",
        handler=handler,
        validate=validate,
    )


def create_browser_history_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserHistory",
        )
        if target_error is not None:
            return target_error
        direction = arguments.get("direction", "back")
        if direction not in {"back", "forward"}:
            return _deny("BrowserHistory direction must be back or forward.")
        return _validate_browser_dimensions(arguments, "BrowserHistory")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserHistory",
        )
        if target_error:
            return _target_error_result(call, "BrowserHistory", target_error)
        direction = -1 if arguments.get("direction", "back") == "back" else 1
        await _progress(context, call, "Navigating browser history...", {"page_id": target_id, "direction": direction})
        try:
            data = await worker.history(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                direction=direction,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserHistory", str(exc), exc)
        return _json_result(call, "BrowserHistory", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserHistory",
        description="Move the selected browser page backward or forward in history.",
        schema_properties={
            **_page_target_schema(),
            "direction": {"type": "string", "enum": ["back", "forward"], "default": "back"},
            **_viewport_schema(),
        },
        search_hint="browser history back forward navigation",
        handler=handler,
        validate=validate,
    )


def create_browser_switch_tab_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserSwitchTab",
        )
        if target_error is not None:
            return target_error
        if not _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id")) and not _browser_target_page_id(_browser_target(context)):
            return _deny("BrowserSwitchTab requires page_id or window_id.")
        max_tabs = arguments.get("max_tabs", 20)
        if not _is_int(max_tabs) or int(max_tabs) < 1 or int(max_tabs) > 50:
            return _deny("BrowserSwitchTab max_tabs must be between 1 and 50.")
        return None

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserSwitchTab",
        )
        if target_error:
            return _target_error_result(call, "BrowserSwitchTab", target_error)
        await _progress(context, call, "Switching browser tab...", {"page_id": target_id})
        try:
            data = await worker.switch_tab(
                conversation_id=_browser_session_id(context),
                page_id=str(target_id),
                max_tabs=min(max(1, int(arguments.get("max_tabs") or 20)), 50),
            )
        except Exception as exc:
            return _error(call, "BrowserSwitchTab", str(exc), exc)
        return _json_result(call, "BrowserSwitchTab", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserSwitchTab",
            description="Activate a logical browser tab by page_id/window_id and return the updated tab state.",
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "max_tabs": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser switch tab activate page window",
            is_read_only=False,
            is_open_world=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserSwitchTab", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_wait_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserWait",
        )
        if target_error is not None:
            return target_error
        timeout_ms = arguments.get("timeout_ms", 1000)
        if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 120_000:
            return _deny("BrowserWait timeout_ms must be between 1 and 120000.")
        state = arguments.get("state")
        if state is not None and state not in {"load", "domcontentloaded", "networkidle"}:
            return _deny("BrowserWait state must be load, domcontentloaded, or networkidle.")
        return _validate_browser_dimensions(arguments, "BrowserWait")

    async def handler(arguments: ToolArguments, context: ToolUseContext, call: ToolCall) -> ToolResult:
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserWait",
        )
        if target_error:
            return _target_error_result(call, "BrowserWait", target_error)
        await _progress(context, call, "Waiting for browser page...", {"page_id": target_id})
        try:
            data = await worker.wait(
                conversation_id=_browser_session_id(context),
                page_id=target_id,
                timeout_ms=int(arguments.get("timeout_ms") or 1000),
                state=arguments.get("state") if isinstance(arguments.get("state"), str) else None,
                width=_browser_width(arguments),
                height=_browser_height(arguments),
            )
        except Exception as exc:
            return _error(call, "BrowserWait", str(exc), exc)
        return _json_result(call, "BrowserWait", _prepare_browser_control_response(data))

    return _simple_browser_control_tool(
        name="BrowserWait",
        description="Wait for time or a load state on the active or selected browser page.",
        schema_properties={
            **_page_target_schema(),
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 120000, "default": 1000},
            "state": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"]},
            **_viewport_schema(),
        },
        search_hint="browser wait load state timeout",
        handler=handler,
        validate=validate,
    )


def create_browser_act_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        target_error = _validate_page_or_window_id(
            arguments.get("page_id"),
            arguments.get("window_id"),
            tool_name="BrowserAct",
        )
        if target_error is not None:
            return target_error
        node_id = arguments.get("node_id")
        action = arguments.get("action")
        if not isinstance(node_id, str) or not node_id.strip():
            return _deny("BrowserAct requires a non-empty node_id.")
        if action not in _BROWSER_ACTIONS:
            return _deny(f"BrowserAct action must be one of: {', '.join(sorted(_BROWSER_ACTIONS))}.")
        if action in {"fill", "select"} and not isinstance(arguments.get("value"), str):
            return _deny("BrowserAct fill/select requires a string value.")
        if action == "press" and not isinstance(arguments.get("key", arguments.get("value", "")), str):
            return _deny("BrowserAct press requires key or value.")
        if action == "upload":
            files = arguments.get("files")
            if not isinstance(files, list) or not all(isinstance(item, str) and item.strip() for item in files):
                return _deny("BrowserAct upload requires a non-empty files array.")
        if action == "wait":
            timeout_ms = arguments.get("timeout_ms", arguments.get("value", 1000))
            if not _is_int(timeout_ms) or int(timeout_ms) < 1 or int(timeout_ms) > 120_000:
                return _deny("BrowserAct wait timeout_ms must be between 1 and 120000.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        node_id = str(arguments["node_id"]).strip()
        action = str(arguments["action"]).strip()
        target_id, target_error = _resolve_browser_page_target(
            arguments,
            context,
            tool_name="BrowserAct",
        )
        if target_error:
            return _target_error_result(call, "BrowserAct", target_error)
        width = min(max(320, int(arguments.get("width") or 1024)), 2400)
        height = min(max(240, int(arguments.get("height") or 720)), 1800)
        value = arguments.get("value") if isinstance(arguments.get("value"), str) else None
        key = arguments.get("key") if isinstance(arguments.get("key"), str) else None
        target_node_id = arguments.get("target_node_id") if isinstance(arguments.get("target_node_id"), str) else None
        timeout_ms = int(arguments["timeout_ms"]) if _is_int(arguments.get("timeout_ms")) else None
        files = [str(item) for item in arguments.get("files", [])] if isinstance(arguments.get("files"), list) else None
        text = arguments.get("text") if isinstance(arguments.get("text"), str) else None
        x = float(arguments["x"]) if isinstance(arguments.get("x"), int | float) else None
        y = float(arguments["y"]) if isinstance(arguments.get("y"), int | float) else None
        await _progress(
            context,
            call,
            f"Running browser action {action}...",
            {"page_id": target_id, "node_id": node_id, "action": action},
        )
        try:
            if target_id:
                await worker.switch_tab(
                    conversation_id=_browser_session_id(context),
                    page_id=target_id,
                    max_tabs=20,
                )
            base_kwargs = {
                "browser_id": _browser_session_id(context),
                "node_id": node_id,
                "action": action,
                "value": value,
                "key": key,
                "width": width,
                "height": height,
            }
            extra_kwargs = {
                "target_node_id": target_node_id,
                "timeout_ms": timeout_ms,
                "files": files,
                "text": text,
                "x": x,
                "y": y,
            }
            compact_extra_kwargs = {key: next_value for key, next_value in extra_kwargs.items() if next_value is not None}
            try:
                view = await worker.view_act(**base_kwargs, **compact_extra_kwargs)
            except TypeError:
                if compact_extra_kwargs:
                    view = await worker.view_act(**base_kwargs)
                else:
                    raise
        except Exception as exc:
            return _error(call, "BrowserAct", str(exc), exc)
        elements = _summarize_element_map(view.get("element_map"))
        data = {
            "type": "browser_action",
            "url": view.get("url") or "",
            "title": view.get("title") or "",
            "runtime": view.get("runtime") or "",
            "render_mode": view.get("render_mode") or "",
            "css_fidelity": view.get("css_fidelity") or "",
            "active_tab_id": view.get("active_tab_id") or "",
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
                "Advanced compatibility tool for mapped browser actions. Prefer BrowserClick, BrowserType, "
                "BrowserScroll, BrowserWait, and other explicit browser tools for normal automation. "
                "Supports click, fill, submit, select, press, hover, wait, drag/drop, upload, "
                "select_text, scroll_to, and screenshot."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **_page_target_schema(),
                    "node_id": {"type": "string", "description": "Element node_id from BrowserGetElementMap."},
                    "action": {
                        "type": "string",
                        "enum": sorted(_BROWSER_ACTIONS),
                    },
                    "value": {"type": "string", "description": "Text/value for fill, select, or press."},
                    "key": {"type": "string", "description": "Keyboard key for press."},
                    "target_node_id": {"type": "string", "description": "Drop target node_id for drag/drop."},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 120000, "description": "Wait timeout."},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Local file paths for upload actions.",
                    },
                    "text": {"type": "string", "description": "Optional text payload for select_text."},
                    "x": {"type": "number", "description": "Viewport x coordinate for drag/drop fallback."},
                    "y": {"type": "number", "description": "Viewport y coordinate for drag/drop fallback."},
                    "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
                    "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
                },
                "required": ["node_id", "action"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser act click fill submit select press hover wait drag drop upload automation node_id",
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=lambda args, context: _browser_action_permission("BrowserAct", args, context),
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def _simple_browser_control_tool(
    *,
    name: str,
    description: str,
    schema_properties: dict[str, Any],
    search_hint: str,
    handler: Any,
    validate: Any,
) -> Tool:
    permission_kwargs = {}
    if name != "BrowserWait":
        permission_kwargs["check_permissions"] = (
            lambda args, context: _browser_action_permission(name, args, context)
        )
    return build_tool(
        definition=ToolDefinition(
            name=name,
            description=description,
            input_schema={
                "type": "object",
                "properties": schema_properties,
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint=search_hint,
            max_result_size_chars=20_000,
            is_read_only=False,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        **permission_kwargs,
        is_read_only=lambda _args: False,
        is_concurrency_safe=lambda _args: False,
    )


def _page_target_schema() -> dict[str, Any]:
    return {
        "browser_id": {
            "type": "string",
            "description": "Optional shared Browser panel id returned by BrowserListTabs. Defaults to the active shared browser.",
        },
        "page_id": {
            "type": "string",
            "description": "Optional page_id returned by BrowserOpen or BrowserListTabs.",
        },
        "window_id": {
            "type": "string",
            "description": "Alias for page_id. If both are provided they must match.",
        },
    }


def _viewport_schema() -> dict[str, Any]:
    return {
        "width": {"type": "integer", "minimum": 320, "maximum": 2400, "default": 1024},
        "height": {"type": "integer", "minimum": 240, "maximum": 1800, "default": 720},
    }


def _validate_browser_dimensions(arguments: ToolArguments, tool_name: str) -> ToolPermissionResult | None:
    width = arguments.get("width", 1024)
    height = arguments.get("height", 720)
    if not _is_int(width) or int(width) < 320 or int(width) > 2400:
        return _deny(f"{tool_name} width must be between 320 and 2400.")
    if not _is_int(height) or int(height) < 240 or int(height) > 1800:
        return _deny(f"{tool_name} height must be between 240 and 1800.")
    return None


def _browser_width(arguments: ToolArguments) -> int:
    return min(max(320, int(arguments.get("width") or 1024)), 2400)


def _browser_height(arguments: ToolArguments) -> int:
    return min(max(240, int(arguments.get("height") or 720)), 1800)


def _prepare_browser_control_response(
    data: dict[str, Any],
    *,
    keep_image: bool = False,
    element_limit: int = 60,
) -> dict[str, Any]:
    result = dict(data)
    elements = _summarize_element_map(result.pop("element_map", []))
    result["element_count"] = len(elements)
    result["elements"] = elements[:element_limit]
    result.pop("browser_snapshot", None)
    result.pop("frame_tree", None)
    if keep_image:
        if result.get("image_data"):
            result.pop("html", None)
            result.pop("document_html", None)
        return result
    result.pop("image_data", None)
    result.pop("image_mime_type", None)
    result.pop("html", None)
    result.pop("document_html", None)
    return result


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
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": " ".join(str(item.get("text") or "").split())[:180],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [],
                "shadow_path": item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else [],
                "interactable": bool(item.get("interactable")),
                "stable_key": str(item.get("stable_key") or ""),
                "computed_summary": item.get("computed_summary") if isinstance(item.get("computed_summary"), dict) else {},
                "form_action": str(item.get("form_action") or ""),
                "input_type": str(item.get("input_type") or ""),
                "bounds": item.get("bounds") if isinstance(item.get("bounds"), dict) else {},
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
    return _PAGE_CACHE.resolve_key(conversation_id, raw_cache_key)


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
    browser_id: Any = None,
) -> ToolPermissionResult | None:
    if browser_id is not None and (not isinstance(browser_id, str) or not browser_id.strip()):
        return _deny(f"{tool_name} browser_id must be a non-empty string.")
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


def _browser_session_id(context: ToolUseContext) -> str:
    override = context.metadata.get("_browser_session_id_override")
    if isinstance(override, str) and override.strip():
        return override.strip()
    target = _browser_target(context)
    target_browser_id = str(target.get("browser_id") or "").strip()
    if target_browser_id:
        return target_browser_id
    active_browser_id = str(_browser_workspace(context).get("active_browser_id") or "").strip()
    if active_browser_id:
        return active_browser_id
    return context.conversation_id


def _browser_workspace(context: ToolUseContext) -> Mapping[str, Any]:
    workspace = context.metadata.get("browser_workspace")
    return workspace if isinstance(workspace, Mapping) else {}


def _browser_workspace_active_tab_id(context: ToolUseContext) -> str | None:
    workspace = _browser_workspace(context)
    active_tab_id = str(workspace.get("active_tab_id") or "").strip()
    if active_tab_id:
        return active_tab_id
    tabs = _workspace_browser_tabs(workspace, browser_id=_browser_session_id(context))
    active = next(
        (
            tab
            for tab in tabs
            if bool(tab.get("active") or tab.get("is_active") or tab.get("is_current_page"))
        ),
        None,
    )
    if active:
        return str(active.get("page_id") or active.get("window_id") or active.get("tab_id") or "").strip() or None
    return None


def _browser_workspace_current_url(context: ToolUseContext) -> str | None:
    workspace = _browser_workspace(context)
    url = str(workspace.get("current_url") or "").strip()
    if not url:
        tabs = _workspace_browser_tabs(workspace, browser_id=_browser_session_id(context))
        active = next(
            (
                tab
                for tab in tabs
                if bool(tab.get("active") or tab.get("is_active") or tab.get("is_current_page"))
            ),
            tabs[0] if tabs else None,
        )
        url = str((active or {}).get("final_url") or (active or {}).get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return None


def _browser_view_is_about_blank(view: Mapping[str, Any]) -> bool:
    url = str(view.get("url") or "").strip()
    return not url or url == "about:blank"


def _merge_shared_browser_workspace_tabs(
    data: dict[str, Any],
    context: ToolUseContext,
    *,
    browser_id: str,
    max_tabs: int,
) -> dict[str, Any]:
    result = dict(data)
    workspace = context.metadata.get("browser_workspace")
    if not isinstance(workspace, Mapping):
        result.setdefault("browser_id", browser_id)
        return result
    workspace_tabs = _workspace_browser_tabs(workspace, browser_id=browser_id)
    if not workspace_tabs:
        result.setdefault("browser_id", browser_id)
        return result
    existing_tabs = result.get("tabs") if isinstance(result.get("tabs"), list) else []
    if existing_tabs and int(result.get("tab_count") or 0) > 0:
        merged = [_normalize_browser_tab_for_tool(tab, browser_id=browser_id) for tab in existing_tabs if isinstance(tab, Mapping)]
    else:
        merged = workspace_tabs
    result["type"] = "browser_tabs"
    result["browser_id"] = browser_id
    result["active_browser_id"] = str(workspace.get("active_browser_id") or browser_id)
    result["tab_count"] = len(merged[:max_tabs])
    result["current_url"] = result.get("current_url") or str(workspace.get("current_url") or "")
    active_tab_id = str(workspace.get("active_tab_id") or "")
    result["last_open_page_id"] = result.get("last_open_page_id") or active_tab_id or (merged[0].get("page_id") if merged else None)
    result["last_open_window_id"] = result.get("last_open_window_id") or active_tab_id or (merged[0].get("window_id") if merged else None)
    result["tabs"] = merged[:max_tabs]
    return result


def _workspace_browser_tabs(workspace: Mapping[str, Any], *, browser_id: str) -> list[dict[str, Any]]:
    raw_tabs = workspace.get("tabs")
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    current_url = str(workspace.get("current_url") or "").strip()
    active_tab_id = str(workspace.get("active_tab_id") or browser_id).strip()
    if not tabs and current_url:
        tabs = [
            {
                "tab_id": active_tab_id,
                "id": active_tab_id,
                "url": current_url,
                "final_url": current_url,
                "title": str(workspace.get("current_title") or ""),
                "active": True,
                "is_active": True,
                "runtime": "lightpanda",
            }
        ]
    return [
        _normalize_browser_tab_for_tool(tab, browser_id=browser_id, index=index)
        for index, tab in enumerate(tabs, start=1)
        if isinstance(tab, Mapping)
    ]


def _normalize_browser_tab_for_tool(
    tab: Mapping[str, Any],
    *,
    browser_id: str,
    index: int | None = None,
) -> dict[str, Any]:
    page_id = str(tab.get("page_id") or tab.get("window_id") or tab.get("tab_id") or tab.get("id") or browser_id)
    url = str(tab.get("final_url") or tab.get("url") or "")
    title = str(tab.get("title") or "")
    parsed = urlparse(url)
    domain = parsed.netloc
    active = bool(tab.get("active") or tab.get("is_active"))
    extraction_count = int(tab.get("extraction_count") or 0)
    already_read = bool(tab.get("already_read")) or extraction_count > 0
    return {
        "index": int(tab.get("index") or index or 1),
        "browser_id": str(tab.get("browser_id") or browser_id),
        "page_id": page_id,
        "window_id": page_id,
        "tab_id": page_id,
        "id": page_id,
        "url": str(tab.get("url") or url),
        "final_url": url,
        "domain": domain,
        "title": title,
        "summary": str(tab.get("summary") or title or domain or url),
        "runtime": str(tab.get("runtime") or ""),
        "source_search_id": tab.get("source_search_id"),
        "opener_tool_call_id": tab.get("opener_tool_call_id"),
        "extraction_count": extraction_count,
        "already_read": already_read,
        "read_status": str(tab.get("read_status") or ("read" if already_read else "unread")),
        "is_last_open": bool(tab.get("is_last_open") or active),
        "is_current_page": bool(tab.get("is_current_page") or active),
        "active": active,
        "is_active": active,
        "history": tab.get("history") if isinstance(tab.get("history"), list) else ([url] if url else []),
        "state": dict(tab.get("state")) if isinstance(tab.get("state"), dict) else {},
        "updated_at": str(tab.get("updated_at") or ""),
    }


def _resolve_browser_page_target(
    arguments: ToolArguments,
    context: ToolUseContext,
    *,
    tool_name: str,
    block_url_argument: bool = False,
) -> tuple[str | None, str | None]:
    requested = _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id"))
    requested_browser_id = str(arguments.get("browser_id") or "").strip()
    has_url_argument = isinstance(arguments.get("url"), str) and bool(arguments["url"].strip())
    if arguments.get("browser_id") is not None and not requested_browser_id:
        return requested, f"{tool_name} browser_id must be a non-empty string."
    target = _browser_target(context)
    target_id = _browser_target_page_id(target)
    target_browser_id = str(target.get("browser_id") or "").strip()
    workspace_browser_id = str(_browser_workspace(context).get("active_browser_id") or "").strip()
    workspace_target_id = _browser_workspace_active_tab_id(context)
    if requested_browser_id and target_browser_id and requested_browser_id != target_browser_id:
        return (
            requested,
            (
                f"{tool_name} cannot target browser_id {requested_browser_id} because the user attached "
                f"Browser workspace {target_browser_id} for this turn."
            ),
        )
    if requested_browser_id:
        context.metadata["_browser_session_id_override"] = requested_browser_id
    elif requested and requested.startswith("browser:"):
        context.metadata["_browser_session_id_override"] = requested
    if not target_id:
        if requested:
            return requested, None
        if workspace_target_id and not has_url_argument and (
            not requested_browser_id or not workspace_browser_id or requested_browser_id == workspace_browser_id
        ):
            return workspace_target_id, None
        return None, None
    if block_url_argument and has_url_argument:
        return (
            requested or target_id,
            (
                f"{tool_name} is bound to the referenced Browser tab {target_id}; "
                "omit url and operate on the attached shared tab instead of opening or reading another page."
            ),
        )
    if requested and requested != target_id:
        return (
            requested,
            (
                f"{tool_name} cannot target page_id/window_id {requested} because the user attached "
                f"Browser tab {target_id} for this turn."
            ),
        )
    return requested or target_id, None


def _browser_targeted_arguments(
    arguments: ToolArguments,
    context: ToolUseContext,
    *,
    tool_name: str,
) -> tuple[ToolArguments, str | None]:
    target_id, error = _resolve_browser_page_target(arguments, context, tool_name=tool_name)
    if error:
        return arguments, error
    if not target_id or _coerce_page_or_window_id(arguments.get("page_id"), arguments.get("window_id")):
        return arguments, None
    updated = dict(arguments)
    updated["page_id"] = target_id
    updated["window_id"] = target_id
    return updated, None


def _browser_target(context: ToolUseContext) -> dict[str, Any]:
    target = context.metadata.get("browser_target")
    return dict(target) if isinstance(target, Mapping) else {}


def _browser_target_page_id(target: Mapping[str, Any]) -> str | None:
    return _coerce_page_or_window_id(
        target.get("page_id") or target.get("tab_id"),
        target.get("window_id"),
    )


def _target_error_result(call: ToolCall, tool_name: str, message: str) -> ToolResult:
    data = {
        "type": _error_type(tool_name),
        "error": message,
        "browser_target_conflict": True,
    }
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        data=data,
    )


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
        "BrowserClick": "browser_click",
        "BrowserType": "browser_type",
        "BrowserScreenshot": "browser_screenshot",
        "BrowserCloseTab": "browser_close_tab",
        "BrowserReadConsole": "browser_console",
        "BrowserScript": "browser_script",
        "BrowserScroll": "browser_scroll",
        "BrowserReload": "browser_reload",
        "BrowserHistory": "browser_history",
        "BrowserSwitchTab": "browser_switch_tab",
        "BrowserWait": "browser_wait",
        "BrowserAct": "browser_action",
    }.get(tool_name, "browser")


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


async def _browser_action_permission(
    tool_name: str,
    arguments: ToolArguments,
    context: ToolUseContext,
) -> ToolPermissionResult:
    targeted_arguments, target_error = _browser_targeted_arguments(
        arguments,
        context,
        tool_name=tool_name,
    )
    if target_error:
        return _deny(target_error)
    permission = _BROWSER_ACTION_ARBITER.decide(
        tool_name=tool_name,
        arguments=targeted_arguments,
        context=context,
    ).to_permission_result()
    if targeted_arguments is not arguments:
        return ToolPermissionResult(
            behavior=permission.behavior,
            message=permission.message,
            updated_input=targeted_arguments,
            metadata=permission.metadata,
        )
    return permission


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


def _browser_result_max_chars(context: ToolUseContext) -> int:
    raw_limit = context.limits.get("result_max_chars")
    if raw_limit is None:
        return 60_000
    try:
        parsed = int(raw_limit)
    except (TypeError, ValueError):
        return 60_000
    return parsed if parsed > 0 else 60_000
