"""Fire-and-forget asyncio task scheduling helper.

Used by ``ChatCompletionUseCase`` for non-critical follow-up work that
should not block the streaming turn (e.g. operational-memory capture
of the user message). Failures are logged at WARNING and swallowed so
a failing background task can never crash the chat turn.

The helper is a free function with no per-call state -- it lives in
its own module rather than ``chat.helpers`` because that module is
documented as pure / sync, and this helper touches the asyncio event
loop. Keeping it separate keeps ``chat.helpers`` honest.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def schedule_background(coro: Awaitable[Any], *, task_name: str) -> asyncio.Task[Any]:
    """Schedule ``coro`` as a background task and log unhandled failures.

    ``CancelledError`` is treated as normal shutdown and never logged.
    Any other exception is logged with ``exc_info`` so it is visible in
    structured logs without interrupting the caller's flow.

    Returns the spawned task so callers (typically tests) can await
    completion explicitly when needed. Production callers do not need
    to keep the reference.
    """

    task: asyncio.Task[Any] = asyncio.create_task(
        _ensure_coroutine(coro), name=task_name
    )

    def _log_failure(done: asyncio.Task[Any]) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning(
                "background_task_failed", task_name=task_name, exc_info=True
            )

    task.add_done_callback(_log_failure)
    return task


async def _ensure_coroutine(awaitable: Awaitable[Any]) -> Any:
    """Adapter so ``schedule_background`` accepts any awaitable.

    ``asyncio.create_task`` only accepts coroutines/generators, so we
    wrap any awaitable in a trivial coroutine to avoid type errors at
    the call site -- callers can pass either ``async def`` results or
    other awaitables transparently.
    """

    return await awaitable
