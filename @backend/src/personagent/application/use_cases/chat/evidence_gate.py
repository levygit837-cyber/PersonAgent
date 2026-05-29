"""Evidence sufficiency gate for codebase-analysis chat turns.

The gate is deliberately heuristic and side-effect free.  It inspects the
current turn's request/profile metadata plus repository-facing tool evidence in
conversation messages, then decides whether the model should be forced into one
more tool-using pass instead of finalizing with an under-supported answer.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.tooling.tool_runtime import (
    max_evidence_gate_continuations,
    minimum_evidence_expectations,
)
from personagent.domain.conversation.models import Conversation, Role

EVIDENCE_GATE_REMINDER = (
    "You are answering a codebase-analysis task but have not inspected enough "
    "repository evidence. Continue using available read/search tools. Do not "
    "produce the final answer until the evidence checklist is satisfied."
)

_MAX_EVIDENCE_GATE_CONTINUATIONS = 2

_CODEBASE_TERMS = frozenset(
    {
        "codebase",
        "repo",
        "repository",
        "file",
        "files",
        "module",
        "class",
        "function",
        "method",
        "service",
        "test",
        "tests",
        "bug",
        "fix",
        "implement",
        "implementation",
        "refactor",
        "endpoint",
        "api",
        "component",
        "manifest",
        "dependency",
        "package",
        "config",
        "pytest",
        "jest",
    }
)
_TEST_RELEVANCE_TERMS = frozenset(
    {
        "test",
        "tests",
        "testing",
        "pytest",
        "jest",
        "vitest",
        "spec",
        "bug",
        "fix",
        "failing",
        "failure",
        "regression",
        "behavior",
        "validate",
        "verify",
    }
)
_MANIFEST_RELEVANCE_TERMS = frozenset(
    {
        "dependency",
        "dependencies",
        "package",
        "install",
        "build",
        "config",
        "configuration",
        "manifest",
        "tooling",
        "script",
        "version",
    }
)

_READ_TOOL_NAMES = frozenset({"read", "read_file", "view", "open"})
_SEARCH_TOOL_NAMES = frozenset(
    {"grep", "glob", "search_files", "rg", "find", "toolsearch"}
)
_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
    }
)
_MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml",
        "poetry.lock",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "makefile",
    }
)
_TEST_COMMAND_RE = re.compile(
    r"\b(pytest|python\s+-m\s+pytest|npm\s+(?:run\s+)?test|pnpm\s+test|yarn\s+test|"
    r"vitest|jest|cargo\s+test|go\s+test|mvn\s+test|gradle\s+test)\b",
    re.IGNORECASE,
)
_READ_COMMAND_RE = re.compile(
    r"\b(cat|sed|head|tail|bat|python\s+- <<|python\s+-c)\b", re.I
)
_SEARCH_COMMAND_RE = re.compile(r"\b(rg|grep|find|fd)\b", re.I)


@dataclass(frozen=True, slots=True)
class EvidenceGateDecision:
    """Decision returned by :class:`EvidenceGateService`."""

    should_continue: bool
    reason: str
    reminder: str | None = None
    missing: tuple[str, ...] = ()
    checklist: dict[str, bool] = field(default_factory=dict)
    retry_count: int = 0
    ready_for_final: bool = False


@dataclass(slots=True)
class _TurnEvidence:
    tool_names: set[str] = field(default_factory=set)
    read_files: set[str] = field(default_factory=set)
    searched_files: set[str] = field(default_factory=set)
    searched_paths: set[str] = field(default_factory=set)
    shell_commands: list[str] = field(default_factory=list)


class EvidenceGateService:
    """Require repository evidence before finalizing codebase-analysis answers."""

    def __init__(self, *, max_continuations: int = _MAX_EVIDENCE_GATE_CONTINUATIONS) -> None:
        self._max_continuations = max(0, int(max_continuations))

    @property
    def max_continuations(self) -> int:
        return self._max_continuations

    def should_continue_investigation(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        turn_state: Any,
        context_metadata: dict[str, Any] | None,
    ) -> EvidenceGateDecision:
        """Return whether the model should do another evidence-gathering pass."""

        retry_count = _retry_count(turn_state)
        metadata = context_metadata or {}
        required_evidence = minimum_evidence_expectations(request)
        if not required_evidence:
            return EvidenceGateDecision(
                should_continue=False,
                reason="investigation depth has no minimum evidence expectations",
                checklist={},
                retry_count=retry_count,
            )

        depth_continuation_cap = max_evidence_gate_continuations(request)
        continuation_cap = (
            depth_continuation_cap
            if request.investigation_depth != "auto"
            else min(self._max_continuations, depth_continuation_cap)
        )
        if retry_count >= continuation_cap:
            return EvidenceGateDecision(
                should_continue=False,
                reason="evidence gate retry cap reached",
                retry_count=retry_count,
            )

        if not _is_codebase_analysis_request(request, metadata, conversation):
            return EvidenceGateDecision(
                should_continue=False,
                reason="request does not require repository evidence gating",
                retry_count=retry_count,
            )

        evidence = _collect_current_turn_evidence(conversation)
        needs_tests = _needs_tests(request, metadata)
        needs_manifests = _needs_manifests(request, metadata)
        has_test_evidence = _has_test_evidence(
            evidence.read_files | evidence.searched_files, evidence.shell_commands
        )
        has_manifest_evidence = _has_manifest_evidence(
            evidence.read_files | evidence.searched_files, evidence.shell_commands
        )
        has_search_evidence = bool(evidence.searched_files or evidence.searched_paths) or any(
            _SEARCH_COMMAND_RE.search(command) for command in evidence.shell_commands
        )
        checklist = {
            "has_tool_calls": bool(evidence.tool_names),
            "has_search_evidence": has_search_evidence,
            "has_file_read_evidence": bool(evidence.read_files)
            or any(_READ_COMMAND_RE.search(command) for command in evidence.shell_commands),
            "has_core_implementation_read": _has_core_implementation_file(evidence.read_files),
            "has_test_evidence": has_test_evidence,
            "has_manifest_evidence": has_manifest_evidence,
            "has_relevant_test_evidence": (not needs_tests) or has_test_evidence,
            "has_relevant_manifest_evidence": (not needs_manifests) or has_manifest_evidence,
            "has_test_or_manifest_evidence": has_test_evidence or has_manifest_evidence,
            "has_caller_or_symbol_search": _has_caller_or_symbol_search(evidence),
            "has_adjacent_module_evidence": _has_adjacent_module_evidence(evidence),
            "has_broad_symbol_search": _has_broad_symbol_search(evidence),
            "has_cross_surface_coverage": _has_cross_surface_coverage(evidence),
        }
        missing = tuple(name for name in required_evidence if not checklist.get(name, False))
        if not missing:
            return EvidenceGateDecision(
                should_continue=False,
                reason="evidence checklist satisfied",
                checklist=checklist,
                retry_count=retry_count,
                ready_for_final=True,
            )
        return EvidenceGateDecision(
            should_continue=True,
            reason=(
                "repository evidence is insufficient for "
                f"{request.investigation_depth} investigation depth"
            ),
            reminder=EVIDENCE_GATE_REMINDER,
            missing=missing,
            checklist=checklist,
            retry_count=retry_count,
        )


def _retry_count(turn_state: Any) -> int:
    if isinstance(turn_state, dict):
        value = turn_state.get("evidence_gate_continuations", 0)
    else:
        value = getattr(turn_state, "evidence_gate_continuations", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _is_codebase_analysis_request(
    request: ChatRequestDTO,
    metadata: dict[str, Any],
    conversation: Conversation,
) -> bool:
    prompt_profile = metadata.get("prompt_profile")
    primary_mode = ""
    secondary_modes: list[str] = []
    if isinstance(prompt_profile, dict):
        primary_mode = str(prompt_profile.get("primary_mode") or "").lower()
        raw_secondary = prompt_profile.get("secondary_modes")
        if isinstance(raw_secondary, list):
            secondary_modes = [str(item).lower() for item in raw_secondary]
    agent_states = [str(item).lower() for item in metadata.get("agent_states") or []]
    profile_suggests_code = bool(
        {primary_mode, *secondary_modes}.intersection({"exploring", "research", "writing"})
        or {"context_discovery", "implementation", "runtime_validation"}.intersection(agent_states)
    )
    text = " ".join(
        str(part or "")
        for part in (
            request.message,
            request.system_prompt,
            request.metadata.get("intent") if isinstance(request.metadata, dict) else None,
            conversation.metadata.get("active_task") if isinstance(conversation.metadata, dict) else None,
        )
    ).lower()
    return profile_suggests_code and _contains_any(text, _CODEBASE_TERMS)


def _needs_tests(request: ChatRequestDTO, metadata: dict[str, Any]) -> bool:
    text = _request_and_profile_text(request, metadata)
    return _contains_any(text, _TEST_RELEVANCE_TERMS)


def _needs_manifests(request: ChatRequestDTO, metadata: dict[str, Any]) -> bool:
    text = _request_and_profile_text(request, metadata)
    return _contains_any(text, _MANIFEST_RELEVANCE_TERMS)


def _request_and_profile_text(request: ChatRequestDTO, metadata: dict[str, Any]) -> str:
    profile = metadata.get("prompt_profile") if isinstance(metadata, dict) else None
    pieces: list[str] = [request.message, request.system_prompt or ""]
    if isinstance(profile, dict):
        pieces.extend(str(value) for value in profile.values() if isinstance(value, str))
        pieces.extend(str(value) for value in profile.get("surface_hints") or [])
    return " ".join(pieces).lower()


def _collect_current_turn_evidence(conversation: Conversation) -> _TurnEvidence:
    last_user_index = -1
    for index in range(len(conversation.messages) - 1, -1, -1):
        if conversation.messages[index].role == Role.USER:
            last_user_index = index
            break
    evidence = _TurnEvidence()
    for message in conversation.messages[last_user_index + 1 :]:
        if message.role == Role.ASSISTANT:
            for call in message.tool_calls or []:
                name = _tool_call_name(call)
                if name:
                    evidence.tool_names.add(name.lower())
        if message.role != Role.TOOL:
            continue
        tool_name = str(message.metadata.get("tool_name") or "").lower()
        if tool_name:
            evidence.tool_names.add(tool_name)
        data = message.metadata.get("data")
        if not isinstance(data, dict):
            data = _json_dict(message.content)
        _collect_from_tool_data(data or {}, tool_name, evidence)
    return evidence


def _collect_from_tool_data(data: dict[str, Any], tool_name: str, evidence: _TurnEvidence) -> None:
    result_type = str(data.get("type") or "").lower()
    if tool_name == "shell" or result_type == "shell_command":
        command = str(data.get("command") or "")
        if command:
            evidence.shell_commands.append(command)
            for path in _paths_from_shell_command(command):
                if _READ_COMMAND_RE.search(command):
                    evidence.read_files.add(path)
                if _SEARCH_COMMAND_RE.search(command):
                    evidence.searched_paths.add(path)
        return

    path = _normal_path(data.get("display_path") or data.get("path"))
    if tool_name in _READ_TOOL_NAMES or result_type == "file_read":
        if path:
            evidence.read_files.add(path)
        return
    if tool_name in _SEARCH_TOOL_NAMES or result_type in {"search_results", "glob_results", "tool_search"}:
        if path:
            evidence.searched_paths.add(path)
        matches = data.get("matches")
        if isinstance(matches, list):
            for match in matches:
                normalized = _normal_path(match)
                if normalized:
                    evidence.searched_files.add(normalized)
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    normalized = _normal_path(item.get("path") or item.get("file"))
                    if normalized:
                        evidence.searched_files.add(normalized)
        content = str(data.get("content") or "")
        for line in content.splitlines():
            candidate = line.split(":", 1)[0].strip()
            normalized = _normal_path(candidate)
            if normalized:
                evidence.searched_files.add(normalized)


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


def _normal_path(value: Any) -> str:
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
        if (
            not token
            or token.startswith("-")
            or token in {"cat", "sed", "head", "tail", "rg", "grep", "find", "fd"}
        ):
            continue
        if "/" in token or PurePosixPath(token).suffix or token in _MANIFEST_NAMES:
            paths.add(token)
    return paths


def _has_core_implementation_file(paths: set[str]) -> bool:
    return any(_is_core_implementation_path(path) for path in paths)


def _is_core_implementation_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        PurePosixPath(lowered).suffix in _SOURCE_SUFFIXES
        and not _is_test_path(lowered)
        and name not in _MANIFEST_NAMES
    )


def _has_test_evidence(paths: set[str], commands: list[str]) -> bool:
    return any(_is_test_path(path) for path in paths) or any(
        _TEST_COMMAND_RE.search(command) for command in commands
    )


def _has_manifest_evidence(paths: set[str], commands: list[str]) -> bool:
    return any(_is_manifest_path(path) for path in paths) or any(
        _is_manifest_path(path)
        for command in commands
        for path in _paths_from_shell_command(command)
    )


def _has_caller_or_symbol_search(evidence: _TurnEvidence) -> bool:
    return any(
        _SEARCH_COMMAND_RE.search(command) and _looks_like_symbol_search(command)
        for command in evidence.shell_commands
    ) or len(evidence.searched_files | evidence.searched_paths) >= 2


def _has_adjacent_module_evidence(evidence: _TurnEvidence) -> bool:
    source_files = {
        path
        for path in evidence.read_files | evidence.searched_files
        if _is_core_implementation_path(path)
    }
    if len(source_files) >= 2:
        return True
    parents = {str(PurePosixPath(path).parent) for path in source_files if path}
    searched_parents = {
        str(PurePosixPath(path).parent)
        for path in evidence.searched_files | evidence.searched_paths
        if _is_core_implementation_path(path)
    }
    return bool(parents.intersection(searched_parents))


def _has_broad_symbol_search(evidence: _TurnEvidence) -> bool:
    searched_paths = evidence.searched_files | evidence.searched_paths
    symbol_searches = sum(
        1
        for command in evidence.shell_commands
        if _SEARCH_COMMAND_RE.search(command) and _looks_like_symbol_search(command)
    )
    return symbol_searches >= 2 or len(searched_paths) >= 4


def _has_cross_surface_coverage(evidence: _TurnEvidence) -> bool:
    paths = evidence.read_files | evidence.searched_files
    surfaces = {
        "implementation" for path in paths if _is_core_implementation_path(path)
    }
    if any(_is_test_path(path) for path in paths) or any(
        _TEST_COMMAND_RE.search(command) for command in evidence.shell_commands
    ):
        surfaces.add("tests")
    if any(_is_manifest_path(path) for path in paths) or any(
        _is_manifest_path(path)
        for command in evidence.shell_commands
        for path in _paths_from_shell_command(command)
    ):
        surfaces.add("config")
    if _has_caller_or_symbol_search(evidence):
        surfaces.add("callers")
    if _has_adjacent_module_evidence(evidence):
        surfaces.add("adjacent_modules")
    return len(surfaces) >= 4


def _looks_like_symbol_search(command: str) -> bool:
    lowered = command.lower()
    return bool(
        re.search(r"\b(rg|grep|fd|find)\b", lowered)
        and (
            "-n" in lowered
            or "--line-number" in lowered
            or "class " in lowered
            or "def " in lowered
            or "function " in lowered
            or "import " in lowered
            or "from " in lowered
        )
    )


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    parts = set(PurePosixPath(lowered).parts)
    name = PurePosixPath(lowered).name
    return bool(
        parts.intersection({"tests", "test", "__tests__", "spec", "specs"})
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
        or name.endswith("_test.go")
        or name.endswith(".test.js")
        or name.endswith(".spec.js")
    )


def _is_manifest_path(path: str) -> bool:
    return PurePosixPath(path.lower()).name in _MANIFEST_NAMES


def _contains_any(text: str, terms: frozenset[str]) -> bool:
    words = set(re.findall(r"[a-zA-Z0-9_+-]+", text.lower()))
    return bool(words.intersection(terms))


__all__ = ["EVIDENCE_GATE_REMINDER", "EvidenceGateDecision", "EvidenceGateService"]
