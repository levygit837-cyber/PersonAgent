"""MCP tool factories."""

from __future__ import annotations

import json
from typing import Any

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
from personagent.infrastructure.tools.mcp_tools.config import (
    McpServerConfig,
    _auth_payload,
    _find_server,
    _normalize_config,
    _sanitize,
    _static_resources,
)
from personagent.infrastructure.tools.mcp_tools.helpers import (
    _allow,
    _deny,
    _error,
    _mcp_permission,
)
from personagent.infrastructure.tools.mcp_tools.protocol import _mcp_request


def create_mcp_tools(
    server_configs: list[McpServerConfig | dict[str, Any]] | tuple[McpServerConfig | dict[str, Any], ...],
    *,
    enabled: bool = True,
) -> list[Tool]:
    """Create base MCP tools plus configured dynamic tools."""
    configs = [_normalize_config(config) for config in server_configs]
    tools: list[Tool] = [
        create_list_mcp_resources_tool(configs, enabled=enabled),
        create_read_mcp_resource_tool(configs, enabled=enabled),
        create_mcp_auth_tool(configs, enabled=enabled),
    ]
    for config in configs:
        for item in config.tools:
            tools.append(_create_dynamic_mcp_tool(config, item, enabled=enabled))
        if config.requires_auth or config.auth_url:
            tools.append(_create_dynamic_auth_tool(config, enabled=enabled))
    return tools


def create_list_mcp_resources_tool(
    configs: list[McpServerConfig],
    *,
    enabled: bool = True,
) -> Tool:
    """Create ListMcpResourcesTool."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        server = arguments.get("server")
        if server is not None and _find_server(configs, str(server)) is None:
            return _deny(f"Unknown MCP server: {server}")
        return None

    async def handler(
        arguments: ToolArguments,
        _context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        selected = [_find_server(configs, str(arguments["server"]))] if arguments.get("server") else configs
        resources: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for config in [item for item in selected if item is not None]:
            resources.extend(_static_resources(config))
            if config.command:
                try:
                    result = await _mcp_request(config, "resources/list", {})
                    for resource in result.get("resources") or []:
                        if isinstance(resource, dict):
                            resources.append({"server": config.name, **resource})
                except Exception as exc:
                    errors[config.name] = str(exc)
        data = {
            "type": "mcp_resources",
            "resources": resources,
            "errors": errors,
            "content": json.dumps(resources, ensure_ascii=False),
        }
        return ToolResult(
            call.id,
            "ListMcpResourcesTool",
            json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="ListMcpResourcesTool",
            aliases=("ListMcpResources",),
            description="List resources exposed by configured MCP servers.",
            input_schema={
                "type": "object",
                "properties": {"server": {"type": "string"}},
                "additionalProperties": False,
            },
            group=ToolGroup.MCP.value,
            search_hint="mcp resources list",
            is_read_only=True,
            is_concurrency_safe=True,
            is_mcp=True,
        ),
        handler=handler,
        enabled=enabled,
        validate_input=validate,
        check_permissions=_allow,
        is_concurrency_safe=lambda _args: True,
        is_read_only=lambda _args: True,
    )


def create_read_mcp_resource_tool(
    configs: list[McpServerConfig],
    *,
    enabled: bool = True,
) -> Tool:
    """Create ReadMcpResourceTool."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        server = arguments.get("server")
        uri = arguments.get("uri")
        if not isinstance(server, str) or not server.strip():
            return _deny("ReadMcpResourceTool requires a non-empty 'server'.")
        if not isinstance(uri, str) or not uri.strip():
            return _deny("ReadMcpResourceTool requires a non-empty 'uri'.")
        if _find_server(configs, server) is None:
            return _deny(f"Unknown MCP server: {server}")
        return None

    async def handler(
        arguments: ToolArguments,
        _context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        config = _find_server(configs, str(arguments["server"]))
        if config is None:
            return _error(call, "ReadMcpResourceTool", f"Unknown MCP server: {arguments['server']}")

        uri = str(arguments["uri"])
        static = next((item for item in _static_resources(config) if item.get("uri") == uri), None)
        if static and "content" in static:
            data = {"type": "mcp_resource", "server": config.name, "uri": uri, **static}
            return ToolResult(
                call.id,
                "ReadMcpResourceTool",
                json.dumps(data, ensure_ascii=False),
                data=data,
            )

        if not config.command:
            return _error(
                call,
                "ReadMcpResourceTool",
                f"MCP server {config.name} has no stdio command and no static resource content.",
            )

        try:
            result = await _mcp_request(config, "resources/read", {"uri": uri})
        except Exception as exc:
            return _error(call, "ReadMcpResourceTool", str(exc))
        data = {"type": "mcp_resource", "server": config.name, "uri": uri, **result}
        return ToolResult(
            call.id,
            "ReadMcpResourceTool",
            json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="ReadMcpResourceTool",
            aliases=("ReadMcpResource", "ReadMcpResoucersTool"),
            description="Read one resource exposed by an MCP server.",
            input_schema={
                "type": "object",
                "properties": {
                    "server": {"type": "string"},
                    "uri": {"type": "string"},
                },
                "required": ["server", "uri"],
                "additionalProperties": False,
            },
            group=ToolGroup.MCP.value,
            search_hint="mcp resource read",
            is_read_only=True,
            is_concurrency_safe=True,
            is_mcp=True,
        ),
        handler=handler,
        enabled=enabled,
        validate_input=validate,
        check_permissions=_allow,
        is_concurrency_safe=lambda _args: True,
        is_read_only=lambda _args: True,
    )


def create_mcp_auth_tool(configs: list[McpServerConfig], *, enabled: bool = True) -> Tool:
    """Create generic McpAuth pseudo-tool."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        server = arguments.get("server")
        if not isinstance(server, str) or not server.strip():
            return _deny("McpAuth requires a non-empty 'server'.")
        if _find_server(configs, server) is None:
            return _deny(f"Unknown MCP server: {server}")
        return None

    async def handler(
        arguments: ToolArguments,
        _context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        config = _find_server(configs, str(arguments["server"]))
        if config is None:
            return _error(call, "McpAuth", f"Unknown MCP server: {arguments['server']}")
        data = _auth_payload(config)
        return ToolResult(call.id, "McpAuth", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="McpAuth",
            description="Return authentication instructions for a configured MCP server.",
            input_schema={
                "type": "object",
                "properties": {"server": {"type": "string"}},
                "required": ["server"],
                "additionalProperties": False,
            },
            group=ToolGroup.MCP.value,
            search_hint="mcp auth oauth login authenticate",
            is_read_only=True,
            is_mcp=True,
        ),
        handler=handler,
        enabled=enabled,
        validate_input=validate,
        check_permissions=_allow,
        is_read_only=lambda _args: True,
    )


def _create_dynamic_mcp_tool(
    config: McpServerConfig,
    item: dict[str, Any],
    *,
    enabled: bool,
) -> Tool:
    tool_name = str(item.get("name") or "").strip()
    dynamic_name = f"mcp__{_sanitize(config.name)}__{_sanitize(tool_name)}"
    input_schema = item.get("input_schema") or item.get("inputSchema") or {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        if config.requires_auth:
            return _deny(
                f"MCP server {config.name} requires authentication. Use "
                f"mcp__{_sanitize(config.name)}__authenticate or McpAuth first."
            )
        return None

    async def handler(
        arguments: ToolArguments,
        _context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        if "static_result" in item:
            payload = item["static_result"]
        elif not config.command:
            return _error(call, dynamic_name, f"MCP server {config.name} has no stdio command.")
        else:
            try:
                payload = await _mcp_request(
                    config,
                    "tools/call",
                    {"name": tool_name, "arguments": arguments},
                )
            except Exception as exc:
                return _error(call, dynamic_name, str(exc))
        data = {
            "type": "mcp_tool_result",
            "server": config.name,
            "tool": tool_name,
            "result": payload,
            "content": json.dumps(payload, ensure_ascii=False),
        }
        return ToolResult(call.id, dynamic_name, json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name=dynamic_name,
            description=str(item.get("description") or f"MCP tool {tool_name} on {config.name}."),
            input_schema=input_schema,
            group=ToolGroup.MCP.value,
            search_hint=f"mcp {config.name} {tool_name}",
            cacheable_prompt=False,
            is_mcp=True,
        ),
        handler=handler,
        enabled=enabled,
        validate_input=validate,
        check_permissions=_mcp_permission,
    )


def _create_dynamic_auth_tool(config: McpServerConfig, *, enabled: bool) -> Tool:
    name = f"mcp__{_sanitize(config.name)}__authenticate"

    async def handler(
        _arguments: ToolArguments,
        _context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        data = _auth_payload(config)
        return ToolResult(call.id, name, json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name=name,
            description=f"Authenticate MCP server {config.name}.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            group=ToolGroup.MCP.value,
            search_hint=f"mcp {config.name} authenticate auth oauth",
            is_read_only=True,
            is_mcp=True,
        ),
        handler=handler,
        enabled=enabled,
        check_permissions=_allow,
        is_read_only=lambda _args: True,
    )
