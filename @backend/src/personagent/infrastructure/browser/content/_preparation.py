"""Page preparation helpers (popup dismiss + incremental scroll) for BrowserContent."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import structlog

from personagent.infrastructure.browser.scripts.content import (
    _INCREMENTAL_SCROLL_SCRIPT,
    _POPUP_DISMISS_SCRIPT,
)

logger = structlog.get_logger(__name__)


class _PagePreparationMixin:
    """Methods for preparing a page before content extraction."""

    async def _prepare_page_for_extraction(self, page: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "prepared_page": True,
            "popup_dismissed_count": 0,
            "popup_dismissed_labels": [],
            "scroll_steps": 0,
        }
        await self._wait_for_page_settle(page)
        with suppress(Exception):
            await page.wait_for_timeout(350)

        first_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, first_dismiss)
        if first_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(350)

        scroll = await self._scroll_page_incrementally(page)
        metadata.update(scroll)

        second_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, second_dismiss)
        if second_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(250)
        return metadata

    async def _wait_for_page_settle(self, page: Any) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state("domcontentloaded", timeout=min(self._w.timeout_ms, 8_000))
        with suppress(Exception):
            await wait_for_load_state("load", timeout=min(self._w.timeout_ms, 2_000))

    async def _dismiss_page_popups(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._w._evaluate_page(page, _POPUP_DISMISS_SCRIPT),
                timeout=min(self._w.timeout_ms / 1000, 3),
            )
        except Exception as exc:
            logger.debug("browser_popup_dismiss_failed", error=str(exc))
            return {"clicked_count": 0, "clicked_labels": [], "error": str(exc)}
        if isinstance(value, dict):
            labels = value.get("clicked_labels")
            return {
                "clicked_count": int(value.get("clicked_count") or 0),
                "clicked_labels": labels if isinstance(labels, list) else [],
            }
        return {"clicked_count": 0, "clicked_labels": []}

    def _merge_popup_dismissal(
        self,
        metadata: dict[str, Any],
        dismissed: dict[str, Any],
    ) -> None:
        clicked_count = int(dismissed.get("clicked_count") or 0)
        metadata["popup_dismissed_count"] = (
            int(metadata.get("popup_dismissed_count") or 0) + clicked_count
        )
        labels = metadata.setdefault("popup_dismissed_labels", [])
        if isinstance(labels, list):
            labels.extend(str(label) for label in dismissed.get("clicked_labels") or [])
            del labels[8:]

    async def _scroll_page_incrementally(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._w._evaluate_page(
                    page,
                    _INCREMENTAL_SCROLL_SCRIPT,
                    {
                        "maxSteps": 36,
                        "delayMs": 180,
                        "stepRatio": 0.82,
                    },
                ),
                timeout=min(max(self._w.timeout_ms / 1000, 1.0), 8.0),
            )
        except Exception as exc:
            logger.debug("browser_incremental_scroll_failed", error=str(exc))
            return {"scroll_error": str(exc)}
        if not isinstance(value, dict):
            return {}
        return {
            "scroll_steps": int(value.get("steps") or 0),
            "scroll_y": int(value.get("scroll_y") or 0),
            "scroll_height": int(value.get("scroll_height") or 0),
            "viewport_height": int(value.get("viewport_height") or 0),
            "scroll_at_bottom": bool(value.get("at_bottom")),
        }
