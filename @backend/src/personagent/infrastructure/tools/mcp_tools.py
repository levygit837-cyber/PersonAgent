"""Minimal MCP tools and config-backed dynamic MCP callables."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
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
    ToolResult,
    ToolUseContext,
    build_tool,
)

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    """Normalized MCP server config used by tools."""

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    tools: tuple[dict[str, Any], ...] = ()
    resources: tuple[dict[str, Any], ...] = ()
    auth_url: str | None = None
    requires_auth: bool = False
    timeout_ms: int = 30_000


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


async def _mcp_permission(
    arguments: ToolArguments,
    _context: ToolUseContext,
) -> ToolPermissionResult:
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


async def _allow(arguments: ToolArguments, _context: ToolUseContext) -> ToolPermissionResult:
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


async def _mcp_request(
    config: McpServerConfig,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if config.transport != "stdio":
        raise RuntimeError(f"Unsupported MCP transport for {config.name}: {config.transport}")
    if not config.command:
        raise RuntimeError(f"MCP server {config.name} has no command configured.")

    env = os.environ.copy()
    if config.env:
        env.update(config.env)
    process = await asyncio.create_subprocess_exec(
        config.command,
        *config.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        init = await _send_request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PersonAgent", "version": "0.1.0"},
            },
            timeout_ms=config.timeout_ms,
        )
        if init.get("error"):
            raise RuntimeError(str(init["error"]))
        await _send_notification(process, "notifications/initialized", {})
        response = await _send_request(
            process,
            2,
            method,
            params,
            timeout_ms=config.timeout_ms,
        )
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        result = response.get("result")
        return result if isinstance(result, dict) else {"content": result}
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            process.kill()
            await process.wait()


async def _send_request(
    process: asyncio.subprocess.Process,
    request_id: int,
    method: str,
    params: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    await _write_json(
        process,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    return await asyncio.wait_for(_read_response(process, request_id), timeout=timeout_ms / 1000)


async def _send_notification(
    process: asyncio.subprocess.Process,
    method: str,
    params: dict[str, Any],
) -> None:
    await _write_json(process, {"jsonrpc": "2.0", "method": method, "params": params})


async def _write_json(process: asyncio.subprocess.Process, payload: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
    await process.stdin.drain()


async def _read_response(
    process: asyncio.subprocess.Process,
    request_id: int,
) -> dict[str, Any]:
    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "MCP server exited.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("id") == request_id:
            return payload


def _normalize_config(raw: McpServerConfig | dict[str, Any]) -> McpServerConfig:
    if isinstance(raw, McpServerConfig):
        return raw
    return McpServerConfig(
        name=str(raw.get("name") or raw.get("id") or "server"),
        transport=str(raw.get("transport") or "stdio"),
        command=raw.get("command"),
        args=tuple(str(item) for item in raw.get("args") or ()),
        env={str(k): str(v) for k, v in dict(raw.get("env") or {}).items()} or None,
        tools=tuple(item for item in raw.get("tools") or () if isinstance(item, dict)),
        resources=tuple(item for item in raw.get("resources") or () if isinstance(item, dict)),
        auth_url=raw.get("auth_url") or raw.get("oauth_url"),
        requires_auth=bool(raw.get("requires_auth")),
        timeout_ms=int(raw.get("timeout_ms") or 30_000),
    )


def _find_server(configs: list[McpServerConfig], name: str) -> McpServerConfig | None:
    normalized = _sanitize(name)
    return next((config for config in configs if config.name == name or _sanitize(config.name) == normalized), None)


def _static_resources(config: McpServerConfig) -> list[dict[str, Any]]:
    return [{"server": config.name, **resource} for resource in config.resources]


def _auth_payload(config: McpServerConfig) -> dict[str, Any]:
    message = (
        f"Open {config.auth_url} to authenticate MCP server {config.name}."
        if config.auth_url
        else f"MCP server {config.name} requires authentication, but no OAuth URL is configured."
    )
    return {
        "type": "mcp_auth",
        "server": config.name,
        "auth_url": config.auth_url,
        "requires_auth": config.requires_auth,
        "content": message,
    }


def _sanitize(value: str) -> str:
    sanitized = _NAME_RE.sub("_", value.strip())
    return sanitized.strip("_") or "server"


def _error(call: ToolCall, tool_name: str, message: str) -> ToolResult:
    data = {"type": "mcp_error", "content": message}
    return ToolResult(
        call.id,
        tool_name,
        json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=data,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)
