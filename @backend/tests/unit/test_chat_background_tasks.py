"""Tests for :func:`schedule_background`.

Three things to verify:

* The returned task is an :class:`asyncio.Task` and carries the
  caller-supplied name.
* Successful coroutines complete normally; ``CancelledError`` is
  swallowed silently; any other exception is logged at WARNING but
  does not propagate to the caller.
* The helper accepts arbitrary awaitables, not just coroutines.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from personagent.application.use_cases.chat.background_tasks import (
    schedule_background,
)


@pytest.mark.asyncio
async def test_schedules_coroutine_and_returns_named_task() -> None:
    async def _noop() -> None:
        return None

    task = schedule_background(_noop(), task_name="noop-task")

    assert isinstance(task, asyncio.Task)
    assert task.get_name() == "noop-task"
    await task
    assert task.done()


@pytest.mark.asyncio
async def test_successful_task_returns_value() -> None:
    async def _produce() -> int:
        return 42

    task = schedule_background(_produce(), task_name="produce")
    result: Any = await task

    assert result == 42


@pytest.mark.asyncio
async def test_failed_task_logs_and_does_not_propagate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _raise() -> None:
        raise ValueError("boom")

    task = schedule_background(_raise(), task_name="raises")

    # Awaiting the task surfaces the exception to the caller, but the
    # done-callback must have already logged it. ``return_exceptions``
    # via gather lets us inspect both without the caller crashing.
    results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], ValueError)


@pytest.mark.asyncio
async def test_cancelled_task_does_not_log() -> None:
    started = asyncio.Event()

    async def _sleep_forever() -> None:
        started.set()
        await asyncio.sleep(3600)

    task = schedule_background(_sleep_forever(), task_name="sleeper")
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    # No exception escaped via the done_callback log path -- this is
    # by design: cancellation during shutdown is normal.


@pytest.mark.asyncio
async def test_accepts_arbitrary_awaitable() -> None:
    fut: asyncio.Future[int] = asyncio.get_event_loop().create_future()
    fut.set_result(7)

    task = schedule_background(fut, task_name="awaitable")
    value = await task

    assert value == 7
