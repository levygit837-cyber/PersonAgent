"""Ferramentas web V1."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from personagent.domain.exceptions import WebDomainBlockedError, WebError, WebFetchTimeoutError
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

_TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
)
_MAX_REDIRECTS = 10


def create_web_fetch_tool() -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        url = arguments.get("url")
        if not isinstance(url, str) or not url.strip():
            return _deny("WebFetch requires a non-empty 'url' string.")
        return _validate_url(url, context)

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        url = str(arguments["url"])
        timeout_ms = int(
            arguments.get("timeout_ms") or context.limits.get("web_timeout_ms", 15_000)
        )
        max_bytes = int(arguments.get("max_bytes") or context.limits.get("web_max_bytes", 512_000))

        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="WebFetch",
                status=ToolExecutionStatus.RUNNING,
                message="Fetching...",
                data={"url": url},
            )
        )

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_ms / 1000),
                headers={"User-Agent": "PersonAgent-WebFetch/1.0"},
            ) as client:
                response, redirect_count = await _request_with_redirects(client, url, context)
        except httpx.TimeoutException as exc:
            error = WebFetchTimeoutError(
                f"WebFetch timed out after {timeout_ms}ms.",
                metadata={"url": url, "timeout_ms": timeout_ms},
                cause=exc,
            )
            return _error(call, error.user_message, error)
        except httpx.HTTPError as exc:
            error = WebError(
                f"WebFetch failed: {exc}",
                metadata={"url": url},
                cause=exc,
            )
            return _error(call, error.user_message, error)
        except WebError as exc:
            return _error(call, exc.user_message, exc)

        final_validation = _validate_url(str(response.url), context)
        if final_validation is not None:
            error = WebDomainBlockedError(
                final_validation.message or "Final URL is blocked.",
                metadata={"url": url, "final_url": str(response.url)},
            )
            return _error(call, error.user_message, error)

        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        if content_type and not content_type.startswith(_TEXT_TYPES):
            error = WebError(
                f"Unsupported content type: {content_type}",
                code="web.unsupported_content_type",
                http_status=415,
                metadata={"url": url, "content_type": content_type},
            )
            return _error(call, error.user_message, error)

        body = response.content
        truncated = len(body) > max_bytes
        if truncated:
            body = body[:max_bytes]
        text = body.decode(response.encoding or "utf-8", errors="replace")
        extracted = _extract_text(text, content_type)
        data = {
            "type": "web_fetch",
            "url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "content_type": content_type,
            "content": extracted,
            "truncated": truncated,
            "redirect_count": redirect_count,
        }
        metadata = {}
        if not response.is_success:
            metadata["error"] = WebError(
                f"WebFetch returned HTTP {response.status_code}.",
                code="web.http_error",
                http_status=response.status_code,
                retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                metadata={
                    "url": url,
                    "final_url": str(response.url),
                    "status_code": response.status_code,
                },
            ).to_envelope()
        return ToolResult(
            tool_call_id=call.id,
            tool_name="WebFetch",
            content=json.dumps(data, ensure_ascii=False),
            status=ToolExecutionStatus.COMPLETED
            if response.is_success
            else ToolExecutionStatus.ERROR,
            is_error=not response.is_success,
            data=data,
            metadata=metadata,
        )

    return build_tool(
        definition=ToolDefinition(
            name="WebFetch",
            description="Fetch a text, HTML, JSON or XML URL with workspace web safety limits.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
                    "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 2000000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="fetch url web page http",
            is_read_only=True,
            is_concurrency_safe=True,
            is_open_world=True,
            timeout_ms=60_000,
        ),
        handler=handler,
        validate_input=validate,
    )


def create_web_search_tool(enabled: bool = False) -> Tool:
    async def handler(
        _arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name="WebSearch",
            content="WebSearch is registered but disabled until a search provider is configured.",
            status=ToolExecutionStatus.ERROR,
            is_error=True,
            data={"type": "web_search", "enabled": False},
        )

    return build_tool(
        definition=ToolDefinition(
            name="WebSearch",
            description="Search the web. Disabled in V1 until a provider is selected.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "site": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.WEB.value,
            search_hint="web search internet query",
            should_defer=True,
            is_read_only=True,
            is_concurrency_safe=True,
            is_open_world=True,
        ),
        handler=handler,
        enabled=enabled,
        is_concurrency_safe=lambda _args: True,
        is_read_only=lambda _args: True,
    )


def validate_web_url(url: str, context: ToolUseContext) -> ToolPermissionResult | None:
    """Validate an agent-supplied URL against web tool safety policy."""

    return _validate_url(url, context)


async def _request_with_redirects(
    client: httpx.AsyncClient,
    url: str,
    context: ToolUseContext,
) -> tuple[httpx.Response, int]:
    current_url = url
    redirect_count = 0
    while True:
        response = await client.get(current_url)
        if not response.is_redirect:
            return response, redirect_count
        if redirect_count >= _MAX_REDIRECTS:
            raise WebError(
                f"WebFetch redirect limit exceeded after {_MAX_REDIRECTS} redirects.",
                code="web.redirect_limit_exceeded",
                http_status=508,
                metadata={"url": url, "last_url": str(response.url)},
            )
        location = response.headers.get("location")
        if not location:
            return response, redirect_count
        next_url = urljoin(str(response.url), location)
        validation = _validate_url(next_url, context)
        if validation is not None:
            raise WebDomainBlockedError(
                validation.message or "Redirect URL is blocked.",
                metadata={"url": url, "redirect_url": next_url},
            )
        current_url = next_url
        redirect_count += 1


def _validate_url(url: str, context: ToolUseContext) -> ToolPermissionResult | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return _deny("Only http and https URLs are allowed.")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return _deny("URL must include a hostname.")
    blocked = tuple(str(item).lower() for item in context.limits.get("web_blocked_domains", ()))
    allowed = tuple(str(item).lower() for item in context.limits.get("web_allowed_domains", ()))
    allow_private_hosts = bool(context.limits.get("web_allow_private_hosts", False))
    if _host_matches(hostname, blocked) or (_is_private_host(hostname) and not allow_private_hosts):
        return _deny(f"URL host is blocked: {hostname}")
    if allowed and not _host_matches(hostname, allowed):
        return _deny(f"URL host is not in the allowed domains: {hostname}")
    return None


def _host_matches(hostname: str, patterns: tuple[str, ...]) -> bool:
    return any(hostname == pattern or hostname.endswith(f".{pattern}") for pattern in patterns)


def _is_private_host(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return _hostname_resolves_private(hostname)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    )


def _hostname_resolves_private(hostname: str) -> bool:
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for result in results:
        address = result[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            return True
    return False


def _extract_text(value: str, content_type: str) -> str:
    if "html" not in content_type:
        return value
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


def _error(call: ToolCall, content: str, error: WebError | None = None) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name="WebFetch",
        content=content,
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        metadata={"error": error.to_envelope()} if error is not None else {},
    )


__all__ = ["create_web_fetch_tool", "create_web_search_tool"]
