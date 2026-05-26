"""Event types and batch data-structures for tool orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from personagent.domain.tools import (
    ToolCall,
    ToolProgress,
    ToolResult,
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
