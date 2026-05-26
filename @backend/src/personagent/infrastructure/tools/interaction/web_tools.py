"""Ferramentas web V1."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpcore
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
            transport = _SafeDNSAsyncHTTPTransport(context)
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_ms / 1000),
                headers={"User-Agent": "PersonAgent-WebFetch/1.0"},
                transport=transport,
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


class _PinnedDNSBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        context: ToolUseContext,
        delegate: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._context = context
        self._delegate = delegate or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        pinned_host = _resolve_pinned_host(host, self._context)
        return await self._delegate.connect_tcp(
            pinned_host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._delegate.connect_unix_socket(
            path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _SafeDNSAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, context: ToolUseContext) -> None:
        super().__init__(trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=20,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedDNSBackend(context),
        )


async def _request_with_redirects(
    client: httpx.AsyncClient,
    url: str,
    context: ToolUseContext,
) -> tuple[httpx.Response, int]:
    current_url = url
    redirect_count = 0
    while True:
        validation = _validate_url(current_url, context)
        if validation is not None:
            raise WebDomainBlockedError(
                validation.message or "URL is blocked.",
                metadata={"url": url, "blocked_url": current_url},
            )
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
    return any(_is_blocked_ip(address) for address in _resolve_host_addresses(hostname))


def _resolve_pinned_host(hostname: str, context: ToolUseContext) -> str:
    addresses = _resolve_host_addresses(hostname)
    if not addresses:
        raise WebDomainBlockedError(
            f"URL host could not be resolved: {hostname}",
            metadata={"host": hostname},
        )
    allow_private_hosts = bool(context.limits.get("web_allow_private_hosts", False))
    blocked_address = next((address for address in addresses if _is_blocked_ip(address)), None)
    if blocked_address and not allow_private_hosts:
        raise WebDomainBlockedError(
            f"URL host resolves to a blocked address: {hostname}",
            metadata={"host": hostname, "address": blocked_address},
        )
    return addresses[0]


def _resolve_host_addresses(hostname: str) -> list[str]:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return [str(ip)]

    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    addresses: list[str] = []
    for result in results:
        address = result[4][0]
        try:
            ipaddress.ip_address(address)
        except ValueError:
            continue
        normalized = str(ipaddress.ip_address(address))
        if normalized not in addresses:
            addresses.append(normalized)
    return addresses


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    )


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
