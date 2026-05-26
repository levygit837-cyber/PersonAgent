"""Session panel aggregation for the desktop chat UI."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Re-export helpers from panel_utils so existing imports continue to work.
from personagent.application.services.session.panel_utils import (  # noqa: F401
    _add,
    _compact_memory_label,
    _diff_stats,
    _estimate_tokens,
    _file_line_count,
    _first_int,
    _first_int_with_key,
    _memory_entry_add,
    _memory_trace,
    _memory_trace_items,
    _metric,
    _optional_int,
    _safe_int,
    _source_from_record,
    _sources_from_tool_data,
    _tool_data,
)
from personagent.domain.conversation.models import Conversation


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


from personagent.application.services.insights import project_snapshot as _ps  # noqa: E402

from . import conversation_panel_data as _cd  # noqa: E402
