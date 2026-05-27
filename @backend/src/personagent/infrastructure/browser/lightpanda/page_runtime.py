"""Page evaluation, runtime detection, and CDP command helpers."""

from __future__ import annotations

import inspect
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)

_MAX_BROWSER_SCRIPT_RESULT_CHARS = 12_000


class BrowserPageRuntime:
    """Script evaluation, page runtime detection, and bounded result helpers."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    async def page_runtime(self, page: Any) -> str:
        return "lightpanda" if await self._w._browser_runtime.is_lightpanda_page(page) else "chrome_cdp"

    async def is_lightpanda_page(self, page: Any) -> bool:
        user_agent = await self._w.element_helpers.safe_user_agent(page)
        return user_agent.lower().startswith("lightpanda/")

    def bounded_script_result(self, value: Any) -> tuple[str, Any | None, bool]:
        try:
            result_text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            result_text = str(value)
        truncated = len(result_text) > _MAX_BROWSER_SCRIPT_RESULT_CHARS
        if truncated:
            result_text = result_text[:_MAX_BROWSER_SCRIPT_RESULT_CHARS].rstrip()
        result: Any | None
        if truncated:
            result = None
        else:
            try:
                result = json.loads(result_text)
            except Exception:
                result = result_text
        return result_text, result, truncated

    async def cdp_command_for_page(
        self,
        page: Any,
        *,
        url: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        context = getattr(page, "context", None)
        if callable(context):
            with suppress(Exception):
                context = context()
        new_cdp_session = getattr(context, "new_cdp_session", None)
        if callable(new_cdp_session):
            cdp_session = await new_cdp_session(page)
            try:
                return await cdp_session.send(method, params or {})
            finally:
                detach = getattr(cdp_session, "detach", None)
                if callable(detach):
                    with suppress(Exception):
                        result = detach()
                        if inspect.isawaitable(result):
                            await result
        return await self._w._cdp_runtime.lightpanda_raw_cdp_command(
            url=url or "about:blank",
            method=method,
            params=params or {},
        )

    def first_open_context_page(self, context: Any) -> Any | None:
        raw_pages = getattr(context, "pages", None)
        if not raw_pages:
            return None
        for page in list(raw_pages):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return None

    async def evaluate_page(
        self,
        page: Any,
        script: str,
        arg: Any | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if arg is None:
                    return await page.evaluate(script)
                return await page.evaluate(script, arg)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "Execution context was destroyed" not in message:
                    raise
                if attempt == 2:
                    break
                with suppress(Exception):
                    await page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(self._w.timeout_ms, 5_000),
                    )
                with suppress(Exception):
                    await page.wait_for_timeout(250)
        if last_error is not None:
            raise last_error
        return None
