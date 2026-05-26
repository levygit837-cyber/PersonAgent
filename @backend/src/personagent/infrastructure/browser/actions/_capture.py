from __future__ import annotations

import asyncio
import base64
from typing import Any

import structlog

from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.search.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)

logger = structlog.get_logger(__name__)


class _CaptureMixin:
    async def screenshot(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        width: int = 1024,
        height: int = 720,
        full_page: bool = False,
        image_format: str = "png",
        quality: int | None = None,
    ) -> dict[str, Any]:
        """Capture a page screenshot or return the controlled DOM-mirror fallback."""

        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
        title, user_agent, raw_element_map, html, scroll_state = await asyncio.gather(
            self._w.page_helpers.safe_title(page),
            self._w.element_helpers.safe_user_agent(page),
            self._w.snapshot.browser_element_map(page),
            self._w.element_helpers.safe_html(page),
            self._w.element_helpers.safe_scroll_state(page),
        )
        current_url = _clean_browser_url(str(getattr(page, "url", "") or "about:blank"))
        runtime = "lightpanda" if user_agent.lower().startswith("lightpanda/") else "chrome_cdp"
        render_mode = "html_mirror"
        image_data = ""
        image_error = ""
        screenshot_method = ""
        requested_format = str(image_format or "png").lower()
        if requested_format not in {"png", "jpeg"}:
            requested_format = "png"
        if runtime == "lightpanda":
            image_error = "LightPanda has no graphical rendering engine; using DOM mirror."
        else:
            try:
                screenshot = getattr(page, "screenshot", None)
                if not callable(screenshot):
                    raise BrowserUnavailableError("Page screenshot capture is unavailable.")
                kwargs: dict[str, Any] = {
                    "type": requested_format,
                    "full_page": bool(full_page),
                }
                if requested_format == "jpeg" and quality is not None:
                    kwargs["quality"] = min(max(int(quality), 1), 100)
                raw_image = await asyncio.wait_for(
                    screenshot(**kwargs),
                    timeout=min(max(self._w.timeout_ms / 1000, 1.0), 10.0),
                )
                image_data = base64.b64encode(raw_image).decode("ascii")
                render_mode = "pixel"
                screenshot_method = "playwright_page_screenshot"
            except Exception as exc:
                image_error = str(exc)
                logger.warning("browser_control_screenshot_failed", error=image_error)
        element_map = self._w.snapshot.enrich_browser_element_map(
            raw_element_map,
            browser_id=conversation_id,
            tab_id=resolved_page_id,
        )
        self._w._element_map_cache[conversation_id] = element_map
        session.current_url = current_url or session.current_url
        session.touch()
        return {
            "type": "browser_screenshot",
            "page_id": resolved_page_id,
            "window_id": resolved_page_id,
            "url": current_url,
            "title": title,
            "runtime": runtime,
            "render_mode": render_mode,
            "active_tab_id": session.current_page_id or resolved_page_id,
            "navigated": False,
            "image_data": image_data,
            "image_mime_type": f"image/{requested_format}" if image_data else "",
            "screenshot_method": screenshot_method,
            "screenshot_error": image_error,
            "can_capture": bool(image_data),
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "scroll_x": scroll_state.get("scroll_x", 0),
            "scroll_y": scroll_state.get("scroll_y", 0),
            "full_page": bool(full_page),
            "html": html if not image_data else "",
            "document_html": html if not image_data else "",
            "element_map": element_map[:80],
        }
