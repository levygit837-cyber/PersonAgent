"""Browser snapshot pipeline: DOM → structured view."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from personagent.infrastructure.artifacts import (  # noqa: F401
    store_bytes_artifact,
    store_text_artifact,
)
from personagent.infrastructure.browser.snapshot_elements import (
    browser_element_map,
    browser_frame_tree_snapshot,
    browser_iframe_element_map,
    enrich_browser_element_map,
)
from personagent.infrastructure.browser.snapshot_pipeline import (
    browser_view_snapshot,
    view_snapshot,
)
from personagent.infrastructure.browser.snapshot_styles import (
    computed_html_snapshot,
    css_fidelity,
    fetch_stylesheet_css,
    html_attrs,
    html_with_embedded_stylesheet_fallbacks,
    rewrite_css_urls,
    stylesheet_hrefs,
)
from personagent.infrastructure.browser.snapshot_tabs import (
    browser_tabs_snapshot,
    panel_session_tabs,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

__all__ = ["BrowserSnapshot"]


class BrowserSnapshot:
    """DOM → structured view pipeline: element maps, HTML, stylesheets, screenshots."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def view_snapshot(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        return await view_snapshot(
            self._w,
            browser_id=browser_id,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    # ------------------------------------------------------------------
    # Core snapshot pipeline
    # ------------------------------------------------------------------

    async def browser_view_snapshot(
        self,
        browser_id: str,
        session: Any,
        *,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        return await browser_view_snapshot(
            self._w,
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    # ------------------------------------------------------------------
    # Element map
    # ------------------------------------------------------------------

    def enrich_browser_element_map(
        self,
        raw_map: list[dict[str, Any]],
        *,
        browser_id: str,
        tab_id: str,
    ) -> list[dict[str, Any]]:
        return enrich_browser_element_map(
            raw_map,
            browser_id=browser_id,
            tab_id=tab_id,
        )

    async def browser_element_map(self, page: Any) -> list[dict[str, Any]]:
        return await browser_element_map(self._w, page)

    async def browser_iframe_element_map(self, page: Any) -> list[dict[str, Any]]:
        return await browser_iframe_element_map(self._w, page)

    async def browser_frame_tree_snapshot(
        self,
        page: Any,
        *,
        current_url: str,
        title: str,
    ) -> list[dict[str, Any]]:
        return await browser_frame_tree_snapshot(
            self._w,
            page,
            current_url=current_url,
            title=title,
        )

    # ------------------------------------------------------------------
    # Tab snapshots
    # ------------------------------------------------------------------

    def browser_tabs_snapshot(
        self,
        browser_id: str,
        session: Any,
        *,
        current_url: str,
        title: str,
        runtime: str,
    ) -> list[dict[str, Any]]:
        return browser_tabs_snapshot(
            self._w,
            browser_id,
            session,
            current_url=current_url,
            title=title,
            runtime=runtime,
        )

    async def panel_session_tabs(
        self,
        *,
        max_tabs: int,
        exclude_conversation_id: str,
    ) -> list[dict[str, Any]]:
        return await panel_session_tabs(
            self._w,
            max_tabs=max_tabs,
            exclude_conversation_id=exclude_conversation_id,
        )

    # ------------------------------------------------------------------
    # HTML + stylesheet pipeline
    # ------------------------------------------------------------------

    async def html_with_embedded_stylesheet_fallbacks(
        self,
        html: str,
        current_url: str,
    ) -> tuple[str, dict[str, int]]:
        return await html_with_embedded_stylesheet_fallbacks(
            self._w,
            html,
            current_url,
        )

    async def computed_html_snapshot(self, page: Any, current_url: str) -> str:
        return await computed_html_snapshot(self._w, page, current_url)

    @staticmethod
    def stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
        return stylesheet_hrefs(html, current_url, max_hrefs=max_hrefs)

    @staticmethod
    def html_attrs(tag: str) -> dict[str, str]:
        return html_attrs(tag)

    async def fetch_stylesheet_css(self, client: Any, href: str) -> tuple[str, bool]:
        return await fetch_stylesheet_css(self._w, client, href)

    @staticmethod
    def rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
        return rewrite_css_urls(css_text, stylesheet_url)

    @staticmethod
    def css_fidelity(*, html: str, render_mode: str, embedded_stylesheet_count: int = 0) -> str:
        return css_fidelity(html=html, render_mode=render_mode, embedded_stylesheet_count=embedded_stylesheet_count)
