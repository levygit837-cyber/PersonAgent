"""Tool building helpers for browser tools."""

from __future__ import annotations

from typing import Any

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolDefinition,
    ToolGroup,
    ToolPermissionResult,
    build_tool,
)
from personagent.infrastructure.tools.browser.building._errors import (
    _browser_action_permission,
    _deny,
)
from personagent.infrastructure.tools.browser.building._utils import _is_int


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
