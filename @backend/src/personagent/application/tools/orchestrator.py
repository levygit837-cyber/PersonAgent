"""Orquestração de chamadas de ferramentas."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import gettempdir
from typing import Any

from personagent.application.tools.registry import ToolRegistry
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.domain.exceptions import (
    PersonAgentError,
    ShellCommandDeniedError,
    ToolError,
    ToolInputValidationError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolPermissionRequiredError,
    ToolTimeoutError,
)
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
            error = ToolNotFoundError(
                f"No such tool available: {call.name}",
                metadata={"tool_name": call.name},
            )
            return ToolExecutionEvent(
                event="tool_error",
                call=call,
                result=self._error_result(call, call.name, error),
            )

        try:
            validation = await tool.validate_input(call.arguments, context)
            if validation is not None and not validation.allowed:
                error = ToolInputValidationError(
                    validation.message or "Input validation failed.",
                    metadata={
                        "tool_name": tool.definition.name,
                        **validation.metadata,
                    },
                )
                return ToolExecutionEvent(
                    event="tool_error",
                    call=call,
                    result=self._error_result(call, tool.definition.name, error),
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
                if permission.behavior == ToolPermissionBehavior.ASK:
                    error = ToolPermissionRequiredError(
                        permission.message or "Tool call requires permission.",
                        metadata={
                            "tool_name": tool.definition.name,
                            **permission.metadata,
                        },
                    )
                else:
                    error_class = (
                        ShellCommandDeniedError
                        if tool.definition.name == "shell"
                        else ToolPermissionDeniedError
                    )
                    error = error_class(
                        permission.message or "Tool call was denied.",
                        metadata={
                            "tool_name": tool.definition.name,
                            **permission.metadata,
                        },
                    )
                return ToolExecutionEvent(
                    event=event_name,
                    call=call,
                    result=self._error_result(
                        call,
                        tool.definition.name,
                        error,
                        status=status,
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
        except TimeoutError as exc:
            timeout_ms = tool.definition.timeout_ms
            error = ToolTimeoutError(
                f"Tool {tool.definition.name} timed out.",
                metadata={"tool_name": tool.definition.name, "timeout_ms": timeout_ms},
                cause=exc,
            )
            result = self._error_result(call, tool.definition.name, error)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, PersonAgentError)
                else ToolError(
                    f"Error calling tool {tool.definition.name}: {exc}",
                    metadata={"tool_name": tool.definition.name},
                    cause=exc,
                )
            )
            result = self._error_result(call, tool.definition.name, error)

        result_metadata = result.metadata if isinstance(result.metadata, dict) else {}
        if "max_result_size_chars" not in result_metadata:
            result = replace(
                result,
                metadata={
                    **result_metadata,
                    "max_result_size_chars": tool.definition.max_result_size_chars,
                },
            )
        if result.is_error and "error" not in result.metadata:
            error = ToolError(
                result.content or f"Tool {tool.definition.name} failed.",
                metadata={"tool_name": tool.definition.name},
            )
            result = replace(
                result,
                metadata={**result.metadata, **self._error_metadata(error)},
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

    def _error_result(
        self,
        call: ToolCall,
        tool_name: str,
        error: PersonAgentError,
        *,
        status: ToolExecutionStatus = ToolExecutionStatus.ERROR,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name=tool_name,
            content=error.user_message,
            status=status,
            is_error=True,
            metadata=self._error_metadata(error),
        )

    def _error_metadata(self, error: PersonAgentError) -> dict[str, Any]:
        return {"error": error.to_envelope()}

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
            "BrowserReadContentChunk",
            "BrowserGetHtml",
            "BrowserGetElementMap",
            "BrowserClick",
            "BrowserType",
            "BrowserScreenshot",
            "BrowserCloseTab",
            "BrowserReadConsole",
            "BrowserScript",
            "BrowserScroll",
            "BrowserReload",
            "BrowserHistory",
            "BrowserSwitchTab",
            "BrowserWait",
            "BrowserAct",
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
        raw_result_limit = (
            result.metadata.get("max_result_size_chars", result.metadata.get("limit", 20_000))
            if isinstance(result.metadata, dict)
            else 20_000
        )
        try:
            result_limit = 20_000 if raw_result_limit is None else int(raw_result_limit)
        except (TypeError, ValueError):
            result_limit = 20_000
        try:
            context_limit = int(context.limits.get("result_max_chars", 20_000))
        except (TypeError, ValueError):
            context_limit = 20_000
        max_chars = max(1, min(result_limit, context_limit))
        if len(result.content) <= max_chars:
            return result

        storage_ref = self._persist_large_result(result, context)
        structured = self._cap_structured_result(result, max_chars, storage_ref)
        if structured is not None:
            return structured
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

    def _cap_structured_result(
        self,
        result: ToolResult,
        max_chars: int,
        storage_ref: str | None,
    ) -> ToolResult | None:
        if not result.data:
            return None
        try:
            data = deepcopy(result.data)
            if not isinstance(data, dict):
                return None
            data.update(
                {
                    "truncated": True,
                    "original_chars": len(result.content),
                    "storage_ref": storage_ref,
                }
            )
            for _attempt in range(20):
                content = json.dumps(data, ensure_ascii=False)
                if len(content) <= max_chars:
                    return replace(
                        result,
                        content=content,
                        metadata={
                            **result.metadata,
                            "truncated": True,
                            "original_chars": len(result.content),
                            "storage_ref": storage_ref,
                        },
                        data=data,
                    )
                slot = self._largest_string_slot(data)
                if slot is None:
                    return None
                parent, key, value = slot
                marker = "\n[Output truncated.]"
                excess = len(content) - max_chars
                target_len = max(0, len(value) - excess - len(marker) - 200)
                if target_len >= len(value):
                    target_len = max(0, len(value) // 2)
                parent[key] = value[:target_len].rstrip() + marker
        except (TypeError, ValueError):
            return None
        return None

    def _largest_string_slot(self, value: Any) -> tuple[dict[str, Any] | list[Any], Any, str] | None:
        best: tuple[dict[str, Any] | list[Any], Any, str] | None = None

        def visit(node: Any) -> None:
            nonlocal best
            if isinstance(node, dict):
                for key, item in node.items():
                    if isinstance(item, str):
                        if best is None or len(item) > len(best[2]):
                            best = (node, key, item)
                    else:
                        visit(item)
            elif isinstance(node, list):
                for index, item in enumerate(node):
                    if isinstance(item, str):
                        if best is None or len(item) > len(best[2]):
                            best = (node, index, item)
                    else:
                        visit(item)

        visit(value)
        return best

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
