"""MCP server configuration and related utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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
