"""LightPanda browser tools for the main chat agent."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

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
        create_browser_extract_content_tool(worker),
        create_browser_read_content_chunk_tool(),
        create_browser_get_html_tool(worker),
    ]


_DEFAULT_CHUNK_SIZE = 8_000
_PAGE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_LATEST_CACHE_KEY: dict[str, str] = {}


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
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_open_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        url = arguments.get("url")
        result_index = arguments.get("result_index")
        has_url = isinstance(url, str) and bool(url.strip())
        has_index = _is_int(result_index)
        if has_url == has_index:
            return _deny("BrowserOpen requires exactly one of 'url' or 'result_index'.")
        if has_url:
            return validate_web_url(str(url), context)
        if int(result_index) < 1:
            return _deny("BrowserOpen result_index must be 1 or greater.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = arguments.get("url")
        result_index = arguments.get("result_index")
        await _progress(
            context,
            call,
            "Opening page with LightPanda...",
            {"url": url, "result_index": result_index},
        )
        try:
            target_url = str(url).strip() if isinstance(url, str) and url.strip() else None
            data = await worker.open(
                conversation_id=context.conversation_id,
                url=target_url,
                result_index=int(result_index) if _is_int(result_index) else None,
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
                "Open a URL or a 1-based result_index from the last BrowserSearch in the "
                "same chat conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to open."},
                    "result_index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-based index from the last BrowserSearch result list.",
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser open url navigate lightpanda",
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
    )


def create_browser_extract_content_tool(worker: LightPandaBrowserWorker) -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        url = arguments.get("url")
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
        max_chars = int(
            arguments.get("max_chars") or context.limits.get("result_max_chars", 20_000)
        )
        include_links = bool(arguments.get("include_links", False))
        await _progress(context, call, "Extracting page content with LightPanda...", {"url": url})
        try:
            data = await worker.extract_content(
                conversation_id=context.conversation_id,
                url=str(url).strip() if isinstance(url, str) and url.strip() else None,
                max_chars=max_chars,
                include_links=include_links,
            )
        except Exception as exc:
            return _error(call, "BrowserExtractContent", str(exc), exc)
        data = dict(data)
        cache_metadata = _cache_page_content(context.conversation_id, data)
        if cache_metadata:
            data.update(cache_metadata)
        return _json_result(call, "BrowserExtractContent", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserExtractContent",
            description=(
                "Return organized markdown/text content from the current LightPanda page or "
                "from a provided URL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional HTTP or HTTPS URL."},
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
            max_result_size_chars=80_000,
            is_read_only=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
        is_read_only=lambda _args: True,
        is_concurrency_safe=lambda _args: False,
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
        if not _is_int(chunk_count) or int(chunk_count) < 1 or int(chunk_count) > 10:
            return _deny("BrowserReadContentChunk chunk_count must be between 1 and 10.")
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
        start_index = min(max(1, int(arguments.get("chunk_index") or 1)), len(chunks))
        count = min(max(1, int(arguments.get("chunk_count") or 1)), 10)
        selected = chunks[start_index - 1 : start_index - 1 + count]
        data = {
            "type": "browser_content_chunks",
            "cache_key": cache_key,
            "url": entry["url"],
            "title": entry["title"],
            "chunk_index": start_index,
            "chunk_count": len(selected),
            "total_chunks": len(chunks),
            "chunks": [
                {"index": start_index + offset, "content": content}
                for offset, content in enumerate(selected)
            ],
            "links": entry.get("links", []),
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
                        "maximum": 10,
                        "default": 1,
                    },
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="browser cached content chunk page research",
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
        max_chars = int(
            arguments.get("max_chars") or context.limits.get("result_max_chars", 20_000)
        )
        await _progress(context, call, "Reading raw page HTML with LightPanda...", {"url": url})
        try:
            data = await worker.get_html(
                conversation_id=context.conversation_id,
                url=str(url).strip() if isinstance(url, str) and url.strip() else None,
                max_chars=max_chars,
            )
        except Exception as exc:
            return _error(call, "BrowserGetHtml", str(exc), exc)
        return _json_result(call, "BrowserGetHtml", data)

    return build_tool(
        definition=ToolDefinition(
            name="BrowserGetHtml",
            description="Return raw HTML from the current LightPanda page or from a provided URL.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Optional HTTP or HTTPS URL."},
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


def _cache_page_content(conversation_id: str, data: dict[str, Any]) -> dict[str, Any]:
    content = str(data.get("content") or "")
    if not content:
        return {}
    url = str(data.get("url") or "")
    title = str(data.get("title") or "")
    digest = sha256(f"{url}\n{title}\n{content[:256]}".encode()).hexdigest()[:12]
    cache_key = f"page_{digest}"
    chunks = [
        content[index : index + _DEFAULT_CHUNK_SIZE]
        for index in range(0, len(content), _DEFAULT_CHUNK_SIZE)
    ] or [""]
    entry = {
        "url": url,
        "title": title,
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunks": chunks,
        "links": data.get("links") if isinstance(data.get("links"), list) else [],
        "buttons": data.get("buttons") if isinstance(data.get("buttons"), list) else [],
    }
    _PAGE_CACHE.setdefault(conversation_id, {})[cache_key] = entry
    _LATEST_CACHE_KEY[conversation_id] = cache_key
    return {
        "cache_key": cache_key,
        "content_chars": len(content),
        "chunk_size": _DEFAULT_CHUNK_SIZE,
        "chunk_count": len(chunks),
        "links": entry["links"],
        "buttons": entry["buttons"],
    }


def _resolve_cache_key(conversation_id: str, raw_cache_key: Any) -> str | None:
    if isinstance(raw_cache_key, str) and raw_cache_key.strip():
        return raw_cache_key.strip()
    return _LATEST_CACHE_KEY.get(conversation_id)


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
        "BrowserExtractContent": "browser_extract_content",
        "BrowserReadContentChunk": "browser_content_chunks",
        "BrowserGetHtml": "browser_get_html",
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
