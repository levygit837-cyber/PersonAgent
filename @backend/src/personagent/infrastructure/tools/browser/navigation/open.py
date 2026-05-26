"""BrowserOpen tool factory."""

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
    _browser_session_id,
    _deny,
    _error,
    _json_result,
    _normalize_browser_open_arguments,
    _progress,
)
from personagent.infrastructure.tools.interaction.web_tools import validate_web_url


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
