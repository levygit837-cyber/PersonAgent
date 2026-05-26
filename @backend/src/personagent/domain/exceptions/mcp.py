from personagent.domain.exceptions.base import ErrorCategory
from personagent.domain.exceptions.tool import ToolError


class McpError(ToolError):
    """MCP operation failed."""

    code = "mcp.error"
    category = ErrorCategory.MCP


class McpAuthRequiredError(McpError):
    """MCP server requires authentication."""

    code = "mcp.auth_required"
    http_status = 401


class McpSessionExpiredError(McpError):
    """MCP session expired."""

    code = "mcp.session_expired"
    http_status = 401
    retryable = True


class McpRequestTimeoutError(McpError):
    """MCP request timed out."""

    code = "mcp.request_timeout"
    http_status = 504
    retryable = True


