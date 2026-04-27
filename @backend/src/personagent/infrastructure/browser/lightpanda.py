"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

Connector = Callable[[str], Awaitable[Any]]

_DEFAULT_SEARCH_BASE_URL = "https://search.yahoo.com/search"
_MAX_CACHED_SEARCHES_PER_CONVERSATION = 8
_MAX_OPENED_PAGES_PER_CONVERSATION = 32
_MARKDOWN_ANY_LINK_PATTERN = re.compile(r"\[([^\]]*)]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*]\([^)]*\)")
_MIN_READABLE_CONTENT_CHARS = 240
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
_RAW_CDP_RETRY_DELAYS = (0.0, 0.5, 1.5, 3.0, 5.0)
_NOISE_LINE_MARKERS = {
    "advertise",
    "advertisement",
    "all rights reserved",
    "cookie policy",
    "copyright",
    "follow us",
    "forbes logo",
    "privacy policy",
    "see all",
    "see more",
    "share a news tip",
    "sign in",
    "sign up",
    "sign up for newsletters",
    "subscribe",
    "terms of service",
}
_NOISE_LINE_SUBSTRINGS = (
    "crown each region",
    "frase by forbes",
    "guess the category",
    "mini crossword",
    "pinpoint by linkedin",
    "quick solve. big win",
    "queens by linkedin",
    "unscramble the anagram",
)
_READABLE_DOM_SCRIPT = r"""
(() => {
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const body = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
  const removeSelectors = [
    'script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe',
    'nav', 'header', 'footer', 'aside',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    'form', 'button'
  ];
  body.querySelectorAll(removeSelectors.join(',')).forEach((el) => el.remove());
  const noisyMeta = /(cookie|newsletter|subscribe|advert|promo|share|social|related|recommend|most-popular|trending|nav|menu|footer|header|sidebar)/i;
  Array.from(body.querySelectorAll('*')).forEach((el) => {
    const meta = `${el.id || ''} ${typeof el.className === 'string' ? el.className : ''} ${el.getAttribute('aria-label') || ''}`;
    if (!noisyMeta.test(meta)) return;
    const textLength = normalize(el.textContent).length;
    const linkCount = el.querySelectorAll('a[href]').length;
    if (textLength < 1400 || linkCount >= 8) el.remove();
  });
  const selectors = [
    'article',
    'main',
    '[role="main"]',
    '[itemprop="articleBody"]',
    '.article-body',
    '.articleBody',
    '.story-body',
    '.entry-content',
    '.post-content',
    '.post__content',
    '.content-body',
    '.body-content',
    '.article-content'
  ];
  const candidates = Array.from(body.querySelectorAll(selectors.join(',')));
  if (!candidates.includes(body)) candidates.push(body);
  const textFor = (node) => {
    const pieces = [];
    const seen = new Set();
    node.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,figcaption,td,th').forEach((el) => {
      const text = normalize(el.textContent);
      if (text.length < 2 || seen.has(text)) return;
      seen.add(text);
      pieces.push(text);
    });
    const structured = pieces.join('\n\n');
    if (structured.length >= 300) return structured;
    return normalize(node.textContent);
  };
  const scoreFor = (node) => {
    const text = textFor(node);
    const linkCount = node.querySelectorAll('a[href]').length;
    const paragraphCount = node.querySelectorAll('p').length;
    const headingCount = node.querySelectorAll('h1,h2,h3').length;
    return text.length + paragraphCount * 180 + headingCount * 100 - linkCount * 90;
  };
  let best = candidates[0] || body;
  let bestScore = -Infinity;
  for (const candidate of candidates) {
    const score = scoreFor(candidate);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  const content = textFor(best);
  const links = Array.from(best.querySelectorAll('a[href]')).map((a) => ({
    url: a.href || a.getAttribute('href') || '',
    text: normalize(a.textContent)
  })).filter((item) => /^https?:\/\//i.test(item.url)).slice(0, 80);
  return {
    title: normalize(document.title),
    content,
    link_count: links.length,
    selected_tag: best.tagName ? best.tagName.toLowerCase() : 'body',
    score: bestScore
  };
})()
"""


class BrowserError(RuntimeError):
    """Base error for browser infrastructure failures."""


class BrowserUnavailableError(BrowserError):
    """Raised when the browser service cannot be used."""


class BrowserBlockedError(BrowserError):
    """Raised when the target site blocks browser automation."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        reason: str = "",
        url: str = "",
        title: str = "",
        sample: str = "",
    ) -> None:
        super().__init__(message)
        self.details = {
            "provider": provider,
            "reason": reason,
            "url": url,
            "title": title,
            "sample": sample,
        }


@dataclass(slots=True)
class BrowserSearchResult:
    """Search result stored in a conversation browser session."""

    index: int
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }


@dataclass(slots=True)
class BrowserSearchSnapshot:
    """Recent search results kept independently from the live browser page."""

    search_id: str
    query: str
    search_url: str
    provider: str
    results: list[BrowserSearchResult]
    created_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class BrowserOpenedPage:
    """Logical browser page opened during a conversation research session."""

    page_id: str
    url: str
    final_url: str
    title: str = ""
    source_search_id: str | None = None
    opener_tool_call_id: str | None = None
    opened_at: float = field(default_factory=time.monotonic)
    extraction_count: int = 0
    last_extracted_at: float | None = None

    @property
    def window_id(self) -> str:
        """Public browser-window identifier. Kept equal to page_id for compatibility."""

        return self.page_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "window_id": self.window_id,
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "source_search_id": self.source_search_id,
            "opener_tool_call_id": self.opener_tool_call_id,
            "extraction_count": self.extraction_count,
        }


@dataclass(slots=True)
class _BrowserSession:
    browser: Any
    context: Any
    page: Any
    pages: dict[str, Any] = field(default_factory=dict)
    search_results: list[BrowserSearchResult] = field(default_factory=list)
    current_url: str | None = None
    last_open_url: str | None = None
    last_open_page_id: str | None = None
    current_page_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.updated_at = time.monotonic()


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


def _infer_search_provider(search_base_url: str) -> str:
    hostname = (urlparse(search_base_url).hostname or "").lower()
    if hostname == "search.yahoo.com" or hostname.endswith(".search.yahoo.com"):
        return "yahoo"
    if hostname == "bing.com" or hostname.endswith(".bing.com"):
        return "bing"
    if hostname.startswith("www.google.") or hostname.startswith("google."):
        return "google"
    return "generic"


def _search_results_script(provider: str) -> str:
    if provider == "yahoo":
        return _YAHOO_RESULTS_SCRIPT
    if provider == "bing":
        return _BING_RESULTS_SCRIPT
    if provider == "google":
        return _GOOGLE_RESULTS_SCRIPT
    return _GENERIC_RESULTS_SCRIPT


def _clean_browser_url(raw_url: str) -> str:
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


def _urls_equivalent(first: str, second: str) -> bool:
    first_clean = _clean_browser_url(first)
    second_clean = _clean_browser_url(second)
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


def _is_retryable_raw_cdp_error(exc: Exception) -> bool:
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


def _clean_extracted_content(raw_content: str) -> tuple[str, dict[str, Any]]:
    """Remove navigation/link-list noise while preserving article text."""

    raw = str(raw_content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = _MARKDOWN_IMAGE_PATTERN.sub("", raw)
    raw_link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(raw)) + len(_URL_PATTERN.findall(raw))
    if not raw:
        return "", {
            "raw_chars": 0,
            "cleaned_chars": 0,
            "raw_link_count": 0,
            "removed_link_noise_blocks": 0,
        }

    kept_blocks: list[str] = []
    removed_blocks = 0
    for block in re.split(r"\n\s*\n+", raw):
        cleaned_block = _clean_content_block(block)
        if not cleaned_block:
            continue
        if _is_link_noise_block(block):
            removed_blocks += 1
            continue
        kept_blocks.append(cleaned_block)

    cleaned = "\n\n".join(kept_blocks)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if _should_keep_raw_content(raw, cleaned, raw_link_count):
        cleaned = _collapse_text_spacing(raw)
    return cleaned, {
        "raw_chars": len(raw),
        "cleaned_chars": len(cleaned),
        "raw_link_count": raw_link_count,
        "removed_link_noise_blocks": removed_blocks,
    }


def _clean_content_block(block: str) -> str:
    lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = _MARKDOWN_ANY_LINK_PATTERN.sub(lambda match: match.group(1).strip(), line)
        line = _URL_PATTERN.sub("", line)
        line = re.sub(r"^[\-*+]\s+", "", line)
        line = _collapse_text_spacing(line)
        if not line or _is_noise_line(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_link_noise_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False
    link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(block)) + len(_URL_PATTERN.findall(block))
    if link_count < 6:
        return False
    link_only_lines = sum(1 for line in lines if _is_link_only_line(line))
    if link_only_lines / max(1, len(lines)) >= 0.55:
        return True
    text_without_links = _MARKDOWN_ANY_LINK_PATTERN.sub("", block)
    text_without_links = _URL_PATTERN.sub("", text_without_links)
    non_link_chars = len(_collapse_text_spacing(text_without_links))
    return link_count >= 12 and non_link_chars < link_count * 24


def _is_link_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(stripped)) + len(_URL_PATTERN.findall(stripped))
    if link_count == 0:
        return False
    without_links = _MARKDOWN_ANY_LINK_PATTERN.sub("", stripped)
    without_links = _URL_PATTERN.sub("", without_links)
    without_links = re.sub(r"^[\-*+]\s*", "", without_links)
    return len(_collapse_text_spacing(without_links)) <= 12


def _is_noise_line(line: str) -> bool:
    normalized = _collapse_text_spacing(line).strip(" :-|").lower()
    if not normalized:
        return True
    if not any(char.isalnum() for char in normalized):
        return True
    if normalized in _NOISE_LINE_MARKERS:
        return True
    if any(marker in normalized for marker in _NOISE_LINE_SUBSTRINGS):
        return True
    return len(normalized) <= 4 and normalized in {"ad", "ads", "new", "more"}


def _should_keep_raw_content(raw: str, cleaned: str, raw_link_count: int) -> bool:
    if len(cleaned) >= _MIN_READABLE_CONTENT_CHARS:
        return False
    if raw_link_count >= 12:
        return False
    return len(raw) > len(cleaned)


def _should_prefer_readable_dom(cleaned: str, stats: dict[str, Any]) -> bool:
    raw_link_count = int(stats.get("raw_link_count") or 0)
    removed_blocks = int(stats.get("removed_link_noise_blocks") or 0)
    cleaned_chars = len(cleaned)
    if cleaned_chars < _MIN_READABLE_CONTENT_CHARS:
        return True
    return bool(raw_link_count >= 40 and removed_blocks)


def _collapse_text_spacing(value: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", str(value or "")).strip()


class LightPandaBrowserWorker:
    """Keeps one CDP browser connection and per-conversation pages."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_ms: int = 30_000,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
        session_ttl_seconds: int = 900,
        max_sessions: int = 32,
        connector: Connector | None = None,
    ) -> None:
        self.enabled = enabled
        self.cdp_url = cdp_url
        self.timeout_ms = max(1, int(timeout_ms))
        self.search_base_url = search_base_url or _DEFAULT_SEARCH_BASE_URL
        self.search_provider = _infer_search_provider(self.search_base_url)
        self.session_ttl_seconds = max(1, int(session_ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self._connector = connector
        self._lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._playwright: Any | None = None
        self._sessions: dict[str, _BrowserSession] = {}
        self._search_cache: dict[str, list[BrowserSearchSnapshot]] = {}
        self._current_url_cache: dict[str, str] = {}
        self._last_open_cache: dict[str, BrowserOpenedPage] = {}
        self._opened_pages_cache: dict[str, list[BrowserOpenedPage]] = {}

    async def warmup(self) -> bool:
        """Best-effort startup connection. Failures are logged, not raised."""

        try:
            browser = await self._connect_browser()
        except BrowserError as exc:
            logger.warning("lightpanda_warmup_failed", error=str(exc))
            return False
        await self._release_browser(browser)
        return True

    async def close(self) -> None:
        """Close pages, contexts, browser and Playwright runtime."""

        async with self._lock:
            await self._close_sessions()
            if self._playwright is not None:
                await self._best_effort_resource_call(
                    "playwright_stop",
                    self._playwright.stop,
                )
                self._playwright = None
            self._search_cache.clear()
            self._current_url_cache.clear()
            self._last_open_cache.clear()
            self._opened_pages_cache.clear()

    @property
    def search_provider_label(self) -> str:
        return {
            "yahoo": "Yahoo",
            "bing": "Bing",
            "google": "Google",
            "generic": "the configured search provider",
        }.get(self.search_provider, self.search_provider)

    async def search(
        self,
        *,
        conversation_id: str,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        """Search the configured search provider in the conversation browser session."""

        session = await self._get_session(conversation_id)
        search_url = self.search_url(query, max_results=max_results)
        resolved_search_url = search_url
        search_page = await self._new_session_page(session)
        if search_page is not None:
            try:
                await self._goto_page(search_page, search_url)
                await self._raise_if_search_blocked(search_page)
                extracted = await self._evaluate_page(
                    search_page,
                    _search_results_script(self.search_provider),
                    {"maxResults": max_results},
                )
                resolved_search_url = str(getattr(search_page, "url", search_url) or search_url)
            finally:
                if search_page is not session.page:
                    await self._best_effort_resource_call(
                        "browser_search_page_close",
                        search_page.close,
                    )
        else:
            expression = (
                f"({_search_results_script(self.search_provider)})"
                f"({json.dumps({'maxResults': max_results})})"
            )
            extracted = await self._raw_runtime_evaluate_value(
                search_url,
                expression,
                label="search_results",
                timeout=min(self.timeout_ms / 1000, 12),
            )
        results = [
            BrowserSearchResult(
                index=index + 1,
                title=str(item.get("title") or "").strip(),
                url=_clean_browser_url(str(item.get("url") or "")),
                snippet=str(item.get("snippet") or "").strip(),
            )
            for index, item in enumerate(extracted or [])
            if isinstance(item, dict)
            and item.get("title")
            and _clean_browser_url(str(item.get("url") or ""))
        ][:max_results]
        snapshot = self._cache_search_results(
            conversation_id=conversation_id,
            query=query,
            search_url=resolved_search_url,
            results=results,
        )
        session.search_results = self._copy_search_results(snapshot.results)
        session.current_url = resolved_search_url
        self._remember_current_url(conversation_id, session.current_url)
        session.touch()
        return {
            "type": "browser_search",
            "provider": self.search_provider,
            "query": query,
            "search_url": resolved_search_url,
            "search_id": snapshot.search_id,
            "cached_search_count": len(self._search_cache.get(conversation_id, [])),
            "results": [
                {**result.to_dict(), "search_id": snapshot.search_id} for result in snapshot.results
            ],
        }

    async def open(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        result_index: int | None = None,
        search_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        """Open a URL or one of the last search results."""

        session = await self._get_session(conversation_id)
        target_url = _clean_browser_url(url) if isinstance(url, str) else url
        matched_search_id = None
        if target_url is None and result_index is not None:
            target_url, matched_search_id = self._result_url(
                conversation_id,
                session,
                result_index,
                search_id=search_id,
            )
        elif target_url and search_id:
            matched_search_id = self._match_search_result_url(
                conversation_id,
                target_url,
                search_id=search_id,
            )
        if target_url is None:
            raise BrowserError("BrowserOpen requires url or result_index.")
        page = await self._new_session_page(session)
        if page is not None:
            try:
                await self._goto_page(page, target_url, allow_partial=True)
                await self._raise_if_search_blocked(page)
            except Exception:
                await self._best_effort_resource_call("browser_open_failed_page_close", page.close)
                raise
            title = await self._safe_title(page)
            final_url = str(getattr(page, "url", target_url) or target_url)
        else:
            final_url = target_url
            title = await self._safe_title_for_url(target_url)
        session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        opened_page = self._cache_opened_page(
            conversation_id=conversation_id,
            url=target_url,
            final_url=final_url,
            title=title,
            source_search_id=matched_search_id,
            opener_tool_call_id=tool_call_id,
        )
        if page is not None:
            session.pages[opened_page.page_id] = page
            session.page = page
        session.last_open_url = opened_page.final_url
        session.last_open_page_id = opened_page.page_id
        session.current_page_id = opened_page.page_id
        session.touch()
        return {
            "type": "browser_open",
            "url": target_url,
            "final_url": final_url,
            "title": title,
            "search_id": matched_search_id,
            "page_id": opened_page.page_id,
            "window_id": opened_page.window_id,
            "opened_page_count": len(self._opened_pages_cache.get(conversation_id, [])),
            "recent_opened_pages": [
                page.to_dict() for page in self._opened_pages_cache.get(conversation_id, [])[:5]
            ],
        }

    async def extract_content(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        """Return organized markdown/text content for the current or provided URL."""

        session = self._cached_usable_session(conversation_id)
        target_url, target_page_id = self._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._get_session(conversation_id)
            target_url, target_page_id = self._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        title = self._target_title(conversation_id, target_page_id)
        if not title and session is not None:
            title = await self._safe_title(session.page)
        final_url = _clean_browser_url(str(target_url))
        content, extraction_method, content_cleanup = await self._markdown_or_text_url(final_url)
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip()
        links = self._extract_links_from_content(content) if include_links else []
        buttons: list[dict[str, str]] = []
        if session is not None:
            session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        opened_page = self._opened_page(conversation_id, target_page_id) if target_page_id else None
        if opened_page is not None:
            if session is not None:
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
            self._mark_opened_page_extracted(opened_page)
        if session is not None:
            session.touch()
        return {
            "type": "browser_extract_content",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "content": content,
            "extraction_method": extraction_method,
            "content_cleanup": content_cleanup,
            "links": links,
            "buttons": buttons,
            "truncated": truncated,
        }

    async def get_html(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
    ) -> dict[str, Any]:
        """Return raw HTML for the current or provided URL."""

        session = self._cached_usable_session(conversation_id)
        target_url, target_page_id = self._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._get_session(conversation_id)
            target_url, target_page_id = self._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        title = self._target_title(conversation_id, target_page_id)
        if not title and session is not None:
            title = await self._safe_title(session.page)
        final_url = _clean_browser_url(str(target_url))
        html, html_method = await self._html_or_empty_url(final_url)
        truncated = len(html) > max_chars
        if truncated:
            html = html[:max_chars].rstrip()
        if session is not None:
            session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        if session is not None and target_page_id:
            opened_page = self._opened_page(conversation_id, target_page_id)
            if opened_page is not None:
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
        if session is not None:
            session.touch()
        return {
            "type": "browser_get_html",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "html": html,
            "html_method": html_method,
            "truncated": truncated,
        }

    async def list_tabs(
        self,
        *,
        conversation_id: str,
        max_tabs: int,
    ) -> dict[str, Any]:
        """Return logical browser tabs opened during the conversation."""

        await self._cleanup_sessions()
        max_tabs = min(max(1, int(max_tabs)), 50)
        session = self._sessions.get(conversation_id)
        current_url = self._current_url_cache.get(conversation_id)
        if session is not None:
            current_url = session.current_url or current_url
        last_open = self._last_open_cache.get(conversation_id)
        pages = self._opened_pages_cache.get(conversation_id, [])[:max_tabs]
        tabs = [
            self._opened_page_tab(
                page,
                index=index,
                current_url=current_url,
                last_open_page_id=last_open.page_id if last_open is not None else None,
            )
            for index, page in enumerate(pages, start=1)
        ]
        return {
            "type": "browser_tabs",
            "tab_count": len(tabs),
            "max_tabs": max_tabs,
            "current_url": current_url,
            "last_open_page_id": last_open.page_id if last_open is not None else None,
            "last_open_window_id": last_open.window_id if last_open is not None else None,
            "tabs": tabs,
        }

    def search_url(self, query: str, *, max_results: int | None = None) -> str:
        parsed = urlparse(self.search_base_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if self.search_provider == "yahoo":
            params["p"] = query
            params.pop("q", None)
        else:
            params["q"] = query
        if self.search_provider == "google":
            params.update(
                {
                    "hl": params.get("hl") or "en",
                    "gl": params.get("gl") or "us",
                    "pws": params.get("pws") or "0",
                }
            )
        elif self.search_provider == "bing":
            params.update(
                {
                    "setlang": params.get("setlang") or "en-US",
                    "cc": params.get("cc") or "US",
                }
            )
        if max_results is not None:
            result_count = str(min(max(1, int(max_results)), 10))
            if self.search_provider == "bing":
                params["count"] = result_count
            elif self.search_provider == "yahoo":
                params["pz"] = result_count
            else:
                params["num"] = result_count
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(params),
                parsed.fragment,
            )
        )

    async def _get_session(self, conversation_id: str) -> _BrowserSession:
        async with self._sessions_lock:
            await self._cleanup_sessions()
            session = self._sessions.get(conversation_id)
            if session is not None:
                try:
                    browser_connected = True
                    is_connected = getattr(session.browser, "is_connected", None)
                    if callable(is_connected):
                        browser_connected = bool(is_connected())
                    if browser_connected and self._session_has_open_page(session):
                        session.page = self._preferred_session_page(session)
                        cached_results = self._latest_cached_search_results(conversation_id)
                        if cached_results:
                            session.search_results = cached_results
                        else:
                            session.search_results = []
                        session.current_url = session.current_url or self._current_url_cache.get(
                            conversation_id
                        )
                        last_open = self._last_open_cache.get(conversation_id)
                        if last_open is not None:
                            session.last_open_url = session.last_open_url or last_open.final_url
                            session.last_open_page_id = session.last_open_page_id or last_open.page_id
                        session.touch()
                        return session
                except Exception:
                    await self._close_session(conversation_id, session)
                    session = None
                if session is not None:
                    await self._close_session(conversation_id, session)

            browser = await self._connect_browser()
            try:
                context = await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(self.timeout_ms)
                last_open = self._last_open_cache.get(conversation_id)
                session = _BrowserSession(
                    browser=browser,
                    context=context,
                    page=page,
                    search_results=self._latest_cached_search_results(conversation_id),
                    current_url=self._current_url_cache.get(conversation_id),
                    last_open_url=last_open.final_url if last_open is not None else None,
                    last_open_page_id=last_open.page_id if last_open is not None else None,
                    current_page_id=last_open.page_id if last_open is not None else None,
                )
                self._sessions[conversation_id] = session
                await self._enforce_session_limit()
                return session
            except Exception as exc:
                await self._release_browser(browser)
                raise BrowserUnavailableError(
                    f"Could not create a LightPanda browser session: {exc}"
                ) from exc

    async def _ensure_browser(self) -> Any:
        """Open one CDP browser connection.

        LightPanda currently does not behave like Chromium when many contexts are
        created on the same Playwright CDP connection. The worker therefore keeps
        the singleton at the worker level, but each conversation session owns its
        own CDP connection.
        """

        return await self._connect_browser()

    def _cached_usable_session(self, conversation_id: str) -> _BrowserSession | None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return None
        try:
            browser_connected = True
            is_connected = getattr(session.browser, "is_connected", None)
            if callable(is_connected):
                browser_connected = bool(is_connected())
            if browser_connected and self._session_has_open_page(session):
                session.page = self._preferred_session_page(session)
                return session
        except Exception:
            pass
        self._sessions.pop(conversation_id, None)
        return None

    def _session_has_open_page(self, session: _BrowserSession) -> bool:
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return True
        return False

    def _preferred_session_page(self, session: _BrowserSession) -> Any:
        if session.current_page_id:
            page = session.pages.get(session.current_page_id)
            if page is not None:
                with suppress(Exception):
                    if not page.is_closed():
                        return page
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return session.page

    def _session_pages(self, session: _BrowserSession) -> list[Any]:
        pages: list[Any] = []
        seen: set[int] = set()
        for page in (session.page, *session.pages.values()):
            marker = id(page)
            if marker in seen:
                continue
            seen.add(marker)
            pages.append(page)
        return pages

    async def _connect_browser(self) -> Any:
        if not self.enabled:
            raise BrowserUnavailableError("LightPanda browser tools are disabled.")
        last_error: Exception | None = None
        for attempt in range(3):
            endpoint = await self._resolve_endpoint()
            try:
                if self._connector is not None:
                    return await self._connector(endpoint)
                return await self._connect_with_playwright(endpoint)
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        raise BrowserUnavailableError(
            "Browser CDP endpoint is unavailable. Start LightPanda with "
            "`docker compose up -d lightpanda` or start Chrome/Chromium with "
            "`--remote-debugging-port=9222`, then verify /json/version."
        ) from last_error

    async def _connect_with_playwright(self, endpoint: str) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `playwright` is required for LightPanda browser tools."
            ) from exc

        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            playwright = self._playwright
        return await playwright.chromium.connect_over_cdp(
            endpoint,
            timeout=self.timeout_ms,
        )

    async def _new_session_page(self, session: _BrowserSession) -> Any | None:
        try:
            page = await session.context.new_page()
        except Exception as exc:
            if "TargetAlreadyLoaded" in str(exc):
                logger.debug("lightpanda_new_page_unavailable", error=str(exc))
                return None
            raise
        with suppress(Exception):
            page.set_default_timeout(self.timeout_ms)
        return page

    async def _resolve_endpoint(self) -> str:
        version_payload = None
        if self.cdp_url.strip().startswith(("http://", "https://")):
            with suppress(Exception):
                async with httpx.AsyncClient(timeout=self.timeout_ms / 1000) as client:
                    response = await client.get(f"{self.cdp_url.rstrip('/')}/json/version")
                    response.raise_for_status()
                    version_payload = response.json()
        return normalize_lightpanda_cdp_endpoint(self.cdp_url, version_payload)

    async def _goto(
        self,
        conversation_id: str,
        session: _BrowserSession,
        url: str,
        *,
        allow_partial: bool = False,
    ) -> None:
        try:
            await self._goto_page(session.page, url, allow_partial=allow_partial)
        except Exception:
            await self._close_session(conversation_id, session)
            raise

    async def _goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
    ) -> None:
        clean_url = _clean_browser_url(url)
        try:
            await page.goto(
                clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms
            )
            await page.wait_for_timeout(250)
        except Exception as exc:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if allow_partial and page_url.startswith(("http://", "https://")):
                logger.warning(
                    "lightpanda_navigation_partial",
                    url=clean_url,
                    page_url=page_url,
                    error=str(exc),
                )
                return
            if "RobotsBlocked" in str(exc):
                raise BrowserBlockedError(
                    "LightPanda blocked navigation because `--obey-robots` is enabled.",
                    provider=urlparse(clean_url).hostname or "",
                    reason="robots_txt",
                    url=clean_url,
                ) from exc
            raise BrowserUnavailableError(
                f"LightPanda navigation failed for {clean_url}: {exc}"
            ) from exc

    async def _evaluate_page(
        self,
        page: Any,
        script: str,
        arg: Any | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if arg is None:
                    return await page.evaluate(script)
                return await page.evaluate(script, arg)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "Execution context was destroyed" not in message:
                    raise
                if attempt == 2:
                    break
                with suppress(Exception):
                    await page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(self.timeout_ms, 5_000),
                    )
                with suppress(Exception):
                    await page.wait_for_timeout(250)
        if last_error is not None:
            raise last_error
        return None

    async def _markdown_or_text(self, session: _BrowserSession) -> tuple[str, str, dict[str, Any]]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._markdown_or_text_url(url)

    async def _markdown_or_text_url(self, url: str) -> tuple[str, str, dict[str, Any]]:
        markdown = await self._lightpanda_markdown_url(url)
        if markdown:
            cleaned_markdown, stats = _clean_extracted_content(markdown)
            if _should_prefer_readable_dom(cleaned_markdown, stats):
                readable = await self._readable_dom_content_url(url)
                if readable:
                    return readable, "readable_dom_text", {
                        **stats,
                        "fallback": "readable_dom_text",
                    }
            if cleaned_markdown:
                method = (
                    "lightpanda_markdown_cleaned"
                    if stats.get("removed_link_noise_blocks")
                    else "lightpanda_markdown"
                )
                return cleaned_markdown, method, stats
        readable = await self._readable_dom_content_url(url)
        if readable:
            return readable, "readable_dom_text", {}
        text = await self._raw_runtime_evaluate_value(
            url,
            "(document.body && (document.body.innerText || document.body.textContent)) "
            "|| document.documentElement.textContent || ''",
            label="dom_text",
            timeout=min(self.timeout_ms / 1000, 5),
        )
        if not isinstance(text, str):
            return "", "dom_text_failed", {}
        cleaned_text, stats = _clean_extracted_content(text)
        return cleaned_text, "dom_text", stats

    async def _readable_dom_content_url(self, url: str) -> str:
        value = await self._raw_runtime_evaluate_value(
            url,
            _READABLE_DOM_SCRIPT,
            label="readable_dom",
            timeout=min(self.timeout_ms / 1000, 8),
        )
        if not isinstance(value, dict):
            return ""
        content = value.get("content")
        if not isinstance(content, str):
            return ""
        cleaned, _stats = _clean_extracted_content(content)
        return cleaned

    async def _lightpanda_markdown(self, session: _BrowserSession) -> str:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._lightpanda_markdown_url(url)

    async def _lightpanda_markdown_url(self, url: str) -> str:
        url = _clean_browser_url(url)
        if not url or url == "about:blank":
            return ""
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="LP.getMarkdown",
                ),
                timeout=min(self.timeout_ms / 1000, 15),
            )
            markdown = self._extract_markdown_payload(payload)
            if markdown:
                return markdown
        except TimeoutError as exc:
            logger.warning("lightpanda_markdown_raw_timeout", error=str(exc), url=url)
            return ""
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        return ""

    def _extract_markdown_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("markdown", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str):
            return payload
        return ""

    async def _raw_runtime_evaluate_value(
        self,
        url: str,
        expression: str,
        *,
        label: str,
        timeout: float,
    ) -> Any:
        if not url or url == "about:blank":
            return None
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="Runtime.evaluate",
                    params={
                        "expression": expression,
                        "returnByValue": True,
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_timeout", label=label, error=str(exc))
            return None
        except Exception as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_failed", label=label, error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return result.get("value")

    async def _html_or_empty(self, session: _BrowserSession) -> tuple[str, str]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._html_or_empty_url(url)

    async def _html_or_empty_url(self, url: str) -> tuple[str, str]:
        url = _clean_browser_url(url)
        value = await self._raw_runtime_evaluate_value(
            url,
            "document.documentElement ? document.documentElement.outerHTML : ''",
            label="html",
            timeout=min(self.timeout_ms / 1000, 10),
        )
        if isinstance(value, str):
            return value, "raw_cdp_runtime_evaluate"
        return "", "raw_cdp_runtime_unavailable"

    async def _lightpanda_raw_cdp_command(
        self,
        *,
        url: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            import websockets
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `websockets` is required for LightPanda native CDP commands."
            ) from exc

        timeout_seconds = self.timeout_ms / 1000
        last_error: Exception | None = None
        for attempt, delay in enumerate(_RAW_CDP_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                endpoint = await self._resolve_endpoint()
                async with websockets.connect(
                    endpoint,
                    open_timeout=timeout_seconds,
                    close_timeout=min(timeout_seconds, 5),
                    max_size=8 * 1024 * 1024,
                ) as websocket:
                    client = _RawCdpClient(websocket)
                    created = await client.send("Target.createTarget", {"url": "about:blank"})
                    target_id = str(created.get("targetId") or "")
                    attached = await client.send(
                        "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True},
                    )
                    session_id = str(attached.get("sessionId") or "")
                    try:
                        with suppress(Exception):
                            await client.send("Page.enable", session_id=session_id)
                        await client.send("Page.navigate", {"url": url}, session_id=session_id)
                        with suppress(TimeoutError, asyncio.TimeoutError):
                            await client.wait_for_event(
                                "Page.domContentEventFired",
                                session_id=session_id,
                                timeout=timeout_seconds,
                            )
                        await asyncio.sleep(0.25)
                        return await client.send(method, params or {}, session_id=session_id)
                    finally:
                        if target_id:
                            with suppress(Exception):
                                await client.send("Target.closeTarget", {"targetId": target_id})
            except Exception as exc:
                last_error = exc
                if attempt == len(_RAW_CDP_RETRY_DELAYS) - 1 or not _is_retryable_raw_cdp_error(
                    exc
                ):
                    raise
                logger.debug(
                    "lightpanda_raw_cdp_retry",
                    attempt=attempt + 1,
                    method=method,
                    url=url,
                    error=str(exc),
                )
        if last_error is not None:
            raise last_error
        raise BrowserUnavailableError("LightPanda raw CDP command failed.")

    def _extract_links_from_content(self, content: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in _MARKDOWN_LINK_PATTERN.finditer(content):
            text = " ".join(match.group(1).split())
            url = match.group(2).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"url": url, "text": text})
            if len(links) >= 50:
                break
        return links

    async def _safe_title(self, page: Any) -> str:
        try:
            title = await asyncio.wait_for(
                page.title(),
                timeout=min(self.timeout_ms / 1000, 3),
            )
            return str(title or "").strip()
        except TimeoutError as exc:
            logger.warning("lightpanda_title_timeout", error=str(exc))
            return ""
        except Exception:
            return ""

    async def _safe_title_for_url(self, url: str) -> str:
        value = await self._raw_runtime_evaluate_value(
            url,
            "document.title || ''",
            label="title",
            timeout=min(self.timeout_ms / 1000, 5),
        )
        return str(value or "").strip() if isinstance(value, str) else ""

    async def _raise_if_google_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "sorry/index" not in page_url and "google." not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_google_surface = "google." in page_url or "google" in title
        if "sorry/index" not in page_url and not is_google_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "our systems have detected",
            "before you continue",
            "consent.google",
            "enable javascript on your web browser",
        )
        if "sorry/index" in page_url or (
            is_google_surface and any(marker in sample or marker in title for marker in markers)
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Google blocked this browser session with consent, CAPTCHA, or unusual-traffic checks. "
                "This is a Google/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="google",
                reason="captcha_or_unusual_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_bing_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "bing.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_bing_surface = "bing.com" in page_url or "bing" in title
        if not is_bing_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
            "solve this puzzle",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Bing blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="bing",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_yahoo_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "search.yahoo.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_yahoo_surface = "search.yahoo.com" in page_url or "yahoo search" in title
        if not is_yahoo_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Yahoo blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="yahoo",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_search_blocked(self, page: Any) -> None:
        await self._raise_if_google_blocked(page)
        await self._raise_if_bing_blocked(page)
        await self._raise_if_yahoo_blocked(page)

    def _cache_search_results(
        self,
        *,
        conversation_id: str,
        query: str,
        search_url: str,
        results: list[BrowserSearchResult],
    ) -> BrowserSearchSnapshot:
        raw_id = f"{conversation_id}\n{query}\n{search_url}\n{time.monotonic_ns()}"
        search_id = f"search_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        snapshot = BrowserSearchSnapshot(
            search_id=search_id,
            query=query,
            search_url=search_url,
            provider=self.search_provider,
            results=self._copy_search_results(results),
        )
        snapshots = self._search_cache.setdefault(conversation_id, [])
        snapshots.insert(0, snapshot)
        del snapshots[_MAX_CACHED_SEARCHES_PER_CONVERSATION:]
        return snapshot

    def _latest_cached_search_results(self, conversation_id: str) -> list[BrowserSearchResult]:
        snapshots = self._search_cache.get(conversation_id) or []
        if not snapshots:
            return []
        return self._copy_search_results(snapshots[0].results)

    def _copy_search_results(
        self,
        results: list[BrowserSearchResult],
    ) -> list[BrowserSearchResult]:
        return [
            BrowserSearchResult(
                index=result.index,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
            )
            for result in results
        ]

    def _remember_current_url(self, conversation_id: str, url: str | None) -> None:
        url = _clean_browser_url(str(url or ""))
        if not url or url == "about:blank":
            return
        self._current_url_cache[conversation_id] = url

    def _cache_opened_page(
        self,
        *,
        conversation_id: str,
        url: str,
        final_url: str,
        title: str,
        source_search_id: str | None,
        opener_tool_call_id: str | None,
    ) -> BrowserOpenedPage:
        url = _clean_browser_url(url)
        final_url = _clean_browser_url(final_url)
        raw_id = f"{conversation_id}\n{final_url}\n{time.monotonic_ns()}"
        page_id = f"page_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        opened_page = BrowserOpenedPage(
            page_id=page_id,
            url=url,
            final_url=final_url,
            title=title,
            source_search_id=source_search_id,
            opener_tool_call_id=opener_tool_call_id,
        )
        pages = self._opened_pages_cache.setdefault(conversation_id, [])
        pages.insert(0, opened_page)
        del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
        self._last_open_cache[conversation_id] = opened_page
        return opened_page

    def _mark_opened_page_extracted(self, opened_page: BrowserOpenedPage) -> None:
        opened_page.extraction_count += 1
        opened_page.last_extracted_at = time.monotonic()

    def _opened_page_tab(
        self,
        page: BrowserOpenedPage,
        *,
        index: int,
        current_url: str | None,
        last_open_page_id: str | None,
    ) -> dict[str, Any]:
        parsed = urlparse(page.final_url or page.url)
        domain = parsed.netloc
        title = page.title.strip() if page.title else ""
        summary = title or domain or page.final_url
        return {
            "index": index,
            "page_id": page.page_id,
            "window_id": page.window_id,
            "url": page.url,
            "final_url": page.final_url,
            "domain": domain,
            "title": title,
            "summary": summary,
            "source_search_id": page.source_search_id,
            "opener_tool_call_id": page.opener_tool_call_id,
            "extraction_count": page.extraction_count,
            "is_last_open": page.page_id == last_open_page_id,
            "is_current_page": bool(current_url and current_url == page.final_url),
        }

    def _opened_page(
        self,
        conversation_id: str,
        page_id: str,
    ) -> BrowserOpenedPage | None:
        for opened_page in self._opened_pages_cache.get(conversation_id, []):
            if opened_page.page_id == page_id:
                return opened_page
        return None

    def _target_title(self, conversation_id: str, page_id: str | None) -> str:
        if not page_id:
            return ""
        opened_page = self._opened_page(conversation_id, page_id)
        return opened_page.title if opened_page is not None else ""

    def _resolve_content_target(
        self,
        conversation_id: str,
        session: _BrowserSession | None,
        *,
        url: str | None = None,
        page_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        if url and page_id:
            raise BrowserError("Use either url or page_id, not both.")
        if page_id:
            opened_page = self._opened_page(conversation_id, page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {page_id}. Run BrowserOpen first."
                )
            return opened_page.final_url, opened_page.page_id
        if url:
            return _clean_browser_url(url), None
        next_unextracted = self._next_unextracted_opened_page(conversation_id)
        if next_unextracted is not None:
            return next_unextracted.final_url, next_unextracted.page_id
        last_open = self._last_open_cache.get(conversation_id)
        if last_open is not None:
            return last_open.final_url, last_open.page_id
        if session is not None and session.last_open_url:
            return session.last_open_url, session.last_open_page_id
        current_url = _clean_browser_url(
            str(
                (session.current_url if session is not None else None)
                or self._current_url_cache.get(conversation_id)
                or ""
            )
        )
        if current_url.startswith(("http://", "https://")):
            return current_url, None
        if session is not None:
            page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                return page_url, None
        return None, None

    def _next_unextracted_opened_page(self, conversation_id: str) -> BrowserOpenedPage | None:
        pages = [
            page
            for page in self._opened_pages_cache.get(conversation_id, [])
            if page.extraction_count == 0
        ]
        if len(pages) <= 1:
            return None
        return min(pages, key=lambda page: page.opened_at)

    def _should_navigate_for_content(self, session: _BrowserSession, target_url: str) -> bool:
        target_url = _clean_browser_url(target_url)
        if not target_url.startswith(("http://", "https://")):
            return False
        page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return page_url != target_url

    def _result_url(
        self,
        conversation_id: str,
        session: _BrowserSession,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> tuple[str, str | None]:
        if search_id:
            for snapshot in self._search_cache.get(conversation_id, []):
                if snapshot.search_id != search_id:
                    continue
                for result in snapshot.results:
                    if result.index == result_index:
                        return _clean_browser_url(result.url), snapshot.search_id
                raise BrowserError(
                    f"No browser search result with index {result_index} in search_id {search_id}."
                )
            raise BrowserError(
                f"No cached browser search with search_id {search_id}. Run BrowserSearch first."
            )

        for snapshot in self._search_cache.get(conversation_id, []):
            for result in snapshot.results:
                if result.index == result_index:
                    return _clean_browser_url(result.url), snapshot.search_id

        for result in session.search_results:
            if result.index == result_index:
                return _clean_browser_url(result.url), None
        raise BrowserError(
            f"No browser search result with index {result_index}. Run BrowserSearch first."
        )

    def _match_search_result_url(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str | None:
        snapshots = self._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if _urls_equivalent(url, result.url):
                    return snapshot.search_id
        return None

    async def _cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._sessions.items()
            if now - session.updated_at > self.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self._close_session(conversation_id, self._sessions[conversation_id])
        self._cleanup_search_cache(now)

    def _cleanup_search_cache(self, now: float) -> None:
        for conversation_id, snapshots in list(self._search_cache.items()):
            fresh = [
                snapshot
                for snapshot in snapshots
                if now - snapshot.created_at <= self.session_ttl_seconds
            ][:_MAX_CACHED_SEARCHES_PER_CONVERSATION]
            if fresh:
                self._search_cache[conversation_id] = fresh
            else:
                self._search_cache.pop(conversation_id, None)
                if conversation_id not in self._sessions:
                    self._current_url_cache.pop(conversation_id, None)
                    self._last_open_cache.pop(conversation_id, None)
                    self._opened_pages_cache.pop(conversation_id, None)

    async def _enforce_session_limit(self) -> None:
        while len(self._sessions) > self.max_sessions:
            conversation_id, session = min(
                self._sessions.items(),
                key=lambda item: item[1].updated_at,
            )
            await self._close_session(conversation_id, session)

    async def _reset_browser(self) -> None:
        async with self._lock:
            await self._close_sessions()

    async def _close_sessions(self) -> None:
        for conversation_id, session in list(self._sessions.items()):
            await self._close_session(conversation_id, session)

    async def _close_session(self, conversation_id: str, session: _BrowserSession) -> None:
        self._sessions.pop(conversation_id, None)
        for page in self._session_pages(session):
            await self._best_effort_resource_call("browser_page_close", page.close)
        await self._best_effort_resource_call("browser_context_close", session.context.close)
        await self._release_browser(session.browser)

    async def _release_browser(self, browser: Any) -> None:
        await self._best_effort_resource_call("browser_close", browser.close)

    async def _best_effort_resource_call(
        self,
        label: str,
        operation: Callable[[], Any],
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await asyncio.wait_for(
                    result,
                    timeout=min(max(self.timeout_ms / 1000, 0.5), 2),
                )
        except Exception as exc:
            logger.debug("lightpanda_resource_close_failed", label=label, error=str(exc))


class _RawCdpClient:
    """Tiny sequential CDP client for LightPanda-native domain calls."""

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket
        self._next_id = 0
        self._events: list[dict[str, Any]] = []

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        await self._websocket.send(json.dumps(message))
        while True:
            payload = json.loads(await self._websocket.recv())
            if payload.get("id") == message_id:
                if "error" in payload:
                    error = payload["error"]
                    raise BrowserUnavailableError(f"LightPanda CDP {method} failed: {error}")
                result = payload.get("result")
                return result if isinstance(result, dict) else {}
            self._events.append(payload)

    async def wait_for_event(
        self,
        method: str,
        *,
        session_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for index, event in enumerate(self._events):
                if self._is_matching_event(event, method, session_id):
                    return self._events.pop(index)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for CDP event {method}.")
            payload = json.loads(await asyncio.wait_for(self._websocket.recv(), timeout=remaining))
            if self._is_matching_event(payload, method, session_id):
                return payload
            self._events.append(payload)

    @staticmethod
    def _is_matching_event(payload: dict[str, Any], method: str, session_id: str) -> bool:
        return payload.get("method") == method and payload.get("sessionId") == session_id


_GOOGLE_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      if (parsed.pathname === '/url' && parsed.searchParams.get('q')) {
        return parsed.searchParams.get('q');
      }
      if (parsed.searchParams.get('url')) {
        return parsed.searchParams.get('url');
      }
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  for (const anchor of Array.from(document.querySelectorAll('a'))) {
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host.includes('google.')) continue;
    const heading = anchor.querySelector('h3');
    const title = clean(heading ? heading.textContent : anchor.textContent);
    if (!title || title.length < 3) continue;
    let container = anchor;
    for (let i = 0; i < 4 && container.parentElement; i += 1) {
      container = container.parentElement;
    }
    let snippet = clean(container.textContent).replace(title, '').replace(href, '').trim();
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_YAHOO_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      const ru = parsed.searchParams.get('RU') || parsed.searchParams.get('url');
      if (ru && /^https?:\\/\\//i.test(ru)) return ru;
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  const containers = Array.from(
    document.querySelectorAll('ol.searchCenterMiddle > li, div.dd.algo, div.algo')
  );
  for (const container of containers) {
    const anchor = container.querySelector(
      '.compTitle a[href], h3 a[href], a[href][target="_blank"]'
    );
    if (!anchor) continue;
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host === 'search.yahoo.com' || host.endsWith('.search.yahoo.com')) continue;
    const titleNode = anchor.querySelector('h3, .title') || container.querySelector('h3');
    const title = clean(titleNode ? titleNode.textContent : anchor.textContent);
    if (!title || title.length < 3) continue;
    const snippetNode = container.querySelector('.compText, .compText p, p');
    let snippet = clean(snippetNode ? snippetNode.textContent : '');
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_BING_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const decodeBingRedirect = (parsed) => {
    const encoded = parsed.searchParams.get('u');
    if (!encoded) return '';
    try {
      let value = encoded.startsWith('a1') ? encoded.slice(2) : encoded;
      value = value.replace(/-/g, '+').replace(/_/g, '/');
      while (value.length % 4) value += '=';
      return atob(value);
    } catch (_) {
      return '';
    }
  };
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      const host = parsed.hostname.toLowerCase();
      if (host.endsWith('bing.com') && parsed.pathname.startsWith('/ck/')) {
        const decoded = decodeBingRedirect(parsed);
        if (/^https?:\\/\\//i.test(decoded)) return decoded;
      }
      if (parsed.searchParams.get('url')) {
        return parsed.searchParams.get('url');
      }
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  const containers = Array.from(document.querySelectorAll('li.b_algo, #b_results > li'));
  for (const container of containers) {
    const anchor = container.querySelector('h2 a[href], a[href]');
    if (!anchor) continue;
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host.endsWith('bing.com')) continue;
    const title = clean(anchor.textContent);
    if (!title || title.length < 3) continue;
    let snippet = clean(
      (container.querySelector('.b_caption p, p') || {}).textContent || ''
    );
    if (!snippet) {
      snippet = clean(container.textContent).replace(title, '').replace(href, '').trim();
    }
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_GENERIC_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const results = [];
  const searchHost = location.hostname.toLowerCase();
  for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
    let href = '';
    try {
      href = new URL(anchor.getAttribute('href') || anchor.href || '', location.href).href;
    } catch (_) {
      continue;
    }
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host === searchHost) continue;
    const title = clean(anchor.textContent);
    if (!title || title.length < 3) continue;
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet: '' });
    if (results.length >= maxResults) break;
  }
  return results;
}"""
