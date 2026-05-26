"""BrowserExtractContent tool factory."""

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
from personagent.infrastructure.tools.browser.building import (
    _PAGE_CACHE,
    _browser_result_max_chars,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_workspace_current_url,
    _cached_extracted_content_response,
    _coerce_page_or_window_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _prepare_extracted_content_response,
    _progress,
    _resolve_browser_page_target,
    _run_deduped_browser_extract,
    _target_error_result,
    _validate_page_or_window_id,
)
from personagent.infrastructure.tools.interaction.web_tools import validate_web_url


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
