"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from personagent.infrastructure.browser.actions import BrowserActions
from personagent.infrastructure.browser.block_detection import BlockDetector
from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache
from personagent.infrastructure.browser.console import BrowserConsole
from personagent.infrastructure.browser.content import BrowserContent
from personagent.infrastructure.browser.element_helpers import ElementHelpers
from personagent.infrastructure.browser.models import (
    BrowserBlockedError,
    BrowserConsoleEntry,
    BrowserError,
    BrowserOpenedPage,
    BrowserSearchSnapshot,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.opened_pages import OpenedPageTracker
from personagent.infrastructure.browser.page_helpers import PageHelpers
from personagent.infrastructure.browser.page_lifecycle import BrowserPageLifecycle
from personagent.infrastructure.browser.search import BrowserSearch
from personagent.infrastructure.browser.search_cache import SearchResultCache
from personagent.infrastructure.browser.session_manager import BrowserSessionManager
from personagent.infrastructure.browser.snapshot import BrowserSnapshot
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    infer_search_provider as _infer_search_provider,
)
from personagent.infrastructure.browser.url_utils import (
    is_local_lightpanda_endpoint as _is_local_lightpanda_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    is_retryable_raw_cdp_error as _is_retryable_raw_cdp_error,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.browser.view_actions import BrowserViewActions

logger = structlog.get_logger(__name__)

Connector = Callable[[str], Awaitable[Any]]

_DEFAULT_SEARCH_BASE_URL = "https://search.yahoo.com/search"
_MAX_CACHED_SEARCHES_PER_CONVERSATION = 8
_MAX_OPENED_PAGES_PER_CONVERSATION = 32
_MAX_LIVE_PAGES_PER_SESSION = max(
    1,
    int(os.getenv("PERSONAGENT_BROWSER_MAX_LIVE_PAGES_PER_SESSION", "4")),
)
_STYLESHEET_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_TTL_SECONDS", "900"))
_MAX_STYLESHEET_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_ENTRIES", "256"))
_MAX_STYLESHEET_HREFS_PER_PAGE = int(os.getenv("PERSONAGENT_BROWSER_CSS_MAX_HREFS", "32"))
_STYLESHEET_CACHE_DIR = Path(
    os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_DIR", str(Path.home() / ".cache/personagent/browser-css"))
)
_RENDER_SNAPSHOT_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_TTL_SECONDS", "180"))
_MAX_RENDER_SNAPSHOT_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_ENTRIES", "16"))
_RAW_CDP_RETRY_DELAYS = (0.0, 0.5, 1.5, 3.0, 5.0)
_MAX_BROWSER_SCRIPT_CHARS = 10_000
_MAX_BROWSER_SCRIPT_RESULT_CHARS = 12_000
_BROWSER_SCRIPT_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}


class LightPandaBrowserWorker:
    """Keeps one CDP browser connection and per-conversation pages."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_ms: int = 30_000,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
        session_ttl_seconds: int = 600,
        max_sessions: int = 12,
        artifact_root: str | Path | None = None,
        render_cache_entries: int = _MAX_RENDER_SNAPSHOT_CACHE_ENTRIES,
        render_cache_ttl_seconds: float = _RENDER_SNAPSHOT_CACHE_TTL_SECONDS,
        css_cache_entries: int = _MAX_STYLESHEET_CACHE_ENTRIES,
        css_cache_ttl_seconds: float = _STYLESHEET_CACHE_TTL_SECONDS,
        auto_start_lightpanda: bool = True,
        connector: Connector | None = None,
    ) -> None:
        # NOTE: Architecture debt — modules hold a reference to the full worker
        # (self._w) and call each other through it. This was a pragmatic choice
        # during the 17-slice incremental decomposition (5_735 → 674 lines) to
        # minimise merge friction and signature churn across slices.
        #
        # Future opportunity ("Code Judo"): invert the dependency graph so each
        # module receives only the specific collaborators it needs via constructor
        # injection (e.g. BrowserActions gets SessionResolver + ViewportHelper +
        # ConsoleInstaller instead of the whole worker). Benefits:
        #   • Independently testable modules (no full-worker mocks)
        #   • Explicit dependencies visible in __init__ signatures
        #   • Worker becomes a thin orchestrator that wires collaborators
        #   • Eliminates the implicit circular awareness (worker ↔ modules)
        #
        # Cost: refactoring all 15+ extracted modules and ~200 unit tests.
        # Recommended as a separate, focused effort after this decomposition is
        # stable in production.
        self.enabled = enabled
        self.cdp_url = cdp_url
        self.timeout_ms = max(1, int(timeout_ms))
        self.search_base_url = search_base_url or _DEFAULT_SEARCH_BASE_URL
        self.search_provider = _infer_search_provider(self.search_base_url)
        self.session_ttl_seconds = max(1, int(session_ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self.artifact_root = Path(artifact_root).expanduser() if artifact_root else None
        self._snapshot_cache = SnapshotCache(
            max_entries=max(1, int(render_cache_entries)),
            ttl_seconds=max(1.0, float(render_cache_ttl_seconds)),
        )
        self._max_stylesheet_cache_entries = max(1, int(css_cache_entries))
        self._stylesheet_cache_ttl_seconds = max(1.0, float(css_cache_ttl_seconds))
        self._stylesheet_disk_cache = StylesheetDiskCache(
            cache_dir=_STYLESHEET_CACHE_DIR,
            max_entries=self._max_stylesheet_cache_entries,
        )
        self.auto_start_lightpanda = auto_start_lightpanda
        self._connector = connector
        self.actions = BrowserActions(self)
        self.lifecycle = BrowserPageLifecycle(self)
        self.snapshot = BrowserSnapshot(self)
        self.search_module = BrowserSearch(self)
        self.view_actions = BrowserViewActions(self)
        self.content_module = BrowserContent(self)
        self.console = BrowserConsole(self)
        self.opened_pages = OpenedPageTracker(self)
        self.search_result_cache = SearchResultCache(self)
        self.element_helpers = ElementHelpers(self)
        self.block_detector = BlockDetector(self)
        self.page_helpers = PageHelpers(self)
        self.session_manager = BrowserSessionManager(self)
        self._lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._container_start_lock = asyncio.Lock()
        self._container_start_attempted = False
        self._playwright: Any | None = None
        self._sessions: dict[str, _BrowserSession] = {}
        self._search_cache: dict[str, list[BrowserSearchSnapshot]] = {}
        self._current_url_cache: dict[str, str] = {}
        self._last_open_cache: dict[str, BrowserOpenedPage] = {}
        self._opened_pages_cache: dict[str, list[BrowserOpenedPage]] = {}
        self._element_map_cache: dict[str, list[dict[str, Any]]] = {}
        self._stylesheet_cache: dict[str, tuple[float, str]] = {}
        self._console_cache: dict[str, dict[str, list[BrowserConsoleEntry]]] = {}
        self._console_sequence = 0
        self._console_listener_keys: set[tuple[str, str, int]] = set()
        self._cooperation_event_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._cooperation_listener_keys: set[tuple[str, str, int]] = set()

    async def warmup(self) -> bool:
        """Best-effort startup connection. Failures are logged, not raised."""

        try:
            browser = await self._connect_browser()
        except BrowserError as exc:
            logger.warning("lightpanda_warmup_failed", error=str(exc))
            return False
        await self.session_manager.release_browser(browser)
        return True

    async def close(self) -> None:
        """Close pages, contexts, browser and Playwright runtime."""

        async with self._lock:
            await self.session_manager.close_sessions()
            if self._playwright is not None:
                await self.session_manager.best_effort_resource_call(
                    "playwright_stop",
                    self._playwright.stop,
                )
                self._playwright = None
            self._search_cache.clear()
            self._current_url_cache.clear()
            self._last_open_cache.clear()
            self._opened_pages_cache.clear()
            self._stylesheet_cache.clear()
            self._snapshot_cache.clear()
            self._console_cache.clear()
            self._console_listener_keys.clear()
            self._cooperation_event_cache.clear()
            self._cooperation_listener_keys.clear()

    @property
    def search_provider_label(self) -> str:
        return self.search_module.search_provider_label

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        return await self.search_module.search(**kwargs)

    async def extract_content(self, **kwargs: Any) -> dict[str, Any]:
        return await self.content_module.extract_content(**kwargs)

    async def get_html(self, **kwargs: Any) -> dict[str, Any]:
        return await self.content_module.get_html(**kwargs)

    async def _lightpanda_markdown(self, session: Any) -> str:
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
            markdown = self.content_module._extract_markdown_payload(payload)
            if markdown:
                return markdown
        except TimeoutError as exc:
            logger.warning("lightpanda_markdown_raw_timeout", error=str(exc), url=url)
            return ""
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        return ""

    async def view_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.snapshot.view_snapshot(**kwargs)

    async def view_navigate(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_navigate(**kwargs)

    async def view_history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_history(**kwargs)

    async def view_reload(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_reload(**kwargs)

    async def view_click(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_click(**kwargs)

    async def view_key(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_key(**kwargs)

    async def view_scroll(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_scroll(**kwargs)

    async def view_act(self, **kwargs: Any) -> dict[str, Any]:
        return await self.view_actions.view_act(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserActions (Slice 3)
    # ------------------------------------------------------------------

    async def click(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.click(**kwargs)

    async def type_input(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.type_input(**kwargs)

    async def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.screenshot(**kwargs)

    async def read_console(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.read_console(**kwargs)

    async def script(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.script(**kwargs)

    async def scroll(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.scroll(**kwargs)

    async def wait(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.wait(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserPageLifecycle (Slice 4)
    # ------------------------------------------------------------------

    async def open(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.open(**kwargs)

    async def list_tabs(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.list_tabs(**kwargs)

    async def close_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.close_tab(**kwargs)

    async def reload(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.reload(**kwargs)

    async def history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.history(**kwargs)

    async def switch_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.switch_tab(**kwargs)

    # ------------------------------------------------------------------
    # Core: page runtime helpers
    # ------------------------------------------------------------------

    async def _page_runtime(self, page: Any) -> str:
        return "lightpanda" if await self._is_lightpanda_page(page) else "chrome_cdp"

    async def _is_lightpanda_page(self, page: Any) -> bool:
        user_agent = await self.element_helpers.safe_user_agent(page)
        return user_agent.lower().startswith("lightpanda/")

    def _bounded_script_result(self, value: Any) -> tuple[str, Any | None, bool]:
        try:
            result_text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            result_text = str(value)
        truncated = len(result_text) > _MAX_BROWSER_SCRIPT_RESULT_CHARS
        if truncated:
            result_text = result_text[:_MAX_BROWSER_SCRIPT_RESULT_CHARS].rstrip()
        result: Any | None
        if truncated:
            result = None
        else:
            try:
                result = json.loads(result_text)
            except Exception:
                result = result_text
        return result_text, result, truncated

    async def _cdp_command_for_page(
        self,
        page: Any,
        *,
        url: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        context = getattr(page, "context", None)
        if callable(context):
            with suppress(Exception):
                context = context()
        new_cdp_session = getattr(context, "new_cdp_session", None)
        if callable(new_cdp_session):
            cdp_session = await new_cdp_session(page)
            try:
                return await cdp_session.send(method, params or {})
            finally:
                detach = getattr(cdp_session, "detach", None)
                if callable(detach):
                    with suppress(Exception):
                        result = detach()
                        if inspect.isawaitable(result):
                            await result
        return await self._lightpanda_raw_cdp_command(
            url=url or "about:blank",
            method=method,
            params=params or {},
        )

    def _first_open_context_page(self, context: Any) -> Any | None:
        raw_pages = getattr(context, "pages", None)
        if not raw_pages:
            return None
        for page in list(raw_pages):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return None

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
        if await self._try_start_lightpanda_container():
            for attempt in range(4):
                endpoint = await self._resolve_endpoint()
                try:
                    if self._connector is not None:
                        return await self._connector(endpoint)
                    return await self._connect_with_playwright(endpoint)
                except Exception as exc:
                    last_error = exc
                    if attempt == 3:
                        break
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise BrowserUnavailableError(
            "Browser CDP endpoint is unavailable. Start LightPanda with "
            "`docker compose up -d lightpanda` or start Chrome/Chromium with "
            "`--remote-debugging-port=9222`, then verify /json/version."
        ) from last_error

    async def _try_start_lightpanda_container(self) -> bool:
        if (
            not self.auto_start_lightpanda
            or self._connector is not None
            or not _is_local_lightpanda_endpoint(self.cdp_url)
        ):
            return False
        async with self._container_start_lock:
            if self._container_start_attempted:
                return False
            self._container_start_attempted = True
            repo_root = Path(__file__).resolve().parents[5]
            compose_file = repo_root / "docker-compose.yml"
            if not compose_file.exists():
                return False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "compose",
                    "up",
                    "-d",
                    "lightpanda",
                    cwd=repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (OSError, TimeoutError) as exc:
                logger.warning("lightpanda_container_autostart_failed", error=str(exc))
                return False
            output = (
                stdout_data.decode("utf-8", errors="replace")
                + stderr_data.decode("utf-8", errors="replace")
            ).strip()
            if proc.returncode != 0:
                logger.warning(
                    "lightpanda_container_autostart_failed",
                    returncode=proc.returncode,
                    output=output,
                )
                return False
            logger.info("lightpanda_container_autostarted", output=output)
            return True

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
        return await self.session_manager.new_session_page(session)

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
        wait_for_styles: bool = True,
    ) -> None:
        try:
            await self._goto_page(session.page, url, allow_partial=allow_partial, wait_for_styles=wait_for_styles)
        except Exception:
            await self.session_manager.close_session(conversation_id, session)
            raise

    async def _goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        clean_url = _clean_browser_url(url)
        try:
            await page.goto(
                clean_url,
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self.timeout_ms,
            )
            if wait_for_styles:
                await self.page_helpers.wait_for_page_visual_ready(page)
            await self.console.install_console_capture(page)
        except Exception as exc:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if allow_partial and page_url.startswith(("http://", "https://")):
                logger.warning(
                    "lightpanda_navigation_partial",
                    url=clean_url,
                    page_url=page_url,
                    error=str(exc),
                )
                with suppress(Exception):
                    await self.console.install_console_capture(page)
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


from personagent.infrastructure.browser.cdp_client import CdpClient as _RawCdpClient  # noqa: E402
