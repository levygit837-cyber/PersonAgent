"""Session panel aggregation for the desktop chat UI."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from personagent.domain.models.conversation import Conversation, Message, Role

_TEXT_TOKEN_DIVISOR = 4


@dataclass(frozen=True, slots=True)
class SessionPanelService:
    """Builds the panel snapshot from conversation metadata, Git and GitHub."""

    workspace_root: str | Path | None = None

    async def panel_snapshot(self, conversation: Conversation) -> dict[str, Any]:
        workspace = self._workspace()
        # Compute conversation-derived data concurrently with project snapshot.
        changed_files_task = asyncio.create_task(self._changed_files_async(conversation, workspace))
        sources_task = asyncio.create_task(self._sources_async(conversation))
        usage_task = asyncio.create_task(self._usage_async(conversation))
        memory_task = asyncio.create_task(self._memory_summary_async(conversation))
        project_task = asyncio.create_task(self._project_snapshot_async(workspace))

        changed_files, sources, usage, memory, project = await asyncio.gather(
            changed_files_task,
            sources_task,
            usage_task,
            memory_task,
            project_task,
        )

        return {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "updated_at": conversation.updated_at.isoformat(),
            "changed_files": changed_files,
            "sources": sources,
            "usage": usage,
            "memory": memory,
            "project": project,
        }

    def project_detail(self, detail_type: str, detail_id: str) -> dict[str, Any]:
        workspace = self._workspace()
        normalized = detail_type.strip().lower()
        if normalized == "commit":
            return _ps.commit_detail(workspace, detail_id)
        if normalized == "push":
            return _ps.push_detail(workspace, detail_id)
        if normalized == "pr":
            return _ps.pr_detail(workspace, detail_id)
        if normalized == "branch":
            return _ps.branch_detail(workspace, detail_id)
        return {
            "type": normalized,
            "id": detail_id,
            "title": "Unsupported detail",
            "error": f"Unsupported project detail type: {detail_type}",
        }

    def _workspace(self) -> Path:
        raw = self.workspace_root or Path.cwd()
        path = Path(raw).expanduser().resolve()
        return path if path.exists() else Path.cwd().resolve()

    async def _usage_async(self, conversation: Conversation) -> dict[str, Any]:
        return self._usage(conversation)

    async def _memory_summary_async(self, conversation: Conversation) -> dict[str, Any]:
        return self._memory_summary(conversation)

    async def _sources_async(self, conversation: Conversation) -> list[dict[str, Any]]:
        return self._sources(conversation)

    async def _changed_files_async(self, conversation: Conversation, workspace: Path) -> list[dict[str, Any]]:
        return self._changed_files(conversation, workspace)

    async def _project_snapshot_async(self, workspace: Path) -> dict[str, Any]:
        return await _ps.project_snapshot_async(workspace)

    def _usage(self, conversation: Conversation) -> dict[str, Any]:
        usage = {
            "context_tokens": _metric(),
            "agent_output_tokens": _metric(),
            "thinking_output_tokens": _metric(),
            "tool_calls": _metric(),
            "skills_used_count": _metric(),
            "mcp_calls_count": _metric(),
            "plans_created": _metric(),
            "todos_created": _metric(),
            "subagents_used": _metric(),
        }
        seen_tools: set[str] = set()
        seen_plans: set[str] = set()
        seen_subagents: set[str] = set()

        for message in conversation.messages:
            metadata = message.metadata or {}
            if message.role == Role.ASSISTANT:
                self._add_token_usage(usage, message)
                tool_calls = message.tool_calls or []
                for call in tool_calls:
                    call_id = str(call.get("id") or "")
                    function = call.get("function") if isinstance(call, dict) else None
                    tool_name = str(function.get("name") if isinstance(function, dict) else "")
                    if call_id and call_id not in seen_tools:
                        seen_tools.add(call_id)
                        _add(usage["tool_calls"], 1)
                    if tool_name == "Skill":
                        _add(usage["skills_used_count"], 1)
                    if tool_name.startswith("mcp__"):
                        _add(usage["mcp_calls_count"], 1)
                if metadata.get("team_mode") is True:
                    agent_id = str(metadata.get("run_id") or message.timestamp.isoformat())
                    seen_subagents.add(agent_id)
            elif message.role == Role.TOOL:
                tool_id = str(message.tool_call_id or "")
                tool_name = str(metadata.get("tool_name") or "")
                if tool_id and tool_id not in seen_tools:
                    seen_tools.add(tool_id)
                    _add(usage["tool_calls"], 1)
                if tool_name == "Skill":
                    _add(usage["skills_used_count"], 1)
                if tool_name.startswith("mcp__") or metadata.get("is_mcp") is True:
                    _add(usage["mcp_calls_count"], 1)
                data = _tool_data(message)
                if data.get("type") == "plan_mode":
                    plan_id = str(data.get("plan_id") or "")
                    if plan_id and plan_id not in seen_plans:
                        seen_plans.add(plan_id)
                        _add(usage["plans_created"], 1)
                if data.get("type") == "todos" or tool_name == "TodoWrite":
                    todos = data.get("todos")
                    _add(usage["todos_created"], len(todos) if isinstance(todos, list) else 1)

        plan_state = conversation.metadata.get("plan_mode") if isinstance(conversation.metadata, dict) else None
        if isinstance(plan_state, dict) and plan_state.get("plan_id"):
            plan_id = str(plan_state["plan_id"])
            if plan_id not in seen_plans:
                _add(usage["plans_created"], 1)

        usage["subagents_used"]["value"] = len(seen_subagents)
        return usage

    def _memory_summary(self, conversation: Conversation) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total_recalls": 0,
            "rag_used": 0,
            "classic_used": 0,
            "omitted": 0,
            "avg_latency_ms": 0,
            "budget_used": 0,
            "budget_tokens": 0,
            "most_used": [],
        }
        latency_values: list[int] = []
        by_key: dict[str, dict[str, Any]] = {}

        for message in conversation.messages:
            if message.role != Role.ASSISTANT:
                continue
            trace = _memory_trace(message)
            if not trace:
                continue
            trace_summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
            total_used = _safe_int(trace_summary.get("total_used"))
            if total_used <= 0:
                continue
            summary["total_recalls"] += 1
            summary["rag_used"] += _safe_int(trace_summary.get("rag_count"))
            summary["classic_used"] += _safe_int(trace_summary.get("classic_count"))
            summary["omitted"] += _safe_int(trace_summary.get("omitted_count"))
            summary["budget_used"] += _safe_int(trace_summary.get("budget_used"))
            summary["budget_tokens"] += _safe_int(trace_summary.get("budget_tokens"))
            latency = _safe_int(trace_summary.get("latency_ms"))
            if latency > 0:
                latency_values.append(latency)

            message_id = message.timestamp.isoformat()
            for item in _memory_trace_items(trace, "classic"):
                key = str(item.get("path") or item.get("name") or item.get("snippet") or "classic")
                entry = by_key.setdefault(
                    f"classic:{key}",
                    {
                        "id": f"classic:{key}",
                        "source": "classic",
                        "label": _compact_memory_label(key),
                        "count": 0,
                        "paths": [],
                        "evidence": [],
                        "messages": [],
                    },
                )
                _memory_entry_add(entry, item.get("path"), item.get("snippet"), message_id)

            for item in _memory_trace_items(trace, "operational"):
                source_ids = item.get("source_ids") if isinstance(item.get("source_ids"), list) else []
                paths = item.get("paths") if isinstance(item.get("paths"), list) else []
                key = str((source_ids or paths or [item.get("summary") or "rag"])[0])
                label = str((paths or [item.get("summary") or key])[0])
                entry = by_key.setdefault(
                    f"rag:{key}",
                    {
                        "id": f"rag:{key}",
                        "source": "rag",
                        "label": _compact_memory_label(label),
                        "count": 0,
                        "paths": [],
                        "evidence": [],
                        "messages": [],
                    },
                )
                evidence = item.get("evidence")
                _memory_entry_add(
                    entry,
                    paths[0] if paths else None,
                    evidence[0] if isinstance(evidence, list) and evidence else item.get("summary"),
                    message_id,
                )

        if latency_values:
            summary["avg_latency_ms"] = int(sum(latency_values) / len(latency_values))
        summary["most_used"] = sorted(
            by_key.values(),
            key=lambda item: (-_safe_int(item.get("count")), str(item.get("label") or "")),
        )[:8]
        return summary

    def _add_token_usage(self, usage: dict[str, Any], message: Message) -> None:
        metadata = message.metadata or {}
        raw_usage = metadata.get("usage")
        exact_agent = None
        exact_thinking = None
        if isinstance(raw_usage, dict):
            exact_thinking = _first_int(
                raw_usage,
                (
                    "reasoning_tokens",
                    "thinking_tokens",
                    "thoughtsTokenCount",
                    "thoughts_token_count",
                ),
            )
            details = raw_usage.get("completion_tokens_details")
            if exact_thinking is None and isinstance(details, dict):
                exact_thinking = _first_int(details, ("reasoning_tokens",))
            candidate_tokens = _first_int(
                raw_usage,
                (
                    "candidatesTokenCount",
                    "candidates_token_count",
                    "output_tokens",
                    "completion_tokens",
                ),
            )
            exact_agent = candidate_tokens
            if (
                exact_agent is not None
                and exact_thinking is not None
                and "completion_tokens" in raw_usage
                and "candidatesTokenCount" not in raw_usage
            ):
                exact_agent = max(0, exact_agent - exact_thinking)

        if exact_agent is None:
            _add(usage["agent_output_tokens"], _estimate_tokens(message.content), estimated=True)
        else:
            _add(usage["agent_output_tokens"], exact_agent)
        reasoning = str(metadata.get("reasoning_content") or "")
        if exact_thinking is None:
            _add(usage["thinking_output_tokens"], _estimate_tokens(reasoning), estimated=True)
        else:
            _add(usage["thinking_output_tokens"], exact_thinking)

        context_tokens = _first_int(
            metadata,
            (
                "context_tokens_after_turn_estimated",
                "context_tokens_estimated",
                "prompt_tokens_estimated",
            ),
        )
        context_tokens_source = None
        if context_tokens is None and isinstance(raw_usage, dict):
            context_tokens, context_tokens_source = _first_int_with_key(
                raw_usage,
                (
                    "prompt_tokens",
                    "input_tokens",
                    "promptTokenCount",
                ),
            )
        if context_tokens is not None:
            usage["context_tokens"]["value"] = max(
                int(usage["context_tokens"].get("value") or 0),
                context_tokens,
            )
            usage["context_tokens"]["estimated"] = context_tokens_source not in (
                "prompt_tokens",
                "input_tokens",
                "promptTokenCount",
            )

    def _changed_files(self, conversation: Conversation, workspace: Path) -> list[dict[str, Any]]:
        files: dict[str, dict[str, Any]] = {}
        for message in conversation.messages:
            if message.role != Role.TOOL:
                continue
            metadata = message.metadata or {}
            tool_name = str(metadata.get("tool_name") or "")
            if tool_name not in {"Write", "Edit"}:
                continue
            data = _tool_data(message)
            path = str(data.get("display_path") or data.get("path") or "").strip()
            if not path:
                continue
            added, removed = _diff_stats(data)
            files[path] = {
                "id": f"tool:{message.tool_call_id or path}",
                "path": str(data.get("path") or path),
                "display_path": path,
                "added_lines": added,
                "removed_lines": removed,
                "source": tool_name,
                "status": "changed",
                "diff": str(data.get("diff") or ""),
                "content": str(data.get("written_content") or data.get("new_content") or ""),
            }

        for item in self._git_changed_files(workspace):
            files.setdefault(item["display_path"], item)

        return sorted(files.values(), key=lambda item: item["display_path"])

    def _git_changed_files(self, workspace: Path) -> list[dict[str, Any]]:
        if not _is_git_repo(workspace):
            return []
        rows = []
        for mode, args in (
            ("unstaged", ["diff", "--numstat"]),
            ("staged", ["diff", "--cached", "--numstat"]),
        ):
            result = _run(["git", *args], workspace)
            if not result.ok:
                continue
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                added = _safe_int(parts[0])
                removed = _safe_int(parts[1])
                path = parts[2]
                rows.append(
                    {
                        "id": f"git:{mode}:{path}",
                        "path": str((workspace / path).resolve()),
                        "display_path": path,
                        "added_lines": added,
                        "removed_lines": removed,
                        "source": f"git:{mode}",
                        "status": mode,
                        "diff": "",
                        "content": "",
                    }
                )
        result = _run(["git", "ls-files", "--others", "--exclude-standard"], workspace)
        if result.ok:
            for path in result.stdout.splitlines()[:50]:
                rows.append(
                    {
                        "id": f"git:untracked:{path}",
                        "path": str((workspace / path).resolve()),
                        "display_path": path,
                        "added_lines": _file_line_count(workspace / path),
                        "removed_lines": 0,
                        "source": "git:untracked",
                        "status": "untracked",
                        "diff": "",
                        "content": "",
                    }
                )
        return rows

    def _sources(self, conversation: Conversation) -> list[dict[str, Any]]:
        by_url: dict[str, dict[str, Any]] = {}
        for message in conversation.messages:
            if message.role != Role.TOOL:
                continue
            metadata = message.metadata or {}
            tool_name = str(metadata.get("tool_name") or "")
            if tool_name not in {
                "WebFetch",
                "BrowserSearch",
                "BrowserOpen",
                "BrowserListTabs",
                "BrowserExtractContent",
                "BrowserGetHtml",
            }:
                continue
            data = _tool_data(message)
            for source in _sources_from_tool_data(tool_name, data):
                by_url.setdefault(source["url"], source)
        return list(by_url.values())


@dataclass(frozen=True, slots=True)
class _RunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _run(command: list[str], cwd: Path, timeout: int = 5) -> _RunResult:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _RunResult(result.returncode, result.stdout, result.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return _RunResult(1, "", str(exc))


async def _run_async(command: list[str], cwd: Path, timeout: int = 5) -> _RunResult:
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return _RunResult(
            proc.returncode or 0,
            stdout_data.decode("utf-8", errors="replace"),
            stderr_data.decode("utf-8", errors="replace"),
        )
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return _RunResult(1, "", f"timed out after {timeout}s")
    except (FileNotFoundError, OSError) as exc:
        return _RunResult(1, "", str(exc))


def _is_git_repo(workspace: Path) -> bool:
    return _run(["git", "rev-parse", "--git-dir"], workspace).ok


def _metric(value: int = 0, estimated: bool = False) -> dict[str, Any]:
    return {"value": value, "estimated": estimated}


def _add(metric: dict[str, Any], value: int, estimated: bool = False) -> None:
    metric["value"] = int(metric.get("value") or 0) + max(0, int(value or 0))
    metric["estimated"] = bool(metric.get("estimated") or estimated)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _TEXT_TOKEN_DIVISOR - 1) // _TEXT_TOKEN_DIVISOR)


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = data.get(key)
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _first_int_with_key(
    data: dict[str, Any], keys: tuple[str, ...]
) -> tuple[int | None, str | None]:
    for key in keys:
        value = data.get(key)
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed, key
    return None, None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "-":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        if value == "-":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tool_data(message: Message) -> dict[str, Any]:
    metadata = message.metadata or {}
    data = metadata.get("data")
    if isinstance(data, dict):
        return data
    if isinstance(message.content, str):
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _memory_trace(message: Message) -> dict[str, Any]:
    metadata = message.metadata or {}
    trace = metadata.get("memory_trace")
    return trace if isinstance(trace, dict) else {}


def _memory_trace_items(trace: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = trace.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _memory_entry_add(
    entry: dict[str, Any],
    path: Any,
    evidence: Any,
    message_id: str,
) -> None:
    entry["count"] = _safe_int(entry.get("count")) + 1
    if isinstance(path, str) and path and path not in entry["paths"]:
        entry["paths"].append(path)
    if isinstance(evidence, str) and evidence.strip() and evidence not in entry["evidence"]:
        entry["evidence"].append(evidence[:280])
    if message_id not in entry["messages"]:
        entry["messages"].append(message_id)


def _compact_memory_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "memory"
    if "/" not in text:
        return text[:120]
    parts = [part for part in text.split("/") if part]
    return "/".join(parts[-2:])[:120] if parts else text[:120]


def _diff_stats(data: dict[str, Any]) -> tuple[int, int]:
    added = _safe_int(data.get("added_lines"))
    removed = _safe_int(data.get("removed_lines"))
    if added or removed:
        return added, removed
    diff = str(data.get("diff") or "")
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        if line.startswith("-"):
            removed += 1
    return added, removed


def _sources_from_tool_data(tool_name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if tool_name == "BrowserSearch":
        results = data.get("results")
        if isinstance(results, list):
            for index, result in enumerate(results, start=1):
                if isinstance(result, dict):
                    sources.extend(_source_from_record(tool_name, result, index))
        return sources
    if tool_name == "BrowserListTabs":
        tabs = data.get("tabs")
        if isinstance(tabs, list):
            for index, tab in enumerate(tabs, start=1):
                if isinstance(tab, dict):
                    sources.extend(_source_from_record(tool_name, tab, index))
        return sources
    sources.extend(_source_from_record(tool_name, data, 1))
    return sources


def _source_from_record(tool_name: str, data: dict[str, Any], index: int) -> list[dict[str, Any]]:
    raw_url = data.get("final_url") or data.get("url") or data.get("href")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return []
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    title = str(data.get("title") or data.get("name") or parsed.netloc)
    description = str(data.get("description") or data.get("snippet") or data.get("content") or "")
    description = " ".join(description.split())[:220]
    domain = parsed.netloc.lower()
    return [
        {
            "id": f"{tool_name}:{index}:{raw_url}",
            "title": title[:140],
            "description": description,
            "url": raw_url,
            "domain": domain,
            "favicon_url": f"https://www.google.com/s2/favicons?domain={domain}&sz=32",
            "tool_name": tool_name,
        }
    ]


def _file_line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


from . import project_snapshot as _ps  # noqa: E402
