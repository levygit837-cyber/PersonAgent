"""Page-level wait, title, and readiness helpers.

Extracted from ``lightpanda.py`` (Slice 14).  The ``PageHelpers``
class owns:

* ``_wait_for_page_visual_ready`` — wait for CSS/fonts + snapshot script
* ``_wait_for_page_load_complete`` — wait for the ``load`` event
* ``_safe_title`` — page title with timeout fallback
* ``_safe_title_for_url`` — title via raw CDP evaluate
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

_STYLE_READY_SNAPSHOT_SCRIPT = r"""
async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(true)));
  const links = Array.from(document.querySelectorAll('link[rel~="stylesheet"], link[as="style"], link[href$=".css"]'));
  const settleLink = (link) => new Promise((resolve) => {
    try {
      if (link.sheet || link.getAttribute('data-personagent-embedded-css') === 'true') {
        resolve(true);
        return;
      }
    } catch {
      resolve(false);
      return;
    }
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    link.addEventListener('load', () => finish(true), { once: true });
    link.addEventListener('error', () => finish(false), { once: true });
    setTimeout(() => {
      try {
        finish(Boolean(link.sheet));
      } catch {
        finish(false);
      }
    }, 2600);
  });
  const fontsReady = document.fonts && document.fonts.ready
    ? Promise.race([document.fonts.ready.then(() => true).catch(() => false), wait(2600).then(() => false)])
    : Promise.resolve(true);
  const results = await Promise.allSettled([...links.map(settleLink), fontsReady]);
  await frame();
  await frame();
  const loaded = results.slice(0, links.length).filter((result) => result.status === 'fulfilled' && result.value !== false).length;
  const fontReadyResult = results[links.length];
  const fontsReadyValue = !fontReadyResult || (fontReadyResult.status === 'fulfilled' && fontReadyResult.value !== false);
  return {
    personagentStyleReadyProbe: true,
    style_ready: (links.length === 0 || loaded >= links.length) && fontsReadyValue,
    stylesheet_count: links.length,
    stylesheet_loaded_count: loaded,
    fonts_ready: fontsReadyValue
  };
}
"""

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)


class PageHelpers:
    """Page-level wait / title / readiness helpers for the browser worker."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    async def wait_for_page_visual_ready(
        self, page: Any
    ) -> dict[str, Any]:
        await self.wait_for_page_load_complete(page)
        metrics: dict[str, Any] = {
            "style_ready": True,
            "stylesheet_count": 0,
            "stylesheet_loaded_count": 0,
            "fonts_ready": True,
        }
        with suppress(Exception):
            value = await asyncio.wait_for(
                self._w._evaluate_page(
                    page, _STYLE_READY_SNAPSHOT_SCRIPT
                ),
                timeout=min(
                    max(self._w.timeout_ms / 1000, 1.0), 5.0
                ),
            )
            if isinstance(value, Mapping):
                metrics.update(
                    {
                        "style_ready": bool(
                            value.get(
                                "style_ready", metrics["style_ready"]
                            )
                        ),
                        "stylesheet_count": int(
                            value.get("stylesheet_count") or 0
                        ),
                        "stylesheet_loaded_count": int(
                            value.get("stylesheet_loaded_count") or 0
                        ),
                        "fonts_ready": bool(
                            value.get(
                                "fonts_ready", metrics["fonts_ready"]
                            )
                        ),
                    }
                )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        return metrics

    async def wait_for_page_load_complete(
        self, page: Any, *, timeout_ms: int | None = None
    ) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state(
                "load",
                timeout=min(
                    timeout_ms or self._w.timeout_ms, 5_000
                ),
            )

    # ------------------------------------------------------------------
    # Title helpers
    # ------------------------------------------------------------------

    async def safe_title(self, page: Any) -> str:
        try:
            title = await asyncio.wait_for(
                page.title(),
                timeout=min(self._w.timeout_ms / 1000, 3),
            )
            return str(title or "").strip()
        except TimeoutError as exc:
            logger.debug("lightpanda_title_timeout", error=str(exc))
            return ""
        except Exception:
            return ""

    async def safe_title_for_url(self, url: str) -> str:
        value = await self._w._raw_runtime_evaluate_value(
            url,
            "document.title || ''",
            label="title",
            timeout=min(self._w.timeout_ms / 1000, 5),
        )
        return str(value or "").strip() if isinstance(value, str) else ""
