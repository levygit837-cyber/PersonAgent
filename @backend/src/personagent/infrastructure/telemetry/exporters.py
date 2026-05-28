"""Custom span exporters for stress test tracing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class JsonFileExporter(SpanExporter):
    """Exports spans as JSON lines to a file for post-run analysis."""

    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w")

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            record = _span_to_dict(span)
            self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._file.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self._file.flush()
        return True


def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    ctx = span.get_span_context()
    return {
        "name": span.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
        "start_time": span.start_time,
        "end_time": span.end_time,
        "status": span.status.status_code.name if span.status else "UNSET",
        "attributes": dict(span.attributes) if span.attributes else {},
        "events": [
            {
                "name": event.name,
                "timestamp": event.timestamp,
                "attributes": dict(event.attributes) if event.attributes else {},
            }
            for event in (span.events or [])
        ],
    }
