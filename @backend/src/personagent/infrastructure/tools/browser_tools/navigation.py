"""Navigation-related browser tool factories.

Extracted from ``factories.py`` (browser_tools Slice 2).
Contains: BrowserSearch, BrowserOpen, BrowserExtractContent,
BrowserReadContentChunk, BrowserGetHtml, BrowserGetElementMap.
"""

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
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools.browser_tools.helpers import (
    _DEFAULT_CHUNK_SIZE,
    _MAX_CHUNK_COUNT,
    _PAGE_CACHE,
    _browser_result_max_chars,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_view_is_about_blank,
    _browser_workspace_current_url,
    _cached_extracted_content_response,
    _coerce_page_or_window_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _normalize_browser_open_arguments,
    _page_target_schema,
    _prepare_extracted_content_response,
    _progress,
    _resolve_browser_page_target,
    _resolve_cache_key,
    _run_deduped_browser_extract,
    _summarize_element_map,
    _target_error_result,
    _validate_page_or_window_id,
)
from personagent.infrastructure.tools.web_tools import validate_web_url


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
