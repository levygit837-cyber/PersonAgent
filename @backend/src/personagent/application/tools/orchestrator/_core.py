"""Core orchestrator that batches and dispatches tool calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolProgress,
    ToolResult,
    ToolUseContext,
)

from ._events import ToolExecutionEvent, _ToolBatch
from ._execution import _ToolExecutionMixin
from ._result_capping import _ToolResultCappingMixin


class ToolOrchestrator(_ToolExecutionMixin, _ToolResultCappingMixin):
    """Executa ferramentas com paralelismo seguro e bloqueio conservador."""

    def __init__(
        self,
        registry: ToolRegistry,
        config: ToolRuntimeConfig,
        artifact_storage: ArtifactStoragePort | None = None,
    ) -> None:
        self._registry = registry
        self._config = config
        self._artifact_storage = artifact_storage or _default_artifact_storage()

    async def execute(
        self,
        calls: list[ToolCall],
        context: ToolUseContext,
    ) -> AsyncIterator[ToolExecutionEvent]:
        """Executa chamadas, agrupando chamadas concurrency-safe consecutivas."""
        for batch in self._partition(calls):
            if batch.concurrency_safe:
                async for event in self._execute_parallel_batch(batch.calls, context):
                    yield event
            else:
                for call in batch.calls:
                    async for event in self._execute_serial_call(call, context):
                        yield event

    async def execute_collect(
        self,
        calls: list[ToolCall],
        context: ToolUseContext,
    ) -> list[ToolResult]:
        """Executa chamadas e retorna resultados na ordem original."""
        results_by_id: dict[str, ToolResult] = {}
        async for event in self.execute(calls, context):
            if event.result is not None:
                results_by_id[event.call.id] = event.result
        return [results_by_id[call.id] for call in calls if call.id in results_by_id]

    def _partition(self, calls: list[ToolCall]) -> list[_ToolBatch]:
        batches: list[_ToolBatch] = []
        for call in calls:
            tool = self._registry.get(call.name)
            concurrency_safe = False
            if tool is not None:
                try:
                    concurrency_safe = tool.is_concurrency_safe(call.arguments)
                except Exception:
                    concurrency_safe = False

            if (
                concurrency_safe
                and batches
                and batches[-1].concurrency_safe
                and len(batches[-1].calls) < self._config.max_concurrency
            ):
                batches[-1].calls.append(call)
            else:
                batches.append(_ToolBatch(concurrency_safe=concurrency_safe, calls=[call]))
        return batches

    def _start_events(self, calls: list[ToolCall]) -> list[ToolExecutionEvent]:
        return [
            ToolExecutionEvent(
                event="tool_call_started",
                call=call,
                progress=ToolProgress(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    status=ToolExecutionStatus.RUNNING,
                    message=self._activity_message(call.name),
                ),
            )
            for call in calls
        ]

    async def _execute_parallel_batch(
        self,
        calls: list[ToolCall],
        context: ToolUseContext,
    ) -> AsyncIterator[ToolExecutionEvent]:
        for event in self._start_events(calls):
            yield event
        if len(calls) > 1:
            yield self._group_event("tool_group_started", calls, ToolExecutionStatus.RUNNING)

        queue: asyncio.Queue[ToolExecutionEvent | None] = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._run_one_to_queue(call, context, queue)) for call in calls
        ]
        call_index = {call.id: index for index, call in enumerate(calls)}
        result_buffer: dict[int, ToolExecutionEvent] = {}
        next_result_index = 0
        remaining = len(tasks)
        while remaining:
            item = await queue.get()
            if item is None:
                remaining -= 1
                continue
            if item.result is None:
                yield item
                continue
            result_buffer[call_index[item.call.id]] = item
            while next_result_index in result_buffer:
                yield result_buffer.pop(next_result_index)
                next_result_index += 1
        await asyncio.gather(*tasks)
        if len(calls) > 1:
            yield self._group_event("tool_group_finished", calls, ToolExecutionStatus.COMPLETED)

    async def _execute_serial_call(
        self,
        call: ToolCall,
        context: ToolUseContext,
    ) -> AsyncIterator[ToolExecutionEvent]:
        yield self._start_events([call])[0]

        queue: asyncio.Queue[ToolExecutionEvent | None] = asyncio.Queue()
        task = asyncio.create_task(self._run_one_to_queue(call, context, queue))
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        await task

    async def _run_one_to_queue(
        self,
        call: ToolCall,
        context: ToolUseContext,
        queue: asyncio.Queue[ToolExecutionEvent | None],
    ) -> None:
        async def progress_callback(progress: ToolProgress) -> None:
            await queue.put(
                ToolExecutionEvent(
                    event="tool_progress",
                    call=call,
                    progress=progress,
                )
            )

        try:
            result_event = await self._execute_one_result_event(
                call,
                context.with_progress_callback(progress_callback),
            )
            await queue.put(result_event)
        finally:
            await queue.put(None)

    def _group_event(
        self,
        event_name: str,
        calls: list[ToolCall],
        status: ToolExecutionStatus,
    ) -> ToolExecutionEvent:
        return ToolExecutionEvent(
            event=event_name,
            call=calls[0],
            progress=ToolProgress(
                tool_call_id=calls[0].id,
                tool_name=calls[0].name,
                status=status,
                message=f"{len(calls)} tools",
                data={"tool_call_ids": [call.id for call in calls]},
            ),
        )


def _default_artifact_storage() -> ArtifactStoragePort:
    from personagent.infrastructure.persistence.artifacts import LocalArtifactStorage
    return LocalArtifactStorage()
