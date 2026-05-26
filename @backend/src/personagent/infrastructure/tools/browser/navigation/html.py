"""BrowserGetHtml tool factory."""

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
    _browser_result_max_chars,
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_workspace_current_url,
    _coerce_page_or_window_id,
    _deny,
    _error,
    _is_int,
    _json_result,
    _progress,
    _resolve_browser_page_target,
    _target_error_result,
    _validate_page_or_window_id,
)
from personagent.infrastructure.tools.interaction.web_tools import validate_web_url


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
