"""Thin investigation state carriers for the chat completion pipeline.

These dataclasses track only objective facts.  All guidance text lives in the
system prompt (see ``domain/prompts/prompt.py``); no hardcoded path patterns,
surface heuristics, or English prose belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from personagent.application.dto import ChatRequestDTO
from personagent.domain.prompts.investigation_taxonomy import InvestigationDepth

InvestigationPhase = Literal["classify", "discover", "inspect", "verify", "synthesize"]

_INVESTIGATION_PHASES: tuple[InvestigationPhase, ...] = (
    "classify",
    "discover",
    "inspect",
    "verify",
    "synthesize",
)


def _dedupe_append(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _tool_name(call_or_result: Any) -> str:
    if isinstance(call_or_result, dict):
        function = call_or_result.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(call_or_result.get("name") or "")
    return str(
        getattr(call_or_result, "name", None)
        or getattr(call_or_result, "tool_name", "")
        or ""
    )


def _tool_args(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        function = call.get("function")
        raw_arguments = (
            function.get("arguments")
            if isinstance(function, dict)
            else call.get("arguments")
        )
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str):
            import json

            try:
                parsed = json.loads(raw_arguments)
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}
    arguments = getattr(call, "arguments", None)
    return arguments if isinstance(arguments, dict) else {}


@dataclass(slots=True)
class InvestigationState:
    """Lightweight progress tracker for repository-facing investigations.

    Normal chat turns keep ``active=False`` and take the existing short path.
    The model is guided by the system prompt investigation contract; this
    object only tracks phase/depth metadata for telemetry and loop control.
    """

    depth: InvestigationDepth = "standard"
    objective: str = ""
    tool_iterations: int = 0
    active: bool = False
    phase: InvestigationPhase = "classify"

    @classmethod
    def classify(cls, request: ChatRequestDTO) -> InvestigationState:
        """Create state from request fields.

        ``investigation_depth`` is taken directly from the DTO; the caller
        (API route / profile) is responsible for resolving ``"auto"`` to a
        concrete depth if desired.
        """
        depth = request.investigation_depth or "light"
        if depth == "auto":
            depth = "light"
        return cls(
            depth=depth,
            objective=request.message.strip(),
            active=request.tools_enabled,
            phase="discover" if request.tools_enabled else "classify",
        )

    def advance(self, phase: InvestigationPhase) -> None:
        if not self.active:
            return
        current = _INVESTIGATION_PHASES.index(self.phase)
        target = _INVESTIGATION_PHASES.index(phase)
        if target >= current:
            self.phase = phase

    def to_metadata(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "phase": self.phase,
            "depth": self.depth,
            "objective": self.objective,
            "tool_iterations": self.tool_iterations,
        }


@dataclass(slots=True)
class TurnCoverage:
    """Per-turn tool coverage telemetry surfaced on assistant metadata."""

    tool_names: list[str] = field(default_factory=list)
    search_patterns: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    files_edited: list[str] = field(default_factory=list)
    mcp_resources_read: list[str] = field(default_factory=list)
    memory_items_injected: int = 0

    def record_prompt_metadata(self, metadata: dict[str, Any] | None) -> None:
        if not isinstance(metadata, dict):
            return
        injected = metadata.get("memory_items_injected")
        if isinstance(injected, int):
            self.memory_items_injected = max(self.memory_items_injected, injected)

    def record_tool_calls(self, tool_calls: list[Any] | None) -> None:
        """Record assistant-issued tool calls before execution."""
        for call in tool_calls or []:
            name = _tool_name(call)
            args = _tool_args(call)
            _dedupe_append(self.tool_names, name)
            for key in ("pattern", "query", "glob"):
                if key in args:
                    _dedupe_append(self.search_patterns, args.get(key))
            if path := args.get("path"):
                if isinstance(path, str):
                    _dedupe_append(self.files_read, path)

    def record_tool_result(self, result: Any) -> None:
        """Record a completed tool result."""
        name = _tool_name(result)
        _dedupe_append(self.tool_names, name)
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return
        result_type = data.get("type")
        if result_type == "file_read":
            _dedupe_append(
                self.files_read, data.get("display_path") or data.get("path")
            )
        elif result_type in {"file_write", "file_edit"}:
            _dedupe_append(
                self.files_edited, data.get("display_path") or data.get("path")
            )
        elif result_type == "mcp_resource":
            server, uri = data.get("server"), data.get("uri")
            if server or uri:
                _dedupe_append(
                    self.mcp_resources_read, f"{server or ''}:{uri or ''}"
                )
        for key in ("pattern", "query", "glob"):
            if key in data:
                _dedupe_append(self.search_patterns, data.get(key))

    def to_metadata(self) -> dict[str, Any]:
        return {
            "tool_names": list(self.tool_names),
            "search_patterns": list(self.search_patterns),
            "files_read": list(self.files_read),
            "files_edited": list(self.files_edited),
            "mcp_resources_read": list(self.mcp_resources_read),
            "memory_items_injected": self.memory_items_injected,
        }
