"""Raw CDP command execution and runtime evaluation via websockets."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.models import BrowserUnavailableError
from personagent.infrastructure.browser.search.url_utils import (
    is_retryable_raw_cdp_error as _is_retryable_raw_cdp_error,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)

_RAW_CDP_RETRY_DELAYS = (0.0, 0.5, 1.5, 3.0, 5.0)


class BrowserCdpRuntime:
    """Low-level CDP command sender and runtime evaluator."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    async def raw_runtime_evaluate_value(
        self,
        url: str,
        expression: str,
        *,
        label: str,
        timeout: float,
    ) -> Any:
        if not url or url == "about:blank":
            return None
        try:
            payload = await asyncio.wait_for(
                self._w._cdp_runtime.lightpanda_raw_cdp_command(
                    url=url,
                    method="Runtime.evaluate",
                    params={
                        "expression": expression,
                        "returnByValue": True,
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_timeout", label=label, error=str(exc))
            return None
        except Exception as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_failed", label=label, error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return result.get("value")

    async def lightpanda_raw_cdp_command(
        self,
        *,
        url: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            import websockets
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `websockets` is required for LightPanda native CDP commands."
            ) from exc

        timeout_seconds = self._w.timeout_ms / 1000
        last_error: Exception | None = None
        for attempt, delay in enumerate(_RAW_CDP_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                endpoint = await self._w._connection.resolve_endpoint()
                async with websockets.connect(
                    endpoint,
                    open_timeout=timeout_seconds,
                    close_timeout=min(timeout_seconds, 5),
                    max_size=8 * 1024 * 1024,
                ) as websocket:
                    from personagent.infrastructure.browser.cdp.client import (
                        CdpClient as _RawCdpClient,
                    )

                    client = _RawCdpClient(websocket)
                    created = await client.send("Target.createTarget", {"url": "about:blank"})
                    target_id = str(created.get("targetId") or "")
                    attached = await client.send(
                        "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True},
                    )
                    session_id = str(attached.get("sessionId") or "")
                    try:
                        with suppress(Exception):
                            await client.send("Page.enable", session_id=session_id)
                        await client.send("Page.navigate", {"url": url}, session_id=session_id)
                        with suppress(TimeoutError, asyncio.TimeoutError):
                            await client.wait_for_event(
                                "Page.domContentEventFired",
                                session_id=session_id,
                                timeout=timeout_seconds,
                            )
                        await asyncio.sleep(0.25)
                        return await client.send(method, params or {}, session_id=session_id)
                    finally:
                        if target_id:
                            with suppress(Exception):
                                await client.send("Target.closeTarget", {"targetId": target_id})
            except Exception as exc:
                last_error = exc
                if attempt == len(_RAW_CDP_RETRY_DELAYS) - 1 or not _is_retryable_raw_cdp_error(
                    exc
                ):
                    raise
                logger.debug(
                    "lightpanda_raw_cdp_retry",
                    attempt=attempt + 1,
                    method=method,
                    url=url,
                    error=str(exc),
                )
        if last_error is not None:
            raise last_error
        raise BrowserUnavailableError("LightPanda raw CDP command failed.")
