"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from personagent.infrastructure.browser.actions import BrowserActions
from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache
from personagent.infrastructure.browser.cdp.client import CdpClient as _RawCdpClient  # noqa: F401
from personagent.infrastructure.browser.cdp.console import BrowserConsole
from personagent.infrastructure.browser.cdp.element_helpers import ElementHelpers
from personagent.infrastructure.browser.content import BrowserContent
from personagent.infrastructure.browser.lightpanda.cdp_runtime import BrowserCdpRuntime
from personagent.infrastructure.browser.lightpanda.connection import BrowserConnection
from personagent.infrastructure.browser.lightpanda.markdown import BrowserMarkdown
from personagent.infrastructure.browser.lightpanda.navigation import BrowserNavigation
from personagent.infrastructure.browser.lightpanda.page_runtime import BrowserPageRuntime
from personagent.infrastructure.browser.models import (
    BrowserBlockedError as BrowserBlockedError,
)
from personagent.infrastructure.browser.models import (
    BrowserConsoleEntry,
    BrowserError,
    BrowserOpenedPage,
    BrowserSearchSnapshot,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.models import (
    BrowserUnavailableError as BrowserUnavailableError,
)
from personagent.infrastructure.browser.page.helpers import PageHelpers
from personagent.infrastructure.browser.page.lifecycle import BrowserPageLifecycle
from personagent.infrastructure.browser.page.opened_pages import OpenedPageTracker
from personagent.infrastructure.browser.page.search import BrowserSearch
from personagent.infrastructure.browser.search.cache import SearchResultCache
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,  # noqa: F401
)
from personagent.infrastructure.browser.search.url_utils import (
    infer_search_provider as _infer_search_provider,
)
from personagent.infrastructure.browser.search.url_utils import (
    normalize_lightpanda_cdp_endpoint as normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.browser.session_manager import BrowserSessionManager
from personagent.infrastructure.browser.snapshot.block_detection import BlockDetector
from personagent.infrastructure.browser.snapshot.snapshot import BrowserSnapshot
from personagent.infrastructure.browser.view_actions import BrowserViewActions

logger = structlog.get_logger(__name__)

Connector = Callable[[str], Awaitable[Any]]

_DEFAULT_SEARCH_BASE_URL = "https://search.yahoo.com/search"
_MAX_LIVE_PAGES_PER_SESSION = max(
    1,
    int(os.getenv("PERSONAGENT_BROWSER_MAX_LIVE_PAGES_PER_SESSION", "4")),
)
_STYLESHEET_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_TTL_SECONDS", "900"))
_MAX_STYLESHEET_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_ENTRIES", "256"))
_STYLESHEET_CACHE_DIR = Path(
    os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_DIR", str(Path.home() / ".cache/personagent/browser-css"))
)
_RENDER_SNAPSHOT_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_TTL_SECONDS", "180"))
_MAX_RENDER_SNAPSHOT_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_ENTRIES", "16"))


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
        self._connection = BrowserConnection(self)
        self._cdp_runtime = BrowserCdpRuntime(self)
        self._navigation = BrowserNavigation(self)
        self._browser_runtime = BrowserPageRuntime(self)
        self._markdown = BrowserMarkdown(self)
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
        return await self._markdown.lightpanda_markdown(session)

    async def _lightpanda_markdown_url(self, url: str) -> str:
        return await self._markdown.lightpanda_markdown_url(url)

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
        return await self._browser_runtime.page_runtime(page)

    async def _is_lightpanda_page(self, page: Any) -> bool:
        return await self._browser_runtime.is_lightpanda_page(page)

    def _bounded_script_result(self, value: Any) -> tuple[str, Any | None, bool]:
        return self._browser_runtime.bounded_script_result(value)

    async def _cdp_command_for_page(
        self,
        page: Any,
        *,
        url: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        return await self._browser_runtime.cdp_command_for_page(
            page, url=url, method=method, params=params
        )

    def _first_open_context_page(self, context: Any) -> Any | None:
        return self._browser_runtime.first_open_context_page(context)

    async def _connect_browser(self) -> Any:
        return await self._connection.connect_browser()

    async def _new_session_page(self, session: _BrowserSession) -> Any | None:
        return await self.session_manager.new_session_page(session)

    async def _goto(
        self,
        conversation_id: str,
        session: _BrowserSession,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        return await self._navigation.goto(
            conversation_id,
            session,
            url,
            allow_partial=allow_partial,
            wait_for_styles=wait_for_styles,
        )

    async def _goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        return await self._navigation.goto_page(
            page, url, allow_partial=allow_partial, wait_for_styles=wait_for_styles
        )

    async def _evaluate_page(
        self,
        page: Any,
        script: str,
        arg: Any | None = None,
    ) -> Any:
        return await self._browser_runtime.evaluate_page(page, script, arg)

    async def _raw_runtime_evaluate_value(
        self,
        url: str,
        expression: str,
        *,
        label: str,
        timeout: float,
    ) -> Any:
        return await self._cdp_runtime.raw_runtime_evaluate_value(
            url, expression, label=label, timeout=timeout
        )

    async def _lightpanda_raw_cdp_command(
        self,
        *,
        url: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._cdp_runtime.lightpanda_raw_cdp_command(
            url=url, method=method, params=params
        )


