"""Runtime tracing for QA request executions."""

from __future__ import annotations

import asyncio
import contextvars
import secrets
import sys
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType, FrameType
from typing import Any

from opentelemetry import trace

from personagent.application.qa.contracts import QARuntimeEventData, RuntimeEventType, TraceMode
from personagent.application.qa.redaction import redact_mapping

_ACTIVE_TRACE: contextvars.ContextVar[_TraceState | None] = contextvars.ContextVar(
    "personagent_qa_trace",
    default=None,
)


@dataclass
class _OpenCall:
    event_id: str
    span_id: str
    started_at: float


@dataclass
class _TraceState:
    session_id: str
    request_id: str
    trace_id: str
    source_roots: tuple[Path, ...]
    excluded_fragments: tuple[str, ...]
    mode: TraceMode
    event_bus: QARuntimeEventBus
    max_events: int = 2_000
    events: list[QARuntimeEventData] = field(default_factory=list)
    sequence: int = 0
    call_stack: list[_OpenCall] = field(default_factory=list)
    code_stacks: dict[CodeType, list[_OpenCall]] = field(default_factory=lambda: defaultdict(list))

    def accepts_code(self, code: CodeType) -> bool:
        path = Path(code.co_filename).resolve()
        if any(fragment in path.as_posix() for fragment in self.excluded_fragments):
            return False
        return any(_is_relative_to(path, root) for root in self.source_roots)

    def rel_file(self, code: CodeType) -> str:
        path = Path(code.co_filename).resolve()
        for root in self.source_roots:
            if _is_relative_to(path, root):
                return path.relative_to(root).as_posix()
        return path.as_posix()

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def add_event(
        self,
        *,
        event_type: RuntimeEventType,
        code: CodeType,
        line: int | None = None,
        span_id: str | None = None,
        parent_id: str | None = None,
        duration_ms: float | None = None,
        exception: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> QARuntimeEventData | None:
        if len(self.events) >= self.max_events:
            return None
        event = QARuntimeEventData(
            id=f"evt_{self.next_sequence():06d}",
            session_id=self.session_id,
            request_id=self.request_id,
            sequence=self.sequence,
            trace_id=self.trace_id,
            span_id=span_id,
            parent_id=parent_id,
            event_type=event_type,
            function=code.co_name,
            file=self.rel_file(code),
            line=line if line is not None else code.co_firstlineno,
            duration_ms=duration_ms,
            exception=exception,
            sanitized_payload=payload or {},
        )
        self.events.append(event)
        self.event_bus.publish(self.session_id, event)
        return event


class QARuntimeEventBus:
    """Small in-process pub/sub bus for QA SSE streams."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[QARuntimeEventData]]] = defaultdict(set)

    def publish(self, session_id: str, event: QARuntimeEventData) -> None:
        subscribers = tuple(self._subscribers.get(session_id, ()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncIterator[asyncio.Queue[QARuntimeEventData]]:
        queue: asyncio.Queue[QARuntimeEventData] = asyncio.Queue(maxsize=500)
        self._subscribers[session_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                self._subscribers.pop(session_id, None)


class PythonRuntimeTracer:
    """Capture runtime function and line events for one awaited operation."""

    def __init__(self, *, event_bus: QARuntimeEventBus | None = None) -> None:
        self.event_bus = event_bus or QARuntimeEventBus()
        self._lock = asyncio.Lock()
        self._tracer = trace.get_tracer("personagent.qa")

    async def capture(
        self,
        *,
        session_id: str,
        request_id: str,
        source_roots: list[Path],
        mode: TraceMode,
        request_payload: dict[str, Any],
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, list[QARuntimeEventData], str]:
        """Trace an awaited operation and return result, events, and trace id."""
        async with self._lock:
            trace_id = secrets.token_hex(16)
            state = _TraceState(
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                source_roots=tuple(root.resolve() for root in source_roots),
                excluded_fragments=(
                    "/application/qa/",
                    "/interfaces/api/routes/qa.py",
                    "/site-packages/",
                    "/.venv/",
                ),
                mode=mode,
                event_bus=self.event_bus,
                max_events=4_000 if mode == TraceMode.LINE else 1_000,
            )
            token = _ACTIVE_TRACE.set(state)
            try:
                with self._tracer.start_as_current_span(
                    "qa.request",
                    attributes={
                        "qa.session_id": session_id,
                        "qa.request_id": request_id,
                        "qa.trace_mode": mode.value,
                        "code.function.name": "qa.request",
                    },
                ):
                    state.events.append(
                        QARuntimeEventData(
                            id="evt_000000",
                            session_id=session_id,
                            request_id=request_id,
                            sequence=0,
                            trace_id=trace_id,
                            span_id=secrets.token_hex(8),
                            event_type=RuntimeEventType.REQUEST,
                            function="qa.request",
                            sanitized_payload=redact_mapping(request_payload),
                        )
                    )
                    self.event_bus.publish(session_id, state.events[-1])
                    if _can_use_sys_monitoring():
                        result = await self._capture_with_monitoring(state, operation)
                    else:
                        result = await self._capture_with_settrace(state, operation)
                    return result, list(state.events), trace_id
            finally:
                _ACTIVE_TRACE.reset(token)

    async def _capture_with_monitoring(
        self,
        state: _TraceState,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        monitoring = _sys_monitoring()
        tool_id = _claim_tool_id("personagent-qa-runtime")
        event_set = monitoring.events.PY_START | monitoring.events.PY_RETURN | monitoring.events.RAISE
        if state.mode in {TraceMode.BLOCKS, TraceMode.LINE}:
            event_set |= monitoring.events.LINE
        try:
            monitoring.register_callback(tool_id, monitoring.events.PY_START, _monitoring_start)
            monitoring.register_callback(tool_id, monitoring.events.PY_RETURN, _monitoring_return)
            monitoring.register_callback(tool_id, monitoring.events.RAISE, _monitoring_raise)
            if state.mode in {TraceMode.BLOCKS, TraceMode.LINE}:
                monitoring.register_callback(tool_id, monitoring.events.LINE, _monitoring_line)
            monitoring.set_events(tool_id, event_set)
            return await operation()
        finally:
            monitoring.set_events(tool_id, monitoring.events.NO_EVENTS)
            monitoring.register_callback(tool_id, monitoring.events.PY_START, None)
            monitoring.register_callback(tool_id, monitoring.events.PY_RETURN, None)
            monitoring.register_callback(tool_id, monitoring.events.RAISE, None)
            if state.mode in {TraceMode.BLOCKS, TraceMode.LINE}:
                monitoring.register_callback(tool_id, monitoring.events.LINE, None)
            monitoring.free_tool_id(tool_id)

    async def _capture_with_settrace(
        self,
        state: _TraceState,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        previous = sys.gettrace()

        def tracer(frame: FrameType, event: str, arg: Any) -> Any:
            active = _ACTIVE_TRACE.get()
            if active is not state or not state.accepts_code(frame.f_code):
                return tracer
            if event == "call":
                _record_call(state, frame.f_code)
            elif event == "return":
                _record_return(state, frame.f_code)
            elif event == "exception":
                exc_type, exc, _ = arg
                _record_exception(state, frame.f_code, frame.f_lineno, f"{exc_type.__name__}: {exc}")
            elif event == "line" and state.mode in {TraceMode.BLOCKS, TraceMode.LINE}:
                _record_line(state, frame.f_code, frame.f_lineno)
            return tracer

        sys.settrace(tracer)
        try:
            return await operation()
        finally:
            sys.settrace(previous)


def _monitoring_start(code: CodeType, _instruction_offset: int) -> None:
    state = _ACTIVE_TRACE.get()
    if state is not None and state.accepts_code(code):
        _record_call(state, code)


def _monitoring_return(code: CodeType, _instruction_offset: int, _retval: object) -> None:
    state = _ACTIVE_TRACE.get()
    if state is not None and state.accepts_code(code):
        _record_return(state, code)


def _monitoring_raise(code: CodeType, _instruction_offset: int, exception: BaseException) -> None:
    state = _ACTIVE_TRACE.get()
    if state is not None and state.accepts_code(code):
        _record_exception(state, code, code.co_firstlineno, f"{type(exception).__name__}: {exception}")


def _monitoring_line(code: CodeType, line_number: int) -> None:
    state = _ACTIVE_TRACE.get()
    if state is not None and state.accepts_code(code):
        _record_line(state, code, line_number)


def _record_call(state: _TraceState, code: CodeType) -> None:
    parent_id = state.call_stack[-1].span_id if state.call_stack else None
    span_id = secrets.token_hex(8)
    event = state.add_event(
        event_type=RuntimeEventType.CALL,
        code=code,
        line=code.co_firstlineno,
        span_id=span_id,
        parent_id=parent_id,
        payload={
            "code.file.path": state.rel_file(code),
            "code.function.name": code.co_name,
            "code.line.number": code.co_firstlineno,
        },
    )
    if event is None:
        return
    open_call = _OpenCall(event_id=event.id, span_id=span_id, started_at=time.perf_counter())
    state.call_stack.append(open_call)
    state.code_stacks[code].append(open_call)


def _record_return(state: _TraceState, code: CodeType) -> None:
    open_call = state.code_stacks.get(code, []).pop() if state.code_stacks.get(code) else None
    if open_call is None:
        return
    if state.call_stack and state.call_stack[-1].event_id == open_call.event_id:
        state.call_stack.pop()
    else:
        state.call_stack = [item for item in state.call_stack if item.event_id != open_call.event_id]
    state.add_event(
        event_type=RuntimeEventType.RETURN,
        code=code,
        line=code.co_firstlineno,
        span_id=open_call.span_id,
        parent_id=state.call_stack[-1].span_id if state.call_stack else None,
        duration_ms=round((time.perf_counter() - open_call.started_at) * 1000, 3),
    )


def _record_line(state: _TraceState, code: CodeType, line_number: int) -> None:
    parent_id = state.call_stack[-1].span_id if state.call_stack else None
    state.add_event(
        event_type=RuntimeEventType.LINE,
        code=code,
        line=line_number,
        span_id=parent_id,
        parent_id=parent_id,
    )


def _record_exception(state: _TraceState, code: CodeType, line_number: int, exception: str) -> None:
    parent_id = state.call_stack[-1].span_id if state.call_stack else None
    state.add_event(
        event_type=RuntimeEventType.EXCEPTION,
        code=code,
        line=line_number,
        span_id=parent_id,
        parent_id=parent_id,
        exception=exception,
    )


def _can_use_sys_monitoring() -> bool:
    return hasattr(sys, "monitoring")


def _sys_monitoring() -> Any:
    return sys.__dict__["monitoring"]


def _claim_tool_id(name: str) -> int:
    monitoring = _sys_monitoring()
    for tool_id in (4, 3, 2, 1, 0, 5):
        try:
            existing = monitoring.get_tool(tool_id)
            if existing is None:
                monitoring.use_tool_id(tool_id, name)
                return tool_id
        except ValueError:
            continue
    raise RuntimeError("No available sys.monitoring tool id for QA runtime tracer")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


__all__ = ["PythonRuntimeTracer", "QARuntimeEventBus"]
