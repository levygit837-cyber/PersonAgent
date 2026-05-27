from __future__ import annotations

from contextlib import suppress
from typing import Any

from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.search.url_utils import (
    clamped_viewport as _clamped_viewport,
)


class _PointerMixin:
    async def view_click(
        self,
        *,
        browser_id: str,
        x: float,
        y: float,
        width: int,
        height: int,
        button: str = "left",
    ) -> dict[str, Any]:
        """Click within the rendered session-panel browser viewport."""

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w.session_manager.preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w.element_helpers.set_page_viewport(page, viewport_width, viewport_height)
        mouse = getattr(page, "mouse", None)
        click = getattr(mouse, "click", None)
        if not callable(click):
            raise BrowserUnavailableError("LightPanda pointer interaction is unavailable.")
        safe_button = button if button in {"left", "middle", "right"} else "left"
        await click(
            min(max(float(x), 0.0), float(viewport_width)),
            min(max(float(y), 0.0), float(viewport_height)),
            button=safe_button,
        )
        await self._w.page_helpers.wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
            wait_for_styles=False,
        )

    async def view_key(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
        text: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Type or press a key in the focused session-panel browser page."""

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w.session_manager.preferred_session_page(session)
        session.page = page
        keyboard = getattr(page, "keyboard", None)
        if keyboard is None:
            raise BrowserUnavailableError("LightPanda keyboard interaction is unavailable.")
        if text:
            type_text = getattr(keyboard, "type", None)
            if not callable(type_text):
                raise BrowserUnavailableError("LightPanda text input is unavailable.")
            await type_text(text)
        elif key:
            press_key = getattr(keyboard, "press", None)
            if not callable(press_key):
                raise BrowserUnavailableError("LightPanda key input is unavailable.")
            await press_key(key)
        await self._w.page_helpers.wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)

    async def view_scroll(
        self,
        *,
        browser_id: str,
        delta_x: float,
        delta_y: float,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Scroll the real session-panel browser page."""

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w.session_manager.preferred_session_page(session)
        session.page = page
        mouse = getattr(page, "mouse", None)
        wheel = getattr(mouse, "wheel", None)
        if callable(wheel):
            await wheel(float(delta_x), float(delta_y))
        else:
            await self._w._browser_runtime.evaluate_page(
                page,
                "([deltaX, deltaY]) => window.scrollBy(deltaX, deltaY)",
                [float(delta_x), float(delta_y)],
            )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)
