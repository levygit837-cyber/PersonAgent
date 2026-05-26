"""URL and CDP endpoint helpers for browser infrastructure."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse, urlunparse

from personagent.infrastructure.browser.models import BrowserError, BrowserUnavailableError

_URL_EDGE_NOISE_CHARS = " \t\r\n\f\v\u00a0\u200b\u200c\u200d\ufeff"
_URL_ENCODED_EDGE_NOISE_SUFFIXES = (
    "%c2%a0",
    "%e2%80%8b",
    "%e2%80%8c",
    "%e2%80%8d",
    "%ef%bb%bf",
    "%20",
    "%09",
    "%0a",
    "%0d",
)


def normalize_lightpanda_cdp_endpoint(
    raw_url: str,
    version_payload: Mapping[str, Any] | None = None,
) -> str:
    """Return a websocket endpoint accepted by Playwright connect_over_cdp."""

    trimmed = raw_url.strip().rstrip("/")
    if not trimmed:
        raise BrowserUnavailableError("LIGHTPANDA_CDP_URL is empty.")
    if trimmed.startswith(("ws://", "wss://")):
        return trimmed
    websocket_url = None
    if version_payload is not None:
        websocket_url = version_payload.get("webSocketDebuggerUrl")
    if isinstance(websocket_url, str) and websocket_url.strip():
        parsed_ws = urlparse(websocket_url.strip())
        parsed_raw = urlparse(trimmed)
        if parsed_ws.hostname in {"0.0.0.0", "::"} and parsed_raw.hostname:
            netloc = parsed_raw.hostname
            if parsed_ws.port:
                netloc = f"{netloc}:{parsed_ws.port}"
            return urlunparse((parsed_ws.scheme, netloc, parsed_ws.path, "", parsed_ws.query, ""))
        return websocket_url.strip()

    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"}:
        raise BrowserUnavailableError(
            "LIGHTPANDA_CDP_URL must start with http://, https://, ws:// or wss://."
        )
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))


def infer_search_provider(search_base_url: str) -> str:
    hostname = (urlparse(search_base_url).hostname or "").lower()
    if hostname == "search.yahoo.com" or hostname.endswith(".search.yahoo.com"):
        return "yahoo"
    if hostname == "bing.com" or hostname.endswith(".bing.com"):
        return "bing"
    if hostname.startswith("www.google.") or hostname.startswith("google."):
        return "google"
    return "generic"


def clean_browser_url(raw_url: str) -> str:
    """Trim whitespace/invisible suffixes that search pages often append to hrefs."""

    url = str(raw_url or "").strip(_URL_EDGE_NOISE_CHARS)
    while url:
        lowered = url.lower()
        for suffix in _URL_ENCODED_EDGE_NOISE_SUFFIXES:
            if lowered.endswith(suffix):
                url = url[: -len(suffix)].rstrip(_URL_EDGE_NOISE_CHARS)
                break
        else:
            break
    return url


def normalize_navigation_url(raw_url: str) -> str:
    url = clean_browser_url(raw_url)
    if not url:
        raise BrowserError("A URL is required.")
    if re.match(r"^https?://", url, re.IGNORECASE):
        return url
    return f"https://{url}"


def browser_empty_fallback_html(url: str, title: str = "") -> str:
    safe_url = escape_html(url)
    safe_title = escape_html(title or url or "Browser")
    return (
        "<!doctype html><html><head>"
        f"<title>{safe_title}</title>"
        "<style>"
        "body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;margin:0;padding:24px;"
        "background:#fff;color:#111827;line-height:1.5}"
        ".pa-empty{max-width:620px;margin:10vh auto;border:1px solid #e5e7eb;border-radius:12px;padding:18px}"
        ".pa-url{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#6b7280;word-break:break-all}"
        "</style></head><body><main class='pa-empty'>"
        "<h1>Browser page loaded</h1>"
        "<p>The page reached this URL, but the DOM snapshot was empty after redirects settled.</p>"
        f"<p class='pa-url'>{safe_url}</p>"
        "</main></body></html>"
    )


def escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def clamped_viewport(width: int, height: int) -> tuple[int, int]:
    return min(max(int(width), 320), 2400), min(max(int(height), 240), 1800)


def is_local_lightpanda_endpoint(raw_url: str) -> bool:
    parsed = urlparse(str(raw_url or "").strip())
    return parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def urls_equivalent(first: str, second: str) -> bool:
    first_clean = clean_browser_url(first)
    second_clean = clean_browser_url(second)
    if first_clean == second_clean:
        return True
    first_parsed = urlparse(first_clean)
    second_parsed = urlparse(second_clean)
    return (
        first_parsed.scheme.lower(),
        first_parsed.netloc.lower(),
        first_parsed.path.rstrip("/") or "/",
        first_parsed.query,
    ) == (
        second_parsed.scheme.lower(),
        second_parsed.netloc.lower(),
        second_parsed.path.rstrip("/") or "/",
        second_parsed.query,
    )


def is_retryable_raw_cdp_error(exc: Exception) -> bool:
    if isinstance(exc, (OSError, TimeoutError, asyncio.TimeoutError)):
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "connect call failed",
            "connection refused",
            "connection reset",
            "connection closed",
            "did not receive a valid http response",
        )
    )


def is_target_already_loaded_error(exc: Exception) -> bool:
    return "targetalreadyloaded" in str(exc).replace(" ", "").lower()
