"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import json
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
class _BrowserSession:
    browser: Any
    context: Any
    page: Any
    search_results: list[BrowserSearchResult] = field(default_factory=list)
    current_url: str | None = None
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
        self._playwright: Any | None = None
        self._sessions: dict[str, _BrowserSession] = {}

    async def warmup(self) -> bool:
        """Best-effort startup connection. Failures are logged, not raised."""

        try:
            browser = await self._connect_browser()
        except BrowserError as exc:
            logger.warning("lightpanda_warmup_failed", error=str(exc))
            return False
        with suppress(Exception):
            await browser.close()
        return True

    async def close(self) -> None:
        """Close pages, contexts, browser and Playwright runtime."""

        async with self._lock:
            await self._close_sessions()
            if self._playwright is not None:
                with suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None

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
        await self._goto(session, search_url)
        await self._raise_if_search_blocked(session.page)
        extracted = await session.page.evaluate(
            _search_results_script(self.search_provider),
            {"maxResults": max_results},
        )
        results = [
            BrowserSearchResult(
                index=index + 1,
                title=str(item.get("title") or "").strip(),
                url=str(item.get("url") or "").strip(),
                snippet=str(item.get("snippet") or "").strip(),
            )
            for index, item in enumerate(extracted or [])
            if isinstance(item, dict) and item.get("title") and item.get("url")
        ][:max_results]
        session.search_results = results
        session.current_url = str(getattr(session.page, "url", search_url) or search_url)
        session.touch()
        return {
            "type": "browser_search",
            "provider": self.search_provider,
            "query": query,
            "search_url": search_url,
            "results": [result.to_dict() for result in results],
        }

    async def open(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        result_index: int | None = None,
    ) -> dict[str, Any]:
        """Open a URL or one of the last search results."""

        session = await self._get_session(conversation_id)
        target_url = url
        if target_url is None and result_index is not None:
            target_url = self._result_url(session, result_index)
        if target_url is None:
            raise BrowserError("BrowserOpen requires url or result_index.")
        await self._goto(session, target_url)
        await self._raise_if_search_blocked(session.page)
        title = await self._safe_title(session.page)
        final_url = str(getattr(session.page, "url", target_url) or target_url)
        session.current_url = final_url
        session.touch()
        return {
            "type": "browser_open",
            "url": target_url,
            "final_url": final_url,
            "title": title,
        }

    async def extract_content(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        """Return organized markdown/text content for the current or provided URL."""

        session = await self._get_session(conversation_id)
        if url:
            await self._goto(session, url)
        await self._raise_if_search_blocked(session.page)
        title = await self._safe_title(session.page)
        final_url = str(getattr(session.page, "url", url or "") or url or "")
        content, extraction_method = await self._markdown_or_text(session)
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip()
        links = await self._extract_links(session.page) if include_links else []
        buttons = await self._extract_buttons(session.page)
        session.current_url = final_url
        session.touch()
        return {
            "type": "browser_extract_content",
            "url": final_url,
            "title": title,
            "content": content,
            "extraction_method": extraction_method,
            "links": links,
            "buttons": buttons,
            "truncated": truncated,
        }

    async def get_html(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        max_chars: int,
    ) -> dict[str, Any]:
        """Return raw HTML for the current or provided URL."""

        session = await self._get_session(conversation_id)
        if url:
            await self._goto(session, url)
        await self._raise_if_search_blocked(session.page)
        title = await self._safe_title(session.page)
        final_url = str(getattr(session.page, "url", url or "") or url or "")
        html = await session.page.content()
        truncated = len(html) > max_chars
        if truncated:
            html = html[:max_chars].rstrip()
        session.current_url = final_url
        session.touch()
        return {
            "type": "browser_get_html",
            "url": final_url,
            "title": title,
            "html": html,
            "truncated": truncated,
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
        await self._cleanup_sessions()
        session = self._sessions.get(conversation_id)
        if session is not None:
            try:
                browser_connected = True
                is_connected = getattr(session.browser, "is_connected", None)
                if callable(is_connected):
                    browser_connected = bool(is_connected())
                if browser_connected and not session.page.is_closed():
                    session.touch()
                    return session
            except Exception:
                await self._close_session(conversation_id, session)

        browser = await self._connect_browser()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            session = _BrowserSession(browser=browser, context=context, page=page)
            self._sessions[conversation_id] = session
            await self._enforce_session_limit()
            return session
        except Exception as exc:
            with suppress(Exception):
                await browser.close()
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

    async def _connect_browser(self) -> Any:
        if not self.enabled:
            raise BrowserUnavailableError("LightPanda browser tools are disabled.")
        endpoint = await self._resolve_endpoint()
        try:
            if self._connector is not None:
                return await self._connector(endpoint)
            return await self._connect_with_playwright(endpoint)
        except Exception as exc:
            raise BrowserUnavailableError(
                "Browser CDP endpoint is unavailable. Start LightPanda with "
                "`docker compose up -d lightpanda` or start Chrome/Chromium with "
                "`--remote-debugging-port=9222`, then verify /json/version."
            ) from exc

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

    async def _resolve_endpoint(self) -> str:
        version_payload = None
        if self.cdp_url.strip().startswith(("http://", "https://")):
            with suppress(Exception):
                async with httpx.AsyncClient(timeout=self.timeout_ms / 1000) as client:
                    response = await client.get(f"{self.cdp_url.rstrip('/')}/json/version")
                    response.raise_for_status()
                    version_payload = response.json()
        return normalize_lightpanda_cdp_endpoint(self.cdp_url, version_payload)

    async def _goto(self, session: _BrowserSession, url: str) -> None:
        try:
            await session.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await session.page.wait_for_timeout(250)
        except Exception as exc:
            await self._reset_browser()
            if "RobotsBlocked" in str(exc):
                raise BrowserBlockedError(
                    "LightPanda blocked navigation because `--obey-robots` is enabled.",
                    provider=urlparse(url).hostname or "",
                    reason="robots_txt",
                    url=url,
                ) from exc
            raise BrowserUnavailableError(f"LightPanda navigation failed for {url}: {exc}") from exc

    async def _markdown_or_text(self, session: _BrowserSession) -> tuple[str, str]:
        markdown = await self._lightpanda_markdown(session)
        if markdown:
            return markdown.strip(), "lightpanda_markdown"
        text = str(
            await session.page.evaluate(
                "() => (document.body && (document.body.innerText || document.body.textContent)) "
                "|| document.documentElement.textContent || ''"
            )
            or ""
        ).strip()
        return text, "dom_text"

    async def _lightpanda_markdown(self, session: _BrowserSession) -> str:
        url = str(getattr(session.page, "url", "") or "")
        if not url or url == "about:blank":
            return ""
        try:
            payload = await self._lightpanda_raw_cdp_command(
                url=url,
                method="LP.getMarkdown",
            )
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        if isinstance(payload, dict):
            for key in ("markdown", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str):
            return payload
        return ""

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

        endpoint = await self._resolve_endpoint()
        timeout_seconds = self.timeout_ms / 1000
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

    async def _extract_links(self, page: Any) -> list[dict[str, str]]:
        links = await page.evaluate(
            """() => {
              const seen = new Set();
              return Array.from(document.querySelectorAll('a[href]')).map((a) => {
                const href = a.href || a.getAttribute('href') || '';
                const text = (a.textContent || '').replace(/\\s+/g, ' ').trim();
                return { url: href, text };
              }).filter((item) => {
                if (!/^https?:\\/\\//i.test(item.url) || seen.has(item.url)) return false;
                seen.add(item.url);
                return true;
              }).slice(0, 50);
            }"""
        )
        return [
            {"url": str(item.get("url") or ""), "text": str(item.get("text") or "")}
            for item in links
            if isinstance(item, dict) and item.get("url")
        ]

    async def _extract_buttons(self, page: Any) -> list[dict[str, str]]:
        buttons = await page.evaluate(
            """() => {
              return Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"]')).map((el) => {
                const text = (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
                const type = el.tagName ? el.tagName.toLowerCase() : '';
                const id = el.id || '';
                const name = el.getAttribute('name') || '';
                return { text, type, id, name };
              }).filter((item) => item.text || item.id || item.name).slice(0, 50);
            }"""
        )
        return [
            {
                "text": str(item.get("text") or ""),
                "type": str(item.get("type") or ""),
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
            }
            for item in buttons
            if isinstance(item, dict)
        ]

    async def _safe_title(self, page: Any) -> str:
        try:
            return str(await page.title() or "").strip()
        except Exception:
            return ""

    async def _raise_if_google_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_google_surface = "google." in page_url or "google" in title
        if "sorry/index" not in page_url and not is_google_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await page.evaluate(
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)"
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
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_bing_surface = "bing.com" in page_url or "bing" in title
        if not is_bing_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await page.evaluate(
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)"
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
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_yahoo_surface = "search.yahoo.com" in page_url or "yahoo search" in title
        if not is_yahoo_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await page.evaluate(
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)"
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

    def _result_url(self, session: _BrowserSession, result_index: int) -> str:
        for result in session.search_results:
            if result.index == result_index:
                return result.url
        raise BrowserError(
            f"No browser search result with index {result_index}. Run BrowserSearch first."
        )

    async def _cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._sessions.items()
            if now - session.updated_at > self.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self._close_session(conversation_id, self._sessions[conversation_id])

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
        with suppress(Exception):
            await session.page.close()
        with suppress(Exception):
            await session.context.close()
        with suppress(Exception):
            await session.browser.close()


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
