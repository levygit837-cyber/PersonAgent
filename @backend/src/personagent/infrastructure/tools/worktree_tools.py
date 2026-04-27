"""Worktree tools for isolated repository edits."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from tempfile import gettempdir

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def create_enter_worktree_tool() -> Tool:
    """Create EnterWorktree."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        name = str(arguments.get("name") or "agent-worktree").strip()
        if not _SLUG_RE.match(name):
            return _deny(
                "EnterWorktree name must start with an alphanumeric character and use only "
                "letters, numbers, underscore, dash or dot."
            )
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        root = await _git_root(context.workspace_root)
        if root is None:
            return _error(call, "EnterWorktree", "EnterWorktree requires a git workspace.")

        name = str(arguments.get("name") or "agent-worktree").strip()
        branch = str(arguments.get("branch") or f"personagent/{name}").strip()
        worktree_path = _worktree_path(root, name)
        if not worktree_path.exists():
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            result = await _run(
                [
                    "git",
                    "-C",
                    str(root),
                    "worktree",
                    "add",
                    "-B",
                    branch,
                    str(worktree_path),
                    "HEAD",
                ],
                cwd=root,
            )
            if result.return_code != 0:
                return _error(
                    call,
                    "EnterWorktree",
                    result.stderr or result.stdout or "git worktree add failed.",
                    data={"stdout": result.stdout, "stderr": result.stderr},
                )

        previous = {
            "cwd": str(context.metadata.get("active_cwd") or context.cwd),
            "allowed_roots": list(context.metadata.get("active_allowed_roots") or ()),
            "workspace_root": str(context.metadata.get("active_workspace_root") or context.workspace_root),
        }
        context.metadata["active_cwd"] = str(worktree_path)
        context.metadata["active_allowed_roots"] = [str(worktree_path)]
        context.metadata["active_workspace_root"] = str(worktree_path)
        context.metadata["worktree_binding"] = {
            "name": name,
            "branch": branch,
            "main_root": str(root),
            "path": str(worktree_path),
            "previous": previous,
        }
        data = {
            "type": "worktree",
            "action": "enter",
            "name": name,
            "branch": branch,
            "path": str(worktree_path),
            "content": f"Entered worktree {worktree_path}.",
        }
        return ToolResult(call.id, "EnterWorktree", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="EnterWorktree",
            description=(
                "Create or enter an isolated git worktree and route subsequent workspace "
                "tools to it for this tool context."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "branch": {
                        "type": "string",
                        "description": "Optional git branch name. Defaults to personagent/<name>.",
                    },
                },
                "additionalProperties": False,
            },
            group=ToolGroup.WORKTREE.value,
            search_hint="git worktree isolated workspace enter",
            is_destructive=False,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_workspace_permission,
    )


def create_exit_worktree_tool() -> Tool:
    """Create ExitWorktree."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        action = str(arguments.get("action") or "keep")
        if action not in {"keep", "remove"}:
            return _deny("ExitWorktree action must be 'keep' or 'remove'.")
        if "worktree_binding" not in context.metadata:
            return _deny("No active worktree binding exists in this tool context.")
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        binding = dict(context.metadata.get("worktree_binding") or {})
        action = str(arguments.get("action") or "keep")
        path = Path(str(binding.get("path") or "")).expanduser()
        main_root = Path(str(binding.get("main_root") or context.workspace_root)).expanduser()
        if not path:
            return _error(call, "ExitWorktree", "Active worktree binding is missing a path.")

        dirty = await _dirty_state(path)
        if action == "remove" and dirty["dirty"] and arguments.get("discard_changes") is not True:
            data = {
                "type": "worktree",
                "action": "refuse_remove_dirty",
                "path": str(path),
                "dirty": dirty,
                "content": "Worktree has uncommitted changes; pass discard_changes=true to remove.",
            }
            return ToolResult(
                call.id,
                "ExitWorktree",
                json.dumps(data, ensure_ascii=False),
                status=ToolExecutionStatus.ERROR,
                is_error=True,
                data=data,
            )

        previous = dict(binding.get("previous") or {})
        if previous.get("cwd"):
            context.metadata["active_cwd"] = previous["cwd"]
        else:
            context.metadata.pop("active_cwd", None)
        if previous.get("allowed_roots"):
            context.metadata["active_allowed_roots"] = previous["allowed_roots"]
        else:
            context.metadata.pop("active_allowed_roots", None)
        if previous.get("workspace_root"):
            context.metadata["active_workspace_root"] = previous["workspace_root"]
        else:
            context.metadata.pop("active_workspace_root", None)
        context.metadata.pop("worktree_binding", None)

        removed = False
        if action == "remove":
            if arguments.get("discard_changes") is True and path.exists():
                await _run(["git", "-C", str(path), "reset", "--hard"], cwd=path)
                await _run(["git", "-C", str(path), "clean", "-fd"], cwd=path)
            result = await _run(
                ["git", "-C", str(main_root), "worktree", "remove", "--force", str(path)],
                cwd=main_root,
            )
            if result.return_code != 0 and path.exists():
                shutil.rmtree(path, ignore_errors=True)
            removed = True

        data = {
            "type": "worktree",
            "action": action,
            "path": str(path),
            "removed": removed,
            "dirty": dirty,
            "content": f"Exited worktree {path}.",
        }
        return ToolResult(call.id, "ExitWorktree", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="ExitWorktree",
            description=(
                "Leave the active worktree. Use action=remove to remove it; dirty worktrees are "
                "protected unless discard_changes=true is explicit."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["keep", "remove"]},
                    "discard_changes": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            group=ToolGroup.WORKTREE.value,
            search_hint="git worktree exit remove keep dirty",
            is_destructive=True,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_workspace_permission,
    )


async def _workspace_permission(
    arguments: ToolArguments,
    context: ToolUseContext,
) -> ToolPermissionResult:
    if str(context.permissions.get("mode") or "").lower() in {"read_only", "readonly"}:
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.DENY,
            message="Worktree tools are blocked in read-only permission mode.",
        )
    if str(arguments.get("action") or "").lower() == "remove":
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.ASK,
            message="permission_required: removing a worktree requires approval.",
            metadata={"tool": "ExitWorktree", "action": "remove"},
        )
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
    )


async def _git_root(path: Path) -> Path | None:
    result = await _run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], cwd=path)
    if result.return_code != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def _worktree_path(root: Path, name: str) -> Path:
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    return Path(gettempdir()) / "personagent-worktrees" / digest / name


async def _dirty_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"dirty": False, "status": "", "exists": False}
    result = await _run(["git", "-C", str(path), "status", "--porcelain"], cwd=path)
    status = result.stdout
    return {"dirty": bool(status.strip()), "status": status, "exists": True}


async def _run(command: list[str], *, cwd: Path) -> _RunResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return _RunResult(
        return_code=int(process.returncode or 0),
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


class _RunResult:
    def __init__(self, *, return_code: int, stdout: str, stderr: str) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr


def _error(
    call: ToolCall,
    tool_name: str,
    message: str,
    data: dict[str, object] | None = None,
) -> ToolResult:
    payload = {"type": "worktree", "content": message, **(data or {})}
    return ToolResult(
        call.id,
        tool_name,
        json.dumps(payload, ensure_ascii=False),
        status=ToolExecutionStatus.ERROR,
        is_error=True,
        data=payload,
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)

