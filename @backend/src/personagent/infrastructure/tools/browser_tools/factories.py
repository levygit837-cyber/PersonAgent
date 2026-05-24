"""LightPanda browser tools for the main chat agent."""

from __future__ import annotations

import json

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
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.browser_tools.helpers import (
    _BROWSER_ACTIONS,
    _BROWSER_CONSOLE_LEVELS,
    _BROWSER_CONTROL_CDP_ALLOWLIST,
    _DEFAULT_CHUNK_SIZE,
    _MAX_CHUNK_COUNT,
    _PAGE_CACHE,
    _browser_action_permission,
    _browser_height,
    _browser_result_max_chars,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_view_is_about_blank,
    _browser_width,
    _browser_workspace_current_url,
    _cached_extracted_content_response,
    _coerce_page_or_window_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _merge_shared_browser_workspace_tabs,
    _normalize_browser_open_arguments,
    _page_target_schema,
    _prepare_browser_control_response,
    _prepare_extracted_content_response,
    _progress,
    _resolve_browser_page_target,
    _resolve_cache_key,
    _run_deduped_browser_extract,
    _simple_browser_control_tool,
    _summarize_element_map,
    _target_error_result,
    _validate_browser_dimensions,
    _validate_page_or_window_id,
    _viewport_schema,
)
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
