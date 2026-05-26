"""Core browser snapshot pipeline: DOM → structured view."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import structlog

from personagent.infrastructure.browser.cache import SnapshotCache
from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.search.url_utils import (
    browser_empty_fallback_html as _browser_empty_fallback_html,
)
from personagent.infrastructure.browser.search.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)

from .elements import (
    browser_element_map,
    browser_frame_tree_snapshot,
    enrich_browser_element_map,
)
from .styles import (
    computed_html_snapshot,
    css_fidelity,
    html_with_embedded_stylesheet_fallbacks,
)
from .tabs import browser_tabs_snapshot

logger = structlog.get_logger(__name__)


async def view_snapshot(
    worker: Any,
    *,
    browser_id: str,
    width: int,
    height: int,
    cache_mode: str = "prefer_live",
    wait_for_styles: bool = True,
) -> dict[str, Any]:
    """Return a real LightPanda-rendered screenshot for a session-panel browser."""

    session = await worker.session_manager.get_session(browser_id)
    return await browser_view_snapshot(
        worker,
        browser_id,
        session,
        width=width,
        height=height,
        cache_mode=cache_mode,
        wait_for_styles=wait_for_styles,
    )


async def browser_view_snapshot(
    worker: Any,
    browser_id: str,
    session: Any,
    *,
    width: int,
    height: int,
    cache_mode: str = "prefer_live",
    wait_for_styles: bool = True,
) -> dict[str, Any]:
    page = worker.session_manager.preferred_session_page(session)
    session.page = page
    active_tab_id = worker.session_manager.ensure_session_page_alias(browser_id, session, page=page)
    viewport_width, viewport_height = _clamped_viewport(width, height)
    await worker.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
    await worker.console.install_cooperation_capture(page, browser_id, active_tab_id)
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
        cached_snapshot = worker._snapshot_cache.read(render_cache_key) or worker._snapshot_cache.read(
            render_cache_url_key
        )
        if cached_snapshot is not None:
            return cached_snapshot
    style_metrics = (
        await worker.page_helpers.wait_for_page_visual_ready(page)
        if wait_for_styles
        else {
            "style_ready": True,
            "stylesheet_count": 0,
            "stylesheet_loaded_count": 0,
            "fonts_ready": True,
        }
    )
    element_map_source = (
        browser_element_map(worker, page)
        if wait_for_styles
        else asyncio.sleep(0, result=list(worker._element_map_cache.get(browser_id, [])))
    )
    title, user_agent, raw_element_map, html, scroll_state = await asyncio.gather(
        worker.page_helpers.safe_title(page),
        worker.element_helpers.safe_user_agent(page),
        element_map_source,
        worker.element_helpers.safe_html(page),
        worker.element_helpers.safe_scroll_state(page),
    )
    if wait_for_styles:
        element_map = enrich_browser_element_map(
            raw_element_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        worker._element_map_cache[browser_id] = element_map
    else:
        element_map = [dict(item) for item in raw_element_map if isinstance(item, Mapping)]
    html_from_fallback = False
    if not html.strip() and current_url.startswith(("http://", "https://")):
        html, _html_method = await worker.content_module._html_or_empty_page(page, fallback_url=current_url)
        html_from_fallback = True
    if not html.strip() and current_url.startswith(("http://", "https://")):
        html = _browser_empty_fallback_html(current_url, title)
        html_from_fallback = True
    html, stylesheet_stats = await html_with_embedded_stylesheet_fallbacks(
        worker,
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
                timeout=min(max(worker.timeout_ms / 1000, 1.0), 10.0),
            )
            image_bytes = bytes(raw_image)
        except Exception as exc:
            image_error = str(exc)
            logger.warning("lightpanda_browser_view_screenshot_failed", error=image_error)

    if current_url and current_url != "about:blank":
        session.current_url = current_url
        worker.search_result_cache.remember_current_url(browser_id, current_url)
    session.touch()
    render_mode = "html_mirror" if is_lightpanda or not image_bytes else "pixel"
    runtime = "lightpanda" if is_lightpanda else "chrome_cdp"
    css_fidelity_value = css_fidelity(
        html=html,
        render_mode=render_mode,
        embedded_stylesheet_count=embedded_stylesheet_count,
    )
    if html_from_fallback and css_fidelity_value == "original":
        css_fidelity_value = "fallback_html"
    needs_computed_fallback = (
        render_mode == "html_mirror"
        and html.strip()
        and (
            css_fidelity_value == "fallback_html"
            or (stylesheet_count > 0 and not style_ready and embedded_stylesheet_count == 0)
        )
    )
    if needs_computed_fallback:
        computed_html = await computed_html_snapshot(worker, page, current_url)
        if computed_html.strip():
            html = computed_html
            render_mode = "computed_html"
            css_fidelity_value = "computed"
            style_ready = True
    fallback_reason = (
        ""
        if css_fidelity_value in {"original", "pixel", "embedded", "computed"}
        else "Page HTML was captured, but original CSS could not be confirmed."
    )
    if css_fidelity_value == "computed":
        fallback_reason = "Original CSS was not confirmed; using a computed-style DOM snapshot."
    tabs = browser_tabs_snapshot(worker, browser_id, session, current_url=current_url, title=title, runtime=runtime)
    frame_tree = (
        await browser_frame_tree_snapshot(worker, page, current_url=current_url, title=title)
        if wait_for_styles
        else [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
    )
    cooperation_events = await worker.console.drain_cooperation_events(page, browser_id, active_tab_id)

    from personagent.infrastructure.browser.snapshot.snapshot import (
        store_bytes_artifact,
        store_text_artifact,
    )

    document_artifact = (
        store_text_artifact(
            category="browser-documents",
            conversation_id=browser_id,
            content=html,
            suffix=".html",
            mime_type="text/html; charset=utf-8",
            root=worker.artifact_root,
            ttl_seconds=max(worker.session_ttl_seconds, worker._snapshot_cache.ttl_seconds),
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
            root=worker.artifact_root,
            ttl_seconds=max(worker.session_ttl_seconds, worker._snapshot_cache.ttl_seconds),
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
        "css_fidelity": css_fidelity_value,
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
        "css_fidelity": css_fidelity_value,
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
    worker._snapshot_cache.store(render_cache_key, view, aliases=[render_cache_url_key])
    return view
