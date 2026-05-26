"""Browser connection management — endpoint resolution, Playwright, container autostart."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.url_utils import (
    is_local_lightpanda_endpoint as _is_local_lightpanda_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_lightpanda_cdp_endpoint,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)


class BrowserConnection:
    """Manages CDP endpoint resolution, Playwright connections, and container autostart."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    async def connect_browser(self) -> Any:
        if not self._w.enabled:
            raise BrowserUnavailableError("LightPanda browser tools are disabled.")
        last_error: Exception | None = None
        for attempt in range(3):
            endpoint = await self.resolve_endpoint()
            try:
                if self._w._connector is not None:
                    return await self._w._connector(endpoint)
                return await self.connect_with_playwright(endpoint)
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        if await self.try_start_lightpanda_container():
            for attempt in range(4):
                endpoint = await self.resolve_endpoint()
                try:
                    if self._w._connector is not None:
                        return await self._w._connector(endpoint)
                    return await self.connect_with_playwright(endpoint)
                except Exception as exc:
                    last_error = exc
                    if attempt == 3:
                        break
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise BrowserUnavailableError(
            "Browser CDP endpoint is unavailable. Start LightPanda with "
            "`docker compose up -d lightpanda` or start Chrome/Chromium with "
            "`--remote-debugging-port=9222`, then verify /json/version."
        ) from last_error

    async def try_start_lightpanda_container(self) -> bool:
        if (
            not self._w.auto_start_lightpanda
            or self._w._connector is not None
            or not _is_local_lightpanda_endpoint(self._w.cdp_url)
        ):
            return False
        async with self._w._container_start_lock:
            if self._w._container_start_attempted:
                return False
            self._w._container_start_attempted = True
            repo_root = Path(__file__).resolve().parents[6]
            compose_file = repo_root / "docker-compose.yml"
            if not compose_file.exists():
                return False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "compose",
                    "up",
                    "-d",
                    "lightpanda",
                    cwd=repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (OSError, TimeoutError) as exc:
                logger.warning("lightpanda_container_autostart_failed", error=str(exc))
                return False
            output = (
                stdout_data.decode("utf-8", errors="replace")
                + stderr_data.decode("utf-8", errors="replace")
            ).strip()
            if proc.returncode != 0:
                logger.warning(
                    "lightpanda_container_autostart_failed",
                    returncode=proc.returncode,
                    output=output,
                )
                return False
            logger.info("lightpanda_container_autostarted", output=output)
            return True

    async def connect_with_playwright(self, endpoint: str) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `playwright` is required for LightPanda browser tools."
            ) from exc

        async with self._w._lock:
            if self._w._playwright is None:
                self._w._playwright = await async_playwright().start()
            playwright = self._w._playwright
        return await playwright.chromium.connect_over_cdp(
            endpoint,
            timeout=self._w.timeout_ms,
        )

    async def resolve_endpoint(self) -> str:
        version_payload = None
        if self._w.cdp_url.strip().startswith(("http://", "https://")):
            with suppress(Exception):
                async with httpx.AsyncClient(timeout=self._w.timeout_ms / 1000) as client:
                    response = await client.get(f"{self._w.cdp_url.rstrip('/')}/json/version")
                    response.raise_for_status()
                    version_payload = response.json()
        return normalize_lightpanda_cdp_endpoint(self._w.cdp_url, version_payload)
