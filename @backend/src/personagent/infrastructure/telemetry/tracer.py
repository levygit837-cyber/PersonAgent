"""OpenTelemetry TracerProvider configuration."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from personagent.infrastructure.telemetry.exporters import JsonFileExporter


def configure_tracing(
    *,
    service_name: str = "personagent",
    export_to: str = "console",
    file_path: str | None = None,
) -> trace.Tracer:
    """Configure and return a tracer for PersonAgent.

    Args:
        service_name: Service name for the TracerProvider resource.
        export_to: Export target — "console", "file", or "none".
        file_path: Path for JSON file exporter (only used when export_to="file").

    Returns:
        A Tracer instance ready for instrumentation.
    """
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider) and existing._active_span_processor:
        return trace.get_tracer(service_name)

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )

    if export_to == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif export_to == "file":
        path = file_path or "traces.json"
        provider.add_span_processor(SimpleSpanProcessor(JsonFileExporter(path)))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
