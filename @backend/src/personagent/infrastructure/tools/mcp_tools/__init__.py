"""MCP tools and config-backed dynamic MCP callables.

This package was extracted from the monolithic ``mcp_tools.py``.
The public API is ``create_mcp_tools(server_configs, enabled=True)``.
"""

from personagent.infrastructure.tools.mcp_tools.config import McpServerConfig
from personagent.infrastructure.tools.mcp_tools.factories import (
    create_list_mcp_resources_tool,
    create_mcp_auth_tool,
    create_mcp_tools,
    create_read_mcp_resource_tool,
)

__all__ = [
    "McpServerConfig",
    "create_list_mcp_resources_tool",
    "create_mcp_auth_tool",
    "create_mcp_tools",
    "create_read_mcp_resource_tool",
]
