"""Orquestração de chamadas de ferramentas."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import gettempdir

from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolPermissionBehavior,
    ToolProgress,
    ToolResult,
    ToolUseContext,
)


@dataclass(frozen=True, slots=True)
class ToolExecutionEvent:
    """Evento emitido pelo orquestrador."""

    event: str
    call: ToolCall
    progress: ToolProgress | None = None
    result: ToolResult | None = None

    def to_stream_metadata(self) -> dict[str, object]:
        """Converte o evento para metadata de StreamChunk/SSE."""
        payload = {
            "event": self.event,
            "tool_call_id": self.call.id,
            "tool_name": self.call.name,
            "tool_input": self.call.arguments,
        }
        if self.progress is not None:
            payload.update(self.progress.to_stream_dict())
        if self.result is not None:
            payload.update(self.result.to_stream_dict())
        return payload


@dataclass(slots=True)
class _ToolBatch:
    concurrency_safe: bool
    calls: list[ToolCall]


class ToolOrchestrator:
    """Executa ferramentas com paralelismo seguro e bloqueio conservador."""

    def __init__(self, registry: ToolRegistry, config: ToolRuntimeConfig) -> None:
        self._registry = registry
        self._config = config

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

    async def _execute_one_result_event(
        self,
        call: ToolCall,
        context: ToolUseContext,
    ) -> ToolExecutionEvent:
        tool = self._registry.get(call.name)
        if tool is None:
            return ToolExecutionEvent(
                event="tool_error",
                call=call,
                result=ToolResult(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content=f"Error: no such tool available: {call.name}",
                    status=ToolExecutionStatus.ERROR,
                    is_error=True,
                ),
            )

        try:
            validation = await tool.validate_input(call.arguments, context)
            if validation is not None and not validation.allowed:
                return ToolExecutionEvent(
                    event="tool_error",
                    call=call,
                    result=ToolResult(
                        tool_call_id=call.id,
                        tool_name=tool.definition.name,
                        content=validation.message or "Input validation failed",
                        status=ToolExecutionStatus.ERROR,
                        is_error=True,
                        metadata=validation.metadata,
                    ),
                )

            permission = await tool.check_permissions(call.arguments, context)
            if not permission.allowed:
                status = (
                    ToolExecutionStatus.PERMISSION_REQUIRED
                    if permission.behavior == ToolPermissionBehavior.ASK
                    else ToolExecutionStatus.ERROR
                )
                event_name = (
                    "permission_required"
                    if permission.behavior == ToolPermissionBehavior.ASK
                    else "tool_error"
                )
                return ToolExecutionEvent(
                    event=event_name,
                    call=call,
                    result=ToolResult(
                        tool_call_id=call.id,
                        tool_name=tool.definition.name,
                        content=permission.message or "Tool call requires permission",
                        status=status,
                        is_error=True,
                        metadata=permission.metadata,
                    ),
                )

            updated_arguments = permission.updated_input or call.arguments
            if tool.definition.timeout_ms:
                result = await asyncio.wait_for(
                    tool.call(updated_arguments, context, call),
                    timeout=tool.definition.timeout_ms / 1000,
                )
            else:
                result = await tool.call(updated_arguments, context, call)
        except Exception as exc:
            result = ToolResult(
                tool_call_id=call.id,
                tool_name=tool.definition.name,
                content=f"Error calling tool {tool.definition.name}: {exc}",
                status=ToolExecutionStatus.ERROR,
                is_error=True,
            )

        result_metadata = result.metadata if isinstance(result.metadata, dict) else {}
        if "max_result_size_chars" not in result_metadata:
            result = replace(
                result,
                metadata={
                    **result_metadata,
                    "max_result_size_chars": tool.definition.max_result_size_chars,
                },
            )
        result = self._cap_result(result, context)
        if result.is_error:
            event_name = (
                "permission_required"
                if result.status == ToolExecutionStatus.PERMISSION_REQUIRED
                else "tool_error"
            )
        else:
            event_name = "tool_result"
        return ToolExecutionEvent(event=event_name, call=call, result=result)

    def _activity_message(self, tool_name: str) -> str:
        if tool_name in {"Read", "read_file"}:
            return "Reading..."
        if tool_name in {"Grep", "Glob", "search_files"}:
            return "Searching..."
        if tool_name == "shell":
            return "Running..."
        if tool_name in {"Write", "Edit"}:
            return "Editing..."
        if tool_name.startswith("Task") or tool_name == "Task":
            return "Updating task..."
        if tool_name == "WebFetch":
            return "Fetching..."
        if tool_name == "BrowserSearch":
            return "Searching..."
        if tool_name in {
            "BrowserOpen",
            "BrowserListTabs",
            "BrowserExtractContent",
            "BrowserGetHtml",
        }:
            return "Browsing..."
        return "Running tool..."

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

    def _cap_result(self, result: ToolResult, context: ToolUseContext) -> ToolResult:
        max_chars = min(
            result.metadata.get("max_result_size_chars", result.metadata.get("limit", 20_000))
            if isinstance(result.metadata, dict)
            else 20_000,
            int(context.limits.get("result_max_chars", 20_000)),
        )
        if len(result.content) <= max_chars:
            return result

        storage_ref = self._persist_large_result(result, context)
        truncated = result.content[:max_chars] + "\n[Output truncated.]"
        metadata = {
            **result.metadata,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
        }
        data = {
            **result.data,
            "truncated": True,
            "original_chars": len(result.content),
            "storage_ref": storage_ref,
        }
        return replace(result, content=truncated, metadata=metadata, data=data)

    def _persist_large_result(self, result: ToolResult, context: ToolUseContext) -> str | None:
        raw_root = context.limits.get("tool_result_storage_root")
        root = Path(str(raw_root)).expanduser() if raw_root else Path(gettempdir())
        storage_dir = root / "personagent-tool-results" / context.conversation_id
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
            path = storage_dir / f"{result.tool_call_id}.txt"
            path.write_text(result.content, encoding="utf-8")
            return str(path)
        except OSError:
            return None


__all__ = ["ToolExecutionEvent", "ToolOrchestrator"]
