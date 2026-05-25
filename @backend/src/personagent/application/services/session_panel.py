"""Session panel aggregation for the desktop chat UI."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from personagent.domain.models.conversation import Conversation, Message

_TEXT_TOKEN_DIVISOR = 4


@dataclass(frozen=True, slots=True)
class SessionPanelService:
    """Builds the panel snapshot from conversation metadata, Git and GitHub."""

    workspace_root: str | Path | None = None

    async def panel_snapshot(self, conversation: Conversation) -> dict[str, Any]:
        workspace = self._workspace()
        # Compute conversation-derived data concurrently with project snapshot.
        changed_files_task = asyncio.create_task(_cd.changed_files_async(conversation, workspace))
        sources_task = asyncio.create_task(_cd.sources_async(conversation))
        usage_task = asyncio.create_task(_cd.usage_async(conversation))
        memory_task = asyncio.create_task(_cd.memory_summary_async(conversation))
        project_task = asyncio.create_task(_ps.project_snapshot_async(workspace))

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


from . import conversation_panel_data as _cd  # noqa: E402
from . import project_snapshot as _ps  # noqa: E402
