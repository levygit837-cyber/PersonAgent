from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import Any

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


class _InteractionMixin:
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
