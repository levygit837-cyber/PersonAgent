"""In-flight state carriers for the chat completion pipeline.

These dataclasses are private to the chat completion use case in the
sense that no external caller should construct them, but they are
exposed publicly (no leading underscore) so that:

* Unit tests can assemble fixtures without going through the full
  ``ChatCompletionUseCase`` boot path.
* Future extraction of helper services (prompt-package assembly,
  context-after-turn metadata, etc.) can take a typed argument instead
  of a raw ``dict[str, Any]``.

Each type is :func:`dataclass(slots=True)` so that constructing one is
cheap and stray attribute writes raise loudly -- the original god-file
relied on dicts and we want to avoid silently growing keys.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from personagent.application.dto import ChatRequestDTO
from personagent.domain.llm_backend.models import GeneratedImage

InvestigationDepth = Literal["light", "standard", "deep", "exhaustive"]
InvestigationPhase = Literal["classify", "discover", "inspect", "verify", "synthesize"]

_INVESTIGATION_PHASES: tuple[InvestigationPhase, ...] = (
    "classify",
    "discover",
    "inspect",
    "verify",
    "synthesize",
)
_DEFAULT_REQUIRED_SURFACES = ["entrypoints", "domain", "adapters", "tests", "config"]
_INVESTIGATION_INTENT_RE = re.compile(
    r"\b("
    r"repo(?:sitory)?|codebase|architecture|architectural|debug|bug|failure|"
    r"trace|root cause|investigate|review|improve|improvement|refactor|"
    r"entrypoint|adapter|domain|test(?:s|ing)?|config(?:uration)?"
    r")\b",
    re.IGNORECASE,
)
_IMPROVEMENT_RE = re.compile(r"\bhow\s+can\s+we\s+improve\b", re.IGNORECASE)
_SEARCH_TOOL_HINTS = frozenset({"grep", "rg", "search", "find", "glob", "toolsearch"})
_READ_TOOL_HINTS = frozenset({"read", "open", "view", "cat", "sed", "head", "tail"})


def _unique_append(values: list[str], value: str, *, max_items: int = 200) -> None:
    normalized = value.strip()
    if not normalized or normalized in values:
        return
    values.append(normalized)
    if len(values) > max_items:
        del values[: len(values) - max_items]


def _tool_call_name(call: dict[str, Any]) -> str:
    function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return str(call.get("name") or "")


def _json_dict(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _path_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip().strip("'\"")
    if not stripped or stripped in {".", "No files matched.", "No matches found."}:
        return ""
    return stripped


def _paths_from_shell_command(command: str) -> set[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths: set[str] = set()
    for token in tokens:
        token = token.strip()
        if not token or token.startswith("-"):
            continue
        if "/" in token or PurePosixPath(token).suffix:
            paths.add(token)
    return paths


@dataclass(slots=True)
class InvestigationState:
    """Lightweight progress tracker for repository-facing investigations.

    Normal chat turns keep ``active=False`` and take the existing short path.
    Repository QA, architecture review, debugging, and improvement requests use
    this object to make the tool loop's investigation phase and evidence
    coverage explicit across streaming and non-streaming executions.
    """

    depth: InvestigationDepth = "standard"
    objective: str = ""
    required_surfaces: list[str] = field(default_factory=lambda: list(_DEFAULT_REQUIRED_SURFACES))
    searched_patterns: list[str] = field(default_factory=list)
    read_files: list[str] = field(default_factory=list)
    tool_iterations: int = 0
    coverage_status: dict[str, bool] = field(default_factory=dict)
    ready_for_final: bool = False
    active: bool = False
    phase: InvestigationPhase = "classify"

    @classmethod
    def classify(cls, request: ChatRequestDTO) -> InvestigationState:
        text_parts = [request.message, request.system_prompt or ""]
        if isinstance(request.metadata, dict):
            text_parts.extend(str(value) for value in request.metadata.values() if isinstance(value, str))
        text = " ".join(text_parts)
        active = bool(_INVESTIGATION_INTENT_RE.search(text) or _IMPROVEMENT_RE.search(text))
        depth = _depth_from_text(text)
        required_surfaces = _required_surfaces_from_text(text)
        return cls(
            depth=depth,
            objective=request.message.strip(),
            required_surfaces=required_surfaces,
            active=active,
            phase="classify",
            coverage_status=dict.fromkeys(required_surfaces, False),
        )

    def advance(self, phase: InvestigationPhase) -> None:
        if not self.active:
            return
        current = _INVESTIGATION_PHASES.index(self.phase)
        target = _INVESTIGATION_PHASES.index(phase)
        if target >= current:
            self.phase = phase

    def record_assistant_tool_calls(self, tool_calls: list[dict[str, Any]] | None) -> None:
        if not self.active:
            return
        for call in tool_calls or []:
            name = _tool_call_name(call).lower()
            if any(hint in name for hint in _SEARCH_TOOL_HINTS):
                function = call.get("function")
                raw_arguments = function.get("arguments") if isinstance(function, dict) else call.get("arguments")
                _unique_append(self.searched_patterns, str(raw_arguments or name))

    def record_tool_messages(self, messages: list[Any]) -> None:
        if not self.active:
            return
        for message in messages:
            if str(getattr(message, "role", "")).lower() != "role.tool":
                role_value = getattr(getattr(message, "role", None), "value", getattr(message, "role", ""))
                if str(role_value).lower() != "tool":
                    continue
            metadata = getattr(message, "metadata", {}) or {}
            tool_name = str(metadata.get("tool_name") or "").lower()
            data = metadata.get("data")
            if not isinstance(data, dict):
                data = _json_dict(str(getattr(message, "content", ""))) or {}
            self._record_tool_data(tool_name, data)
        self.refresh_coverage()

    def _record_tool_data(self, tool_name: str, data: dict[str, Any]) -> None:
        result_type = str(data.get("type") or "").lower()
        command = str(data.get("command") or "")
        if command:
            if any(hint in tool_name or re.search(rf"\b{re.escape(hint)}\b", command, re.I) for hint in _SEARCH_TOOL_HINTS):
                _unique_append(self.searched_patterns, command)
            if any(hint in tool_name or re.search(rf"\b{re.escape(hint)}\b", command, re.I) for hint in _READ_TOOL_HINTS):
                for path in _paths_from_shell_command(command):
                    _unique_append(self.read_files, path)
        path = _path_value(data.get("display_path") or data.get("path"))
        if path and (any(hint in tool_name for hint in _READ_TOOL_HINTS) or result_type == "file_read"):
            _unique_append(self.read_files, path)
        if any(hint in tool_name for hint in _SEARCH_TOOL_HINTS) or result_type in {"search_results", "glob_results", "tool_search"}:
            if path:
                _unique_append(self.searched_patterns, path)
            matches = data.get("matches")
            if isinstance(matches, list):
                for match in matches:
                    match_path = _path_value(match)
                    if match_path:
                        _unique_append(self.searched_patterns, match_path)
            results = data.get("results")
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict):
                        match_path = _path_value(item.get("path") or item.get("file"))
                        if match_path:
                            _unique_append(self.searched_patterns, match_path)

    def refresh_coverage(self) -> None:
        if not self.active:
            return
        files = [path.lower() for path in self.read_files]
        searched = [pattern.lower() for pattern in self.searched_patterns]
        coverage = dict.fromkeys(self.required_surfaces, False)
        for surface in coverage:
            if surface == "entrypoints":
                coverage[surface] = any(token in " ".join(searched + files) for token in ("route", "api", "main", "cli", "entry", "controller"))
            elif surface == "domain":
                coverage[surface] = any("domain" in path or "model" in path or "service" in path for path in files)
            elif surface == "adapters":
                coverage[surface] = any(token in path for path in files for token in ("adapter", "infrastructure", "repository", "client"))
            elif surface == "tests":
                coverage[surface] = any("test" in path or "spec" in path for path in files + searched)
            elif surface == "config":
                coverage[surface] = any(_looks_like_config(path) for path in files + searched)
            else:
                coverage[surface] = any(surface in path for path in files + searched)
        self.coverage_status = coverage
        self.ready_for_final = bool(coverage) and all(coverage.values())

    def reminder(self) -> str:
        missing = [name for name, covered in self.coverage_status.items() if not covered]
        missing_text = ", ".join(missing) if missing else "none"
        return (
            "Investigation path active. Progress through classify, discover, "
            "inspect, verify, then synthesize. Use tools before the final answer; "
            f"depth={self.depth}; current_phase={self.phase}; objective={self.objective!r}; "
            f"required_surfaces={self.required_surfaces}; missing_surfaces={missing_text}."
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "phase": self.phase,
            "depth": self.depth,
            "objective": self.objective,
            "required_surfaces": list(self.required_surfaces),
            "searched_patterns": list(self.searched_patterns),
            "read_files": list(self.read_files),
            "tool_iterations": self.tool_iterations,
            "coverage_status": dict(self.coverage_status),
            "ready_for_final": self.ready_for_final,
        }


def _depth_from_text(text: str) -> InvestigationDepth:
    lowered = text.lower()
    if "exhaustive" in lowered or "comprehensive" in lowered:
        return "exhaustive"
    if "deep" in lowered or "thorough" in lowered:
        return "deep"
    if "quick" in lowered or "light" in lowered or "brief" in lowered:
        return "light"
    return "standard"


def _required_surfaces_from_text(text: str) -> list[str]:
    lowered = text.lower()
    surfaces = list(_DEFAULT_REQUIRED_SURFACES)
    if not any(word in lowered for word in ("test", "bug", "debug", "failure", "fix", "improve", "review")):
        surfaces.remove("tests")
    if not any(word in lowered for word in ("config", "dependency", "architecture", "review", "improve")):
        surfaces.remove("config")
    return surfaces


def _looks_like_config(path: str) -> bool:
    name = PurePosixPath(path.lower()).name
    return name in {
        "pyproject.toml", "package.json", "requirements.txt", "setup.py",
        "dockerfile", "docker-compose.yml", "docker-compose.yaml", "go.mod",
        "cargo.toml", "makefile", "tsconfig.json", "vite.config.ts",
    } or "config" in path

@dataclass(slots=True)
class PromptPackage:
    """Materialized system+user prompt pair ready to hand to the LLM.

    ``user_context_message`` is optional because some turns inject
    context only into the system prompt; ``metadata`` carries the
    bookkeeping (token estimates, memory trace, etc.) that the use case
    later forwards to the assistant message.
    """

    system_prompt: str | None
    user_context_message: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class MemoryRecallResult:
    """Output of the memory-recall step.

    Empty by default so callers that disable RAG don't need to think
    about the trace dict at all.
    """

    prompt_memories: list[str] = field(default_factory=list)
    trace: dict[str, Any] | None = None


@dataclass(slots=True)
class PromptPreparation:
    """Resolved prompt-surface state for a single user turn.

    Captures everything that varies between turns *before* the LLM call:
    the original :class:`ChatRequestDTO`, any reminders injected by
    slash commands or context attachments, the cooperation-shared
    Browser target, etc.
    """

    request: ChatRequestDTO
    slash_reminder: str | None = None
    slash_metadata: dict[str, Any] | None = None
    context_reminders: list[str] = field(default_factory=list)
    context_attachment_metadata: list[dict[str, Any]] = field(default_factory=list)
    browser_target: dict[str, Any] | None = None


def _dedupe_append(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _path_category(path: str) -> str | None:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if (
        "/tests/" in f"/{normalized}/"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
    ):
        return "tests"
    if (
        "config" in normalized
        or name in {"pyproject.toml", "package.json", "tsconfig.json", "vite.config.ts"}
        or name.endswith((".toml", ".yaml", ".yml"))
    ):
        return "config"
    if (
        name in {"main.py", "__main__.py", "cli.py", "app.py", "server.py", "index.ts", "index.tsx"}
        or "/routes/" in f"/{normalized}/"
        or "/entrypoints/" in f"/{normalized}/"
    ):
        return "entrypoints"
    if "/domain/" in f"/{normalized}/":
        return "domain"
    if "/infrastructure/" in f"/{normalized}/" or "/adapters/" in f"/{normalized}/":
        return "infra"
    return None


def _tool_args(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        function = call.get("function")
        raw_arguments = function.get("arguments") if isinstance(function, dict) else call.get("arguments")
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}
    arguments = getattr(call, "arguments", None)
    return arguments if isinstance(arguments, dict) else {}


def _tool_name(call_or_result: Any) -> str:
    if isinstance(call_or_result, dict):
        return _tool_call_name(call_or_result)
    return str(getattr(call_or_result, "name", None) or getattr(call_or_result, "tool_name", "") or "")


@dataclass(slots=True)
class TurnCoverage:
    """Per-turn tool coverage telemetry surfaced on assistant metadata."""

    tool_names: list[str] = field(default_factory=list)
    search_patterns: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    files_edited: list[str] = field(default_factory=list)
    mcp_resources_read: list[str] = field(default_factory=list)
    memory_items_injected: int = 0
    coverage_category_hits: dict[str, int] = field(default_factory=dict)

    def record_prompt_metadata(self, metadata: dict[str, Any] | None) -> None:
        if not isinstance(metadata, dict):
            return
        injected = metadata.get("memory_items_injected")
        if isinstance(injected, int):
            self.memory_items_injected = max(self.memory_items_injected, injected)

    def record_tool_calls(self, tool_calls: list[Any] | None) -> None:
        for call in tool_calls or []:
            name = _tool_name(call)
            args = _tool_args(call)
            _dedupe_append(self.tool_names, name)
            self._record_from_name_and_args(name, args)

    def record_tool_result(self, result: Any) -> None:
        name = _tool_name(result)
        _dedupe_append(self.tool_names, name)
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return
        result_type = data.get("type")
        if result_type == "file_read":
            self._record_file_read(data.get("display_path") or data.get("path"))
        elif result_type in {"file_write", "file_edit"}:
            self._record_file_edited(data.get("display_path") or data.get("path"))
        elif result_type == "mcp_resource":
            self._record_mcp_resource(data.get("server"), data.get("uri"))
        for key in ("pattern", "query", "glob"):
            if key in data:
                _dedupe_append(self.search_patterns, data.get(key))
        matches = data.get("matches")
        if isinstance(matches, list):
            for path in matches:
                self._record_category_for_path(str(path))
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    self._record_category_for_path(str(item.get("path") or item.get("file") or ""))

    def _record_from_name_and_args(self, name: str, args: dict[str, Any]) -> None:
        if name in {"Grep", "Glob", "search_files", "WebSearch", "BrowserSearch", "ToolSearch"}:
            for key in ("pattern", "query", "glob"):
                _dedupe_append(self.search_patterns, args.get(key))
        if name in {"Read", "read_file"}:
            self._record_file_read(args.get("path"))
        if name in {"Write", "Edit"}:
            self._record_file_edited(args.get("path"))
        if name == "ReadMcpResourceTool":
            self._record_mcp_resource(args.get("server"), args.get("uri"))
        if name == "Config":
            self._hit_category("config")
        path = args.get("path")
        if isinstance(path, str):
            self._record_category_for_path(path)

    def _record_file_read(self, path: Any) -> None:
        _dedupe_append(self.files_read, path)
        self._record_category_for_path(str(path or ""))

    def _record_file_edited(self, path: Any) -> None:
        _dedupe_append(self.files_edited, path)
        self._record_category_for_path(str(path or ""))

    def _record_mcp_resource(self, server: Any, uri: Any) -> None:
        if server or uri:
            _dedupe_append(self.mcp_resources_read, f"{server or ''}:{uri or ''}")
        self._hit_category("infra")

    def _record_category_for_path(self, path: str) -> None:
        category = _path_category(path)
        if category:
            self._hit_category(category)

    def _hit_category(self, category: str) -> None:
        self.coverage_category_hits[category] = self.coverage_category_hits.get(category, 0) + 1

    def to_metadata(self) -> dict[str, Any]:
        return {
            "tool_names": list(self.tool_names),
            "search_patterns": list(self.search_patterns),
            "files_read": list(self.files_read),
            "files_edited": list(self.files_edited),
            "mcp_resources_read": list(self.mcp_resources_read),
            "memory_items_injected": self.memory_items_injected,
            "coverage_category_hits": dict(sorted(self.coverage_category_hits.items())),
        }


@dataclass(slots=True)
class AssistantStreamState:
    """Accumulator for the assistant pass of a single streaming turn.

    The chat loop appends chunks here as they arrive from the provider
    so that, once the stream completes, the final assistant message can
    be assembled from a single mutable object. Tool calls, images,
    usage stats, and provider/model identifiers all live here too so
    that the post-stream cleanup path has one place to look.
    """

    content_chunks: list[str] = field(default_factory=list)
    reasoning_chunks: list[str] = field(default_factory=list)
    images: list[GeneratedImage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    model: str = ""
    provider: str = ""

    @property
    def content(self) -> str:
        return "".join(self.content_chunks)

    @property
    def reasoning_content(self) -> str:
        return "".join(self.reasoning_chunks)

    @property
    def has_visible_output(self) -> bool:
        return bool(self.content or self.images)


@dataclass(slots=True)
class StreamingTurnState:
    """Cross-iteration state for the streaming completion turn loop.

    Bundles the standalone tracking variables that previously lived as
    local bindings inside ``_stream_completion_turn`` so that the
    streaming-loop extraction can pass a single typed argument around
    instead of a long parameter list. Each field maps 1:1 to a former
    local:

    * ``final_finish_reason`` / ``final_usage`` / ``final_model`` /
      ``final_provider`` -- the values written into the final
      ``conversation_saved`` :class:`StreamChunk`. They start from
      ``None`` (with ``final_model`` / ``final_provider`` seeded from
      the request) and may be overwritten by each iteration's
      assistant pass or by an error branch.
    * ``seen_tool_call_ids`` -- IDs the assistant has already emitted;
      passed by reference into the per-iteration assistant pass to
      keep duplicate detection consistent across iterations.
    * ``iteration`` / ``executed_tools`` -- loop control + a flag the
      retry-on-empty-tool-response branch reads to decide whether to
      replay the assistant pass with the final-answer reminder.
    * ``last_prompt_context_metadata`` -- the most recent context
      metadata dict, surfaced into the ``conversation_saved`` payload.
    * ``evidence_gate_continuations`` -- how many extra model passes the
      evidence gate has requested for the current turn.

    The dataclass is mutable (``slots=True`` but no ``frozen=True``)
    because the streaming loop mutates these fields in place.
    """

    final_finish_reason: str | None = None
    final_usage: dict[str, int] | None = None
    final_model: str | None = None
    final_provider: str | None = None
    seen_tool_call_ids: set[str] = field(default_factory=set)
    iteration: int = 0
    executed_tools: bool = False
    last_prompt_context_metadata: dict[str, Any] = field(default_factory=dict)
    evidence_gate_continuations: int = 0
    coverage: TurnCoverage = field(default_factory=TurnCoverage)


__all__ = [
    "AssistantStreamState",
    "InvestigationState",
    "MemoryRecallResult",
    "PromptPackage",
    "PromptPreparation",
    "StreamingTurnState",
    "TurnCoverage",
]
