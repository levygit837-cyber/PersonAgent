"""Visible-page browser actions extracted from the LightPanda god file."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserUnavailableError,
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

_MAX_CONSOLE_ENTRIES_PER_PAGE = 200
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


class BrowserActions:
    """Visible-page actions: click, type, screenshot, scroll, console, script, wait."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # click
    # ------------------------------------------------------------------

    async def click(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        node_id: str | None = None,
        x: float | None = None,
        y: float | None = None,
        width: int = 1024,
        height: int = 720,
        button: str = "left",
        click_count: int = 1,
        modifiers: list[str] | None = None,
        wait_after_ms: int = 250,
    ) -> dict[str, Any]:
        """Click a mapped element or viewport coordinate on a live browser page."""

        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        safe_wait_ms = min(max(int(wait_after_ms), 0), 10_000)
        action_details: Mapping[str, Any] = {}
        if node_id:
            view = await self._w.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="click",
                width=viewport_width,
                height=viewport_height,
            )
            if isinstance(view.get("last_action"), Mapping):
                action_details = view["last_action"]
        else:
            if x is None or y is None:
                raise BrowserError("BrowserClick requires node_id or x/y coordinates.")
            await self._w.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
            mouse = getattr(page, "mouse", None)
            click = getattr(mouse, "click", None)
            if not callable(click):
                raise BrowserUnavailableError("Browser pointer interaction is unavailable.")
            safe_button = button if button in {"left", "middle", "right"} else "left"
            kwargs = {
                "button": safe_button,
                "click_count": min(max(int(click_count), 1), 3),
            }
            if modifiers:
                keyboard = getattr(page, "keyboard", None)
                for modifier in modifiers:
                    down = getattr(keyboard, "down", None)
                    if callable(down):
                        with suppress(Exception):
                            await down(str(modifier))
                try:
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
                finally:
                    for modifier in reversed(modifiers):
                        up = getattr(keyboard, "up", None)
                        if callable(up):
                            with suppress(Exception):
                                await up(str(modifier))
            else:
                try:
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
                except TypeError:
                    kwargs.pop("click_count", None)
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
            await self._w.page_helpers.wait_for_page_load_complete(page, timeout_ms=1_500)
            if safe_wait_ms:
                with suppress(Exception):
                    await page.wait_for_timeout(safe_wait_ms)
            session.touch()
            view = await self._w.snapshot.browser_view_snapshot(
                conversation_id,
                session,
                width=viewport_width,
                height=viewport_height,
                wait_for_styles=False,
            )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or view.get("url") or ""))
        view.update(
            {
                "type": "browser_click",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": bool(after_url and before_url and after_url != before_url),
                "last_action": {
                    "action": "click",
                    "node_id": node_id,
                    "x": x,
                    "y": y,
                    "button": button,
                    "click_count": min(max(int(click_count), 1), 3),
                    "modifiers": modifiers or [],
                    "target": action_details.get("target"),
                    "result": action_details.get("result"),
                },
            }
        )
        return view

    # ------------------------------------------------------------------
    # type_input
    # ------------------------------------------------------------------

    async def type_input(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        node_id: str | None = None,
        mode: str = "type",
        text: str | None = None,
        key: str | None = None,
        clear: bool = False,
        delay_ms: int = 0,
        submit: bool = False,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        """Type, fill, or press keys on a live browser page."""

        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        normalized_mode = str(mode or "type").strip().lower()
        if normalized_mode not in {"type", "fill", "press"}:
            raise BrowserError("BrowserType mode must be one of: type, fill, press.")
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        action_details: Mapping[str, Any] = {}
        if node_id and normalized_mode == "fill":
            view = await self._w.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="fill",
                value=text or "",
                width=viewport_width,
                height=viewport_height,
            )
            if isinstance(view.get("last_action"), Mapping):
                action_details = view["last_action"]
        elif node_id and normalized_mode == "press":
            view = await self._w.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="press",
                key=key or text or "",
                width=viewport_width,
                height=viewport_height,
            )
            if isinstance(view.get("last_action"), Mapping):
                action_details = view["last_action"]
        else:
            await self._w.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
            if node_id:
                focus_view = await self._w.view_act(
                    browser_id=conversation_id,
                    node_id=node_id,
                    action="click",
                    width=viewport_width,
                    height=viewport_height,
                )
                if isinstance(focus_view.get("last_action"), Mapping):
                    action_details = focus_view["last_action"]
            keyboard = getattr(page, "keyboard", None)
            if keyboard is None:
                raise BrowserUnavailableError("Browser keyboard interaction is unavailable.")
            if clear:
                press_key = getattr(keyboard, "press", None)
                if callable(press_key):
                    with suppress(Exception):
                        await press_key("Control+A")
                    with suppress(Exception):
                        await press_key("Backspace")
            if normalized_mode == "press":
                press_key = getattr(keyboard, "press", None)
                if not callable(press_key):
                    raise BrowserUnavailableError("Browser key input is unavailable.")
                await press_key(key or text or "")
            elif text:
                type_text = getattr(keyboard, "type", None)
                if not callable(type_text):
                    raise BrowserUnavailableError("Browser text input is unavailable.")
                delay = min(max(int(delay_ms), 0), 1_000)
                try:
                    await type_text(text, delay=delay)
                except TypeError:
                    await type_text(text)
            if submit:
                press_key = getattr(keyboard, "press", None)
                if callable(press_key):
                    await press_key("Enter")
            await self._w.page_helpers.wait_for_page_load_complete(page, timeout_ms=1_500)
            session.touch()
            view = await self._w.snapshot.browser_view_snapshot(
                conversation_id,
                session,
                width=viewport_width,
                height=viewport_height,
                wait_for_styles=False,
            )
        if submit and node_id and normalized_mode in {"fill", "press"}:
            keyboard = getattr(session.page, "keyboard", None)
            press_key = getattr(keyboard, "press", None)
            if callable(press_key):
                with suppress(Exception):
                    await press_key("Enter")
                await self._w.page_helpers.wait_for_page_load_complete(session.page, timeout_ms=1_500)
                view = await self._w.snapshot.browser_view_snapshot(
                    conversation_id,
                    session,
                    width=viewport_width,
                    height=viewport_height,
                    wait_for_styles=False,
                )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or view.get("url") or ""))
        view.update(
            {
                "type": "browser_type",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": bool(after_url and before_url and after_url != before_url),
                "last_action": {
                    "action": normalized_mode,
                    "node_id": node_id,
                    "text": text if normalized_mode in {"type", "fill"} else None,
                    "key": key if normalized_mode == "press" else None,
                    "clear": bool(clear),
                    "submit": bool(submit),
                    "target": action_details.get("target"),
                    "result": action_details.get("result"),
                },
            }
        )
        return view

    # ------------------------------------------------------------------
    # screenshot
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # read_console
    # ------------------------------------------------------------------

    async def read_console(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        levels: list[str] | None = None,
        since_id: int | None = None,
        limit: int = 100,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Read a bounded ring buffer of captured console events for a browser page."""

        session = await self._w.session_manager.get_session(conversation_id)
        target_page_id = str(page_id or session.current_page_id or session.last_open_page_id or "").strip()
        if not target_page_id:
            last_open = self._w._last_open_cache.get(conversation_id)
            target_page_id = last_open.page_id if last_open is not None else conversation_id
        page = session.pages.get(target_page_id) or self._w.session_manager.preferred_session_page(session)
        with suppress(Exception):
            await self._w.console.drain_page_console_entries(page, conversation_id, target_page_id)
        allowed_levels = {str(level).lower() for level in levels or [] if str(level).strip()}
        page_entries = list(self._w._console_cache.get(conversation_id, {}).get(target_page_id, []))
        if since_id is not None:
            page_entries = [entry for entry in page_entries if entry.entry_id > int(since_id)]
        if allowed_levels:
            page_entries = [entry for entry in page_entries if entry.level.lower() in allowed_levels]
        safe_limit = min(max(int(limit), 1), _MAX_CONSOLE_ENTRIES_PER_PAGE)
        selected = page_entries[-safe_limit:]
        if clear:
            self._w._console_cache.get(conversation_id, {}).pop(target_page_id, None)
        return {
            "type": "browser_console",
            "page_id": target_page_id,
            "window_id": target_page_id,
            "url": _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "")),
            "title": await self._w.page_helpers.safe_title(page),
            "runtime": await self._w._page_runtime(page),
            "render_mode": "html_mirror" if await self._w._is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or target_page_id,
            "navigated": False,
            "entries": [entry.to_dict() for entry in selected],
            "next_since_id": selected[-1].entry_id if selected else since_id,
            "cleared": bool(clear),
        }

    # ------------------------------------------------------------------
    # script
    # ------------------------------------------------------------------

    async def script(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        mode: str = "evaluate",
        script: str | None = None,
        args: Any | None = None,
        cdp_method: str | None = None,
        cdp_params: dict[str, Any] | None = None,
        timeout_ms: int = 5_000,
    ) -> dict[str, Any]:
        """Run allowlisted page JS or selected CDP methods for advanced browser control."""

        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        normalized_mode = str(mode or "evaluate").strip().lower()
        safe_timeout_ms = min(max(int(timeout_ms), 1), 30_000)
        current_url = _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "about:blank"))
        if normalized_mode == "evaluate":
            if not isinstance(script, str) or not script.strip():
                raise BrowserError("BrowserScript evaluate requires a non-empty script.")
            if len(script) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(f"BrowserScript script is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters.")
            value = await asyncio.wait_for(
                self._w._evaluate_page(page, script, args),
                timeout=safe_timeout_ms / 1000,
            )
            method = "Runtime.evaluate"
        elif normalized_mode == "cdp":
            method = str(cdp_method or "").strip()
            if method not in _BROWSER_SCRIPT_CDP_ALLOWLIST:
                raise BrowserError(
                    "BrowserScript cdp_method must be one of: "
                    + ", ".join(sorted(_BROWSER_SCRIPT_CDP_ALLOWLIST))
                    + "."
                )
            raw_params = cdp_params or {}
            if len(json.dumps(raw_params, ensure_ascii=False, default=str)) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript cdp_params is too large; max {_MAX_BROWSER_SCRIPT_CHARS} serialized characters."
                )
            expression = raw_params.get("expression") if isinstance(raw_params, dict) else None
            if isinstance(expression, str) and len(expression) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript Runtime.evaluate expression is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters."
                )
            value = await asyncio.wait_for(
                self._w._cdp_command_for_page(
                    page,
                    url=current_url,
                    method=method,
                    params=raw_params,
                ),
                timeout=safe_timeout_ms / 1000,
            )
        else:
            raise BrowserError("BrowserScript mode must be one of: evaluate, cdp.")
        result_text, result, truncated = self._w._bounded_script_result(value)
        return {
            "type": "browser_script",
            "page_id": resolved_page_id,
            "window_id": resolved_page_id,
            "url": current_url,
            "title": await self._w.page_helpers.safe_title(page),
            "runtime": await self._w._page_runtime(page),
            "render_mode": "html_mirror" if await self._w._is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or resolved_page_id,
            "navigated": False,
            "mode": normalized_mode,
            "cdp_method": method if normalized_mode == "cdp" else None,
            "result": result,
            "result_text": result_text,
            "truncated": truncated,
        }

    # ------------------------------------------------------------------
    # scroll
    # ------------------------------------------------------------------

    async def scroll(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        delta_x: float = 0.0,
        delta_y: float = 600.0,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        view = await self._w.view_scroll(
            browser_id=conversation_id,
            delta_x=delta_x,
            delta_y=delta_y,
            width=width,
            height=height,
        )
        view.update(
            {
                "type": "browser_scroll",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": False,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    # ------------------------------------------------------------------
    # wait
    # ------------------------------------------------------------------

    async def wait(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        timeout_ms: int = 1_000,
        state: str | None = None,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, page, resolved_page_id = await self._w.session_manager.resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        safe_timeout_ms = min(max(int(timeout_ms), 1), 120_000)
        state_value = str(state or "").strip()
        if state_value:
            wait_for_load_state = getattr(page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                with suppress(Exception):
                    await wait_for_load_state(state_value, timeout=safe_timeout_ms)
        else:
            with suppress(Exception):
                await page.wait_for_timeout(safe_timeout_ms)
        view = await self._w.snapshot.browser_view_snapshot(conversation_id, session, width=width, height=height)
        view.update(
            {
                "type": "browser_wait",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "timeout_ms": safe_timeout_ms,
                "state": state_value or None,
                "navigated": False,
            }
        )
        return view
