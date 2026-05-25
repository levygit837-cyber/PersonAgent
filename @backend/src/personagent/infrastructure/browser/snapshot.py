"""Browser snapshot pipeline: DOM → structured view."""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from personagent.infrastructure.artifacts import store_bytes_artifact, store_text_artifact
from personagent.infrastructure.browser.cache import SnapshotCache
from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.url_utils import (
    browser_empty_fallback_html as _browser_empty_fallback_html,
)
from personagent.infrastructure.browser.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)

_LINK_TAG_PATTERN = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HTML_ATTR_PATTERN = re.compile(
    r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'>`]+)"
)
_CSS_URL_PATTERN = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"\s][^)'\"]*)(?P=quote)\)")
_MAX_STYLESHEET_HREFS_PER_PAGE = int(os.getenv("PERSONAGENT_BROWSER_CSS_MAX_HREFS", "32"))


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
        """Return a real LightPanda-rendered screenshot for a session-panel browser."""

        session = await self._w.session_manager.get_session(browser_id)
        return await self.browser_view_snapshot(
            browser_id,
            session,
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
        page = self._w.session_manager.preferred_session_page(session)
        session.page = page
        active_tab_id = self._w.session_manager.ensure_session_page_alias(browser_id, session, page=page)
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
        await self._w.console.install_cooperation_capture(page, browser_id, active_tab_id)
        current_url = _clean_browser_url(str(getattr(page, "url", "") or "about:blank"))
        render_cache_key = SnapshotCache.cache_key(
            browser_id,
            current_url,
            active_tab_id,
            viewport_width,
            viewport_height,
        )
        render_cache_url_key = SnapshotCache.url_cache_key(browser_id, current_url)
        if cache_mode == "prefer_cached":
            cached_snapshot = self._w._snapshot_cache.read(render_cache_key) or self._w._snapshot_cache.read(
                render_cache_url_key
            )
            if cached_snapshot is not None:
                return cached_snapshot
        style_metrics = (
            await self._w.page_helpers.wait_for_page_visual_ready(page)
            if wait_for_styles
            else {
                "style_ready": True,
                "stylesheet_count": 0,
                "stylesheet_loaded_count": 0,
                "fonts_ready": True,
            }
        )
        element_map_source = (
            self.browser_element_map(page)
            if wait_for_styles
            else asyncio.sleep(0, result=list(self._w._element_map_cache.get(browser_id, [])))
        )
        title, user_agent, raw_element_map, html, scroll_state = await asyncio.gather(
            self._w.page_helpers.safe_title(page),
            self._w.element_helpers.safe_user_agent(page),
            element_map_source,
            self._w.element_helpers.safe_html(page),
            self._w.element_helpers.safe_scroll_state(page),
        )
        if wait_for_styles:
            element_map = self.enrich_browser_element_map(
                raw_element_map,
                browser_id=browser_id,
                tab_id=session.current_page_id or browser_id,
            )
            self._w._element_map_cache[browser_id] = element_map
        else:
            element_map = [dict(item) for item in raw_element_map if isinstance(item, Mapping)]
        html_from_fallback = False
        if not html.strip() and current_url.startswith(("http://", "https://")):
            html, _html_method = await self._w.content_module._html_or_empty_page(page, fallback_url=current_url)
            html_from_fallback = True
        if not html.strip() and current_url.startswith(("http://", "https://")):
            html = _browser_empty_fallback_html(current_url, title)
            html_from_fallback = True
        html, stylesheet_stats = await self.html_with_embedded_stylesheet_fallbacks(
            html,
            current_url,
        )
        embedded_stylesheet_count = int(stylesheet_stats.get("embedded_stylesheet_count") or 0)
        stylesheet_count = max(
            int(style_metrics.get("stylesheet_count") or 0),
            int(stylesheet_stats.get("stylesheet_count") or 0),
        )
        stylesheet_loaded_count = max(
            int(style_metrics.get("stylesheet_loaded_count") or 0),
            embedded_stylesheet_count,
        )
        stylesheet_cached_count = int(stylesheet_stats.get("stylesheet_cached_count") or 0)
        style_ready = bool(style_metrics.get("style_ready")) or (
            stylesheet_count > 0 and stylesheet_loaded_count >= stylesheet_count
        )
        is_lightpanda = user_agent.lower().startswith("lightpanda/")
        image_bytes = b""
        image_error = ""
        if is_lightpanda:
            image_error = "LightPanda has no graphical rendering engine; using DOM mirror."
        else:
            try:
                screenshot = getattr(page, "screenshot", None)
                if not callable(screenshot):
                    raise BrowserUnavailableError("Page screenshot capture is unavailable.")
                raw_image = await asyncio.wait_for(
                    screenshot(type="png", full_page=False),
                    timeout=min(max(self._w.timeout_ms / 1000, 1.0), 10.0),
                )
                image_bytes = bytes(raw_image)
            except Exception as exc:
                image_error = str(exc)
                logger.warning("lightpanda_browser_view_screenshot_failed", error=image_error)

        if current_url and current_url != "about:blank":
            session.current_url = current_url
            self._w.search_result_cache.remember_current_url(browser_id, current_url)
        session.touch()
        render_mode = "html_mirror" if is_lightpanda or not image_bytes else "pixel"
        runtime = "lightpanda" if is_lightpanda else "chrome_cdp"
        css_fidelity = self.css_fidelity(
            html=html,
            render_mode=render_mode,
            embedded_stylesheet_count=embedded_stylesheet_count,
        )
        if html_from_fallback and css_fidelity == "original":
            css_fidelity = "fallback_html"
        needs_computed_fallback = (
            render_mode == "html_mirror"
            and html.strip()
            and (
                css_fidelity == "fallback_html"
                or (stylesheet_count > 0 and not style_ready and embedded_stylesheet_count == 0)
            )
        )
        if needs_computed_fallback:
            computed_html = await self.computed_html_snapshot(page, current_url)
            if computed_html.strip():
                html = computed_html
                render_mode = "computed_html"
                css_fidelity = "computed"
                style_ready = True
        fallback_reason = (
            ""
            if css_fidelity in {"original", "pixel", "embedded", "computed"}
            else "Page HTML was captured, but original CSS could not be confirmed."
        )
        if css_fidelity == "computed":
            fallback_reason = "Original CSS was not confirmed; using a computed-style DOM snapshot."
        tabs = self.browser_tabs_snapshot(browser_id, session, current_url=current_url, title=title, runtime=runtime)
        frame_tree = (
            await self.browser_frame_tree_snapshot(page, current_url=current_url, title=title)
            if wait_for_styles
            else [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
        )
        cooperation_events = await self._w.console.drain_cooperation_events(page, browser_id, active_tab_id)
        document_artifact = (
            store_text_artifact(
                category="browser-documents",
                conversation_id=browser_id,
                content=html,
                suffix=".html",
                mime_type="text/html; charset=utf-8",
                root=self._w.artifact_root,
                ttl_seconds=max(self._w.session_ttl_seconds, self._w._snapshot_cache.ttl_seconds),
            )
            if html.strip()
            else None
        )
        preview_artifact = (
            store_bytes_artifact(
                category="browser-previews",
                conversation_id=browser_id,
                content=image_bytes,
                suffix=".png",
                mime_type="image/png",
                root=self._w.artifact_root,
                ttl_seconds=max(self._w.session_ttl_seconds, self._w._snapshot_cache.ttl_seconds),
            )
            if image_bytes
            else None
        )
        browser_snapshot = {
            "document_ref": document_artifact.artifact_id if document_artifact else "",
            "document_url": document_artifact.url if document_artifact else "",
            "preview_image_ref": preview_artifact.artifact_id if preview_artifact else "",
            "preview_image_url": preview_artifact.url if preview_artifact else "",
            "url": current_url,
            "title": title,
            "render_mode": render_mode,
            "runtime": runtime,
            "css_fidelity": css_fidelity,
            "fallback_reason": fallback_reason,
            "render_cache_key": render_cache_key,
            "render_cache_status": "miss",
            "style_ready": style_ready,
            "stylesheet_count": stylesheet_count,
            "stylesheet_loaded_count": stylesheet_loaded_count,
            "stylesheet_cached_count": stylesheet_cached_count,
            "visual_events": [],
            "tabs": tabs,
            "active_tab_id": active_tab_id,
            "frame_tree": frame_tree,
            "element_map": element_map,
            "cooperation_events": cooperation_events,
            "scroll_x": scroll_state.get("scroll_x", 0),
            "scroll_y": scroll_state.get("scroll_y", 0),
        }
        view = {
            "type": "browser_view",
            "browser_id": browser_id,
            "url": current_url,
            "title": title,
            "document_ref": document_artifact.artifact_id if document_artifact else "",
            "document_url": document_artifact.url if document_artifact else "",
            "render_mode": render_mode,
            "runtime": runtime,
            "css_fidelity": css_fidelity,
            "fallback_reason": fallback_reason,
            "render_cache_key": render_cache_key,
            "render_cache_status": "miss",
            "style_ready": style_ready,
            "stylesheet_count": stylesheet_count,
            "stylesheet_loaded_count": stylesheet_loaded_count,
            "stylesheet_cached_count": stylesheet_cached_count,
            "visual_events": [],
            "tabs": tabs,
            "active_tab_id": active_tab_id,
            "frame_tree": frame_tree,
            "element_map": element_map,
            "annotations": [],
            "timeline_events": [],
            "cooperation_events": cooperation_events,
            "scroll_x": scroll_state.get("scroll_x", 0),
            "scroll_y": scroll_state.get("scroll_y", 0),
            "browser_snapshot": browser_snapshot,
            "user_agent": user_agent,
            "preview_image_ref": preview_artifact.artifact_id if preview_artifact else "",
            "preview_image_url": preview_artifact.url if preview_artifact else "",
            "image_data": "",
            "image_mime_type": "image/png" if preview_artifact else "",
            "screenshot_method": "playwright_page_screenshot" if preview_artifact else "",
            "screenshot_error": image_error,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "can_capture": bool(preview_artifact),
        }
        self._w._snapshot_cache.store(render_cache_key, view, aliases=[render_cache_url_key])
        return view

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
        enriched: list[dict[str, Any]] = []
        for item in raw_map:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            selector = str(item.get("selector") or "")
            role = str(item.get("role") or "")
            text = str(item.get("text") or "")
            frame_id = str(item.get("frame_id") or "main")
            stable_key = str(item.get("stable_key") or f"{tab_id}|{frame_id}|{selector}|{role}|{text[:80]}")
            next_item = dict(item)
            next_item["node_id"] = node_id
            next_item["tab_id"] = str(item.get("tab_id") or tab_id or browser_id)
            next_item["frame_id"] = frame_id
            next_item["selector_chain"] = item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [selector]
            next_item["shadow_path"] = item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else []
            next_item["stable_key"] = stable_key
            next_item["interactable"] = bool(
                item.get("interactable")
                or role in {"link", "button", "input", "textbox", "select", "form", "checkbox", "radio", "tab"}
            )
            if not isinstance(next_item.get("computed_summary"), dict):
                next_item["computed_summary"] = {}
            enriched.append(next_item)
            if len(enriched) >= 220:
                break
        return enriched

    async def browser_element_map(self, page: Any) -> list[dict[str, Any]]:
        from personagent.infrastructure.browser.scripts import _BROWSER_ELEMENT_MAP_SCRIPT

        mapped: list[dict[str, Any]] = []
        with suppress(Exception):
            value = await self._w._evaluate_page(
                page,
                _BROWSER_ELEMENT_MAP_SCRIPT,
                {"frameId": "main", "frameUrl": str(getattr(page, "url", "") or "")},
            )
            if isinstance(value, list):
                mapped.extend(
                    item
                    for item in value
                    if isinstance(item, dict) and isinstance(item.get("node_id"), str)
                )
        mapped.extend(await self.browser_iframe_element_map(page))
        return mapped[:500]

    async def browser_iframe_element_map(self, page: Any) -> list[dict[str, Any]]:
        from personagent.infrastructure.browser.scripts import _BROWSER_ELEMENT_MAP_SCRIPT

        frames = await self._w.element_helpers.page_frames(page)
        if len(frames) <= 1:
            return []
        main_frame = self._w.element_helpers.main_frame(page)
        mapped: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if frame is main_frame:
                continue
            frame_id = self._w.element_helpers.frame_id(frame, index)
            offset = await self._w.element_helpers.frame_viewport_offset(frame)
            with suppress(Exception):
                evaluate = getattr(frame, "evaluate", None)
                if not callable(evaluate):
                    continue
                value = evaluate(
                    _BROWSER_ELEMENT_MAP_SCRIPT,
                    {
                        "frameId": frame_id,
                        "frameUrl": str(getattr(frame, "url", "") or ""),
                        "offsetX": offset[0],
                        "offsetY": offset[1],
                    },
                )
                if inspect.isawaitable(value):
                    value = await value
                if isinstance(value, list):
                    mapped.extend(
                        item
                        for item in value
                        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
                    )
            if len(mapped) >= 280:
                break
        return mapped[:280]

    async def browser_frame_tree_snapshot(
        self,
        page: Any,
        *,
        current_url: str,
        title: str,
    ) -> list[dict[str, Any]]:
        frames = await self._w.element_helpers.page_frames(page)
        if not frames:
            return [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
        main_frame = self._w.element_helpers.main_frame(page)
        tree: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            frame_id = "main" if frame is main_frame or index == 0 else self._w.element_helpers.frame_id(frame, index)
            parent_id = ""
            frame_url = str(getattr(frame, "url", "") or "")
            parent_frame = getattr(frame, "parent_frame", None)
            if callable(parent_frame):
                with suppress(Exception):
                    parent = parent_frame()
                    if parent is not None and parent is not main_frame:
                        parent_index = frames.index(parent) if parent in frames else 0
                        parent_id = self._w.element_helpers.frame_id(parent, parent_index)
                    elif parent is main_frame:
                        parent_id = "main"
            tree.append(
                {
                    "frame_id": frame_id,
                    "url": frame_url or (current_url if frame_id == "main" else ""),
                    "title": title if frame_id == "main" else "",
                    "parent_frame_id": parent_id,
                }
            )
        return tree or [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]

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
        opened_pages = self._w._opened_pages_cache.get(browser_id, [])
        active_tab_id = session.current_page_id or browser_id
        tabs: list[dict[str, Any]] = []
        for index, opened_page in enumerate(opened_pages[:50], start=1):
            tabs.append(
                {
                    "tab_id": opened_page.page_id,
                    "id": opened_page.page_id,
                    "url": opened_page.final_url or opened_page.url,
                    "title": opened_page.title or title,
                    "runtime": runtime,
                    "active": opened_page.page_id == active_tab_id,
                    "is_active": opened_page.page_id == active_tab_id,
                    "history": [opened_page.final_url or opened_page.url],
                    "index": index,
                }
            )
        if not tabs:
            tabs.append(
                {
                    "tab_id": active_tab_id,
                    "id": active_tab_id,
                    "url": current_url,
                    "title": title,
                    "runtime": runtime,
                    "active": True,
                    "is_active": True,
                    "history": [current_url] if current_url and current_url != "about:blank" else [],
                    "index": 1,
                }
            )
        return tabs

    async def panel_session_tabs(
        self,
        *,
        max_tabs: int,
        exclude_conversation_id: str,
    ) -> list[dict[str, Any]]:
        tabs: list[dict[str, Any]] = []
        sessions = sorted(
            self._w._sessions.items(),
            key=lambda item: getattr(item[1], "updated_at", 0.0),
            reverse=True,
        )
        for browser_id, session in sessions:
            if browser_id == exclude_conversation_id or not browser_id.startswith("browser:"):
                continue
            current_url = _clean_browser_url(
                str(
                    session.current_url
                    or self._w._current_url_cache.get(browser_id)
                    or getattr(session.page, "url", "")
                    or ""
                )
            )
            if not current_url or current_url == "about:blank":
                continue
            title = ""
            with suppress(Exception):
                title = await self._w.page_helpers.safe_title(session.page)
            page_id = session.current_page_id or session.last_open_page_id or browser_id
            parsed = urlparse(current_url)
            tabs.append(
                {
                    "index": len(tabs) + 1,
                    "browser_id": browser_id,
                    "page_id": page_id,
                    "window_id": page_id,
                    "tab_id": page_id,
                    "id": page_id,
                    "url": current_url,
                    "final_url": current_url,
                    "domain": parsed.netloc,
                    "title": title,
                    "summary": title or parsed.netloc or current_url,
                    "source_search_id": None,
                    "opener_tool_call_id": None,
                    "extraction_count": 0,
                    "is_last_open": True,
                    "is_current_page": True,
                    "active": True,
                    "is_active": True,
                    "history": [current_url],
                    "source": "shared_panel_session",
                }
            )
            if len(tabs) >= max_tabs:
                break
        return tabs

    # ------------------------------------------------------------------
    # HTML + stylesheet pipeline
    # ------------------------------------------------------------------

    async def html_with_embedded_stylesheet_fallbacks(
        self,
        html: str,
        current_url: str,
    ) -> tuple[str, dict[str, int]]:
        if not html or not current_url.startswith(("http://", "https://")):
            return html, {
                "stylesheet_count": 0,
                "embedded_stylesheet_count": 0,
                "stylesheet_cached_count": 0,
            }
        hrefs = self.stylesheet_hrefs(html, current_url, max_hrefs=_MAX_STYLESHEET_HREFS_PER_PAGE)
        if not hrefs:
            return html, {
                "stylesheet_count": 0,
                "embedded_stylesheet_count": 0,
                "stylesheet_cached_count": 0,
            }
        timeout = httpx.Timeout(1.8, connect=0.6)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            results = await asyncio.gather(
                *(self.fetch_stylesheet_css(client, href) for href in hrefs),
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

    async def computed_html_snapshot(self, page: Any, current_url: str) -> str:
        from personagent.infrastructure.browser.scripts import _COMPUTED_HTML_SNAPSHOT_SCRIPT

        with suppress(Exception):
            value = await self._w._evaluate_page(
                page,
                _COMPUTED_HTML_SNAPSHOT_SCRIPT,
                {"url": current_url},
            )
            if isinstance(value, str):
                return value[:2_000_000]
        return ""

    @staticmethod
    def stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
        hrefs: list[str] = []
        for tag_match in _LINK_TAG_PATTERN.finditer(html):
            attrs = BrowserSnapshot.html_attrs(str(tag_match.group(0) or ""))
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

    @staticmethod
    def html_attrs(tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for match in _HTML_ATTR_PATTERN.finditer(tag):
            name = str(match.group("name") or "").lower()
            value = str(match.group("value") or "")
            if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
                value = value[1:-1]
            attrs[name] = value
        return attrs

    async def fetch_stylesheet_css(self, client: httpx.AsyncClient, href: str) -> tuple[str, bool]:
        now = time.time()
        cached = self._w._stylesheet_cache.get(href)
        if cached is not None and cached[0] > now:
            return cached[1], True
        disk_cached = self._w._stylesheet_disk_cache.read(href, now=now)
        if disk_cached:
            self._w._stylesheet_cache[href] = (now + self._w._stylesheet_cache_ttl_seconds, disk_cached)
            return disk_cached, True
        response = await client.get(href)
        if response.status_code >= 400:
            return "", False
        content_type = response.headers.get("content-type", "")
        css_text = response.text
        if "css" not in content_type.lower() and "{" not in css_text[:1000]:
            return "", False
        css_text = self.rewrite_css_urls(css_text[:350_000], href)
        self._w._stylesheet_cache[href] = (now + self._w._stylesheet_cache_ttl_seconds, css_text)
        self._w._stylesheet_disk_cache.write(href, css_text, expires_at=now + self._w._stylesheet_cache_ttl_seconds)
        if len(self._w._stylesheet_cache) > self._w._max_stylesheet_cache_entries:
            expired = [key for key, (expires_at, _) in self._w._stylesheet_cache.items() if expires_at <= now]
            for key in expired:
                self._w._stylesheet_cache.pop(key, None)
            while len(self._w._stylesheet_cache) > self._w._max_stylesheet_cache_entries:
                self._w._stylesheet_cache.pop(next(iter(self._w._stylesheet_cache)))
        return css_text, False

    @staticmethod
    def rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
        def replace(match: re.Match[str]) -> str:
            raw_url = str(match.group("url") or "").strip()
            quote = str(match.group("quote") or "")
            if not raw_url or raw_url.startswith(("data:", "http://", "https://", "#")):
                return match.group(0)
            return f"url({quote}{urljoin(stylesheet_url, raw_url)}{quote})"

        return _CSS_URL_PATTERN.sub(replace, css_text)

    @staticmethod
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
