"""Search-provider block / CAPTCHA detection.

Extracted from ``lightpanda.py`` (Slice 13).  The ``BlockDetector``
helper checks whether a search page is showing a CAPTCHA or
unusual-traffic interstitial for Google, Bing, and Yahoo.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from personagent.infrastructure.browser.models import BrowserBlockedError

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker


class BlockDetector:
    """Detects search-provider blocks on a browser page."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Internal: extract page body sample
    # ------------------------------------------------------------------

    async def _page_body_sample(self, page: Any) -> str:
        with suppress(Exception):
            return str(
                await self._w._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText "
                    "|| document.body.textContent)) || '').slice(0, 3000)",
                )
                or ""
            )
        return ""

    # ------------------------------------------------------------------
    # Provider-specific checks
    # ------------------------------------------------------------------

    async def raise_if_google_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "sorry/index" not in page_url and "google." not in page_url:
            return
        raw_title = await self._w._safe_title(page)
        title = raw_title.lower()
        is_google_surface = "google." in page_url or "google" in title
        if "sorry/index" not in page_url and not is_google_surface:
            return
        raw_sample = await self._page_body_sample(page)
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "our systems have detected",
            "before you continue",
            "consent.google",
            "enable javascript on your web browser",
        )
        if "sorry/index" in page_url or (
            is_google_surface
            and any(
                marker in sample or marker in title
                for marker in markers
            )
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Google blocked this browser session with consent, "
                "CAPTCHA, or unusual-traffic checks. "
                "This is a Google/browser-fingerprint block, not a "
                "Playwright CDP connection error.",
                provider="google",
                reason="captcha_or_unusual_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def raise_if_bing_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "bing.com" not in page_url:
            return
        raw_title = await self._w._safe_title(page)
        title = raw_title.lower()
        is_bing_surface = "bing.com" in page_url or "bing" in title
        if not is_bing_surface:
            return
        raw_sample = await self._page_body_sample(page)
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
            "solve this puzzle",
        )
        if any(
            marker in sample or marker in title for marker in markers
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Bing blocked this browser session with CAPTCHA or "
                "automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, "
                "not a Playwright CDP connection error.",
                provider="bing",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def raise_if_yahoo_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "search.yahoo.com" not in page_url:
            return
        raw_title = await self._w._safe_title(page)
        title = raw_title.lower()
        is_yahoo_surface = (
            "search.yahoo.com" in page_url or "yahoo search" in title
        )
        if not is_yahoo_surface:
            return
        raw_sample = await self._page_body_sample(page)
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
        )
        if any(
            marker in sample or marker in title for marker in markers
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Yahoo blocked this browser session with CAPTCHA or "
                "automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, "
                "not a Playwright CDP connection error.",
                provider="yahoo",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    # ------------------------------------------------------------------
    # Composite check
    # ------------------------------------------------------------------

    async def raise_if_search_blocked(self, page: Any) -> None:
        await self.raise_if_google_blocked(page)
        await self.raise_if_bing_blocked(page)
        await self.raise_if_yahoo_blocked(page)
