"""HTML + stylesheet pipeline helpers for browser snapshots."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

_LINK_TAG_PATTERN = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HTML_ATTR_PATTERN = re.compile(
    r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'`>]+)"
)
_CSS_URL_PATTERN = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"\s][^)'\"]*)(?P=quote)\)")
_MAX_STYLESHEET_HREFS_PER_PAGE = int(os.getenv("PERSONAGENT_BROWSER_CSS_MAX_HREFS", "32"))

logger = structlog.get_logger(__name__)


async def html_with_embedded_stylesheet_fallbacks(
    worker: Any,
    html: str,
    current_url: str,
) -> tuple[str, dict[str, int]]:
    if not html or not current_url.startswith(("http://", "https://")):
        return html, {
            "stylesheet_count": 0,
            "embedded_stylesheet_count": 0,
            "stylesheet_cached_count": 0,
        }
    hrefs = stylesheet_hrefs(html, current_url, max_hrefs=_MAX_STYLESHEET_HREFS_PER_PAGE)
    if not hrefs:
        return html, {
            "stylesheet_count": 0,
            "embedded_stylesheet_count": 0,
            "stylesheet_cached_count": 0,
        }
    timeout = httpx.Timeout(1.8, connect=0.6)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(fetch_stylesheet_css(worker, client, href) for href in hrefs),
            return_exceptions=True,
        )
    embedded_styles = [
        f"/* PersonAgent embedded stylesheet fallback: {href} */\n{css_text}"
        for href, result in zip(hrefs, results, strict=False)
        for css_text, cache_hit in [result if isinstance(result, tuple) else ("", False)]
        if isinstance(css_text, str) and css_text.strip()
    ]
    cached_count = sum(
        1
        for result in results
        if isinstance(result, tuple) and len(result) >= 2 and bool(result[1]) and isinstance(result[0], str) and result[0].strip()
    )
    stats = {
        "stylesheet_count": len(hrefs),
        "embedded_stylesheet_count": len(embedded_styles),
        "stylesheet_cached_count": cached_count,
    }
    if not embedded_styles:
        return html, stats
    style_block = (
        '<style data-personagent-embedded-css="true">\n'
        + "\n\n".join(embedded_styles)
        + "\n</style>"
    )
    if re.search(r"<head(\s[^>]*)?>", html, flags=re.IGNORECASE):
        return (
            re.sub(
                r"<head(\s[^>]*)?>",
                lambda match: f"{match.group(0)}{style_block}",
                html,
                count=1,
                flags=re.IGNORECASE,
            ),
            stats,
        )
    return f"{style_block}{html}", stats


async def computed_html_snapshot(worker: Any, page: Any, current_url: str) -> str:
    from contextlib import suppress

    from personagent.infrastructure.browser.snapshot.scripts import (
        _COMPUTED_HTML_SNAPSHOT_SCRIPT,
    )
    with suppress(Exception):
        value = await worker._evaluate_page(
            page,
            _COMPUTED_HTML_SNAPSHOT_SCRIPT,
            {"url": current_url},
        )
        if isinstance(value, str):
            return value[:2_000_000]
    return ""


def stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
    hrefs: list[str] = []
    for tag_match in _LINK_TAG_PATTERN.finditer(html):
        attrs = html_attrs(str(tag_match.group(0) or ""))
        href = str(attrs.get("href") or "").strip()
        if not href:
            continue
        rel = str(attrs.get("rel") or "").lower()
        as_attr = str(attrs.get("as") or "").lower()
        parsed_path = urlparse(href).path.lower()
        looks_like_stylesheet = (
            "stylesheet" in rel
            or as_attr == "style"
            or parsed_path.endswith(".css")
            or ".css" in parsed_path
        )
        if not looks_like_stylesheet:
            continue
        absolute = urljoin(current_url, href)
        if absolute.startswith(("http://", "https://")) and absolute not in hrefs:
            hrefs.append(absolute)
        if len(hrefs) >= max_hrefs:
            break
    return hrefs


def html_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _HTML_ATTR_PATTERN.finditer(tag):
        name = str(match.group("name") or "").lower()
        value = str(match.group("value") or "")
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        attrs[name] = value
    return attrs


async def fetch_stylesheet_css(worker: Any, client: httpx.AsyncClient, href: str) -> tuple[str, bool]:
    now = time.time()
    cached = worker._stylesheet_cache.get(href)
    if cached is not None and cached[0] > now:
        return cached[1], True
    disk_cached = worker._stylesheet_disk_cache.read(href, now=now)
    if disk_cached:
        worker._stylesheet_cache[href] = (now + worker._stylesheet_cache_ttl_seconds, disk_cached)
        return disk_cached, True
    response = await client.get(href)
    if response.status_code >= 400:
        return "", False
    content_type = response.headers.get("content-type", "")
    css_text = response.text
    if "css" not in content_type.lower() and "{" not in css_text[:1000]:
        return "", False
    css_text = rewrite_css_urls(css_text[:350_000], href)
    worker._stylesheet_cache[href] = (now + worker._stylesheet_cache_ttl_seconds, css_text)
    worker._stylesheet_disk_cache.write(href, css_text, expires_at=now + worker._stylesheet_cache_ttl_seconds)
    if len(worker._stylesheet_cache) > worker._max_stylesheet_cache_entries:
        expired = [key for key, (expires_at, _) in worker._stylesheet_cache.items() if expires_at <= now]
        for key in expired:
            worker._stylesheet_cache.pop(key, None)
        while len(worker._stylesheet_cache) > worker._max_stylesheet_cache_entries:
            worker._stylesheet_cache.pop(next(iter(worker._stylesheet_cache)))
    return css_text, False


def rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_url = str(match.group("url") or "").strip()
        quote = str(match.group("quote") or "")
        if not raw_url or raw_url.startswith(("data:", "http://", "https://", "#")):
            return match.group(0)
        return f"url({quote}{urljoin(stylesheet_url, raw_url)}{quote})"

    return _CSS_URL_PATTERN.sub(replace, css_text)


def css_fidelity(*, html: str, render_mode: str, embedded_stylesheet_count: int = 0) -> str:
    if render_mode in {"screenshot", "pixel"}:
        return "pixel"
    if render_mode == "computed_html":
        return "computed"
    if not html.strip():
        return "fallback_html"
    if embedded_stylesheet_count > 0:
        return "embedded"
    lowered = html.lower()
    if (
        'rel="stylesheet"' in lowered
        or "rel='stylesheet'" in lowered
        or "as=\"style\"" in lowered
        or "as='style'" in lowered
        or "<style" in lowered
    ):
        return "original"
    return "fallback_html"
