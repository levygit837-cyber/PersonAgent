"""Search tools: glob, grep, search_files."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import shutil
from pathlib import Path
from typing import Any

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionResult,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.filesystem_tools.helpers import (
    _deny,
    _display_path,
    _error,
    _grep_result,
    _grep_with_python,
    _is_ignored,
    _positive_int,
    _search_output_schema,
)
from personagent.infrastructure.tools.path_safety import resolve_within_allowed_roots


def create_glob_tool() -> Tool:
    """Cria a ferramenta Glob."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return _deny("Glob requires a non-empty 'pattern' string.")
        try:
            root = resolve_within_allowed_roots(str(arguments.get("path") or "."), context)
        except ValueError as exc:
            return _deny(str(exc))
        if not root.exists():
            return _deny(f"Glob path not found: {root}")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        root = resolve_within_allowed_roots(str(arguments.get("path") or "."), context)
        pattern = str(arguments["pattern"])
        max_results = min(_positive_int(arguments.get("max_results"), default=100), 1000)
        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="Glob",
                status=ToolExecutionStatus.RUNNING,
                message="Searching...",
                data={"path": str(root), "pattern": pattern},
            )
        )
        matches = []
        if root.is_file():
            if fnmatch.fnmatch(root.name, pattern):
                matches = [root]
        else:
            matches = [path for path in root.glob(pattern) if not _is_ignored(path)]
        matches = sorted(matches, key=lambda item: str(item))[:max_results]
        content = "\n".join(_display_path(path, context.workspace_root) for path in matches)
        data = {
            "type": "glob_results",
            "path": str(root),
            "display_path": _display_path(root, context.workspace_root),
            "pattern": pattern,
            "matches": [_display_path(path, context.workspace_root) for path in matches],
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "content": content or "No files matched.",
        }
        return ToolResult(
            tool_call_id=call.id,
            tool_name="Glob",
            content=json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="Glob",
            description="Find files by glob pattern inside the allowed workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern such as '**/*.py'."},
                    "path": {
                        "type": "string",
                        "description": "Directory to search. Defaults to cwd.",
                    },
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            output_schema=_search_output_schema("glob_results"),
            group=ToolGroup.WORKSPACE.value,
            search_hint="glob find files path pattern",
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
        to_auto_classifier_input=lambda args: args.get("pattern", ""),
    )


def create_grep_tool() -> Tool:
    """Cria a ferramenta Grep com alias legado search_files."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return _deny("Grep requires a non-empty 'pattern' string.")
        try:
            resolved = resolve_within_allowed_roots(str(arguments.get("path") or "."), context)
        except ValueError as exc:
            return _deny(str(exc))
        if not resolved.exists():
            return _deny(f"Search path not found: {resolved}")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        search_path = resolve_within_allowed_roots(str(arguments.get("path") or "."), context)
        pattern = str(arguments["pattern"])
        max_results = min(_positive_int(arguments.get("max_results"), default=50), 500)
        timeout_ms = int(context.limits.get("search_timeout_ms", 15_000))
        glob = arguments.get("glob")

        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="Grep",
                status=ToolExecutionStatus.RUNNING,
                message="Searching...",
                data={"path": str(search_path), "pattern": pattern},
            )
        )

        rg = shutil.which("rg")
        if rg is not None:
            return await _grep_with_rg(
                rg=rg,
                search_path=search_path,
                pattern=pattern,
                glob=glob,
                max_results=max_results,
                timeout_ms=timeout_ms,
                context=context,
                call=call,
            )
        return _grep_with_python(
            search_path=search_path,
            pattern=pattern,
            glob=glob,
            max_results=max_results,
            context=context,
            call=call,
        )

    return build_tool(
        definition=ToolDefinition(
            name="Grep",
            aliases=("search_files",),
            description="Search text files in the workspace using ripgrep when available.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern."},
                    "path": {"type": "string", "description": "Directory or file to search."},
                    "glob": {
                        "type": "string",
                        "description": "Optional glob filter such as '*.py'.",
                    },
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            output_schema=_search_output_schema("search_results"),
            group=ToolGroup.WORKSPACE.value,
            search_hint="grep ripgrep rg search text symbol usage",
            metadata={"category": "filesystem", "read_only": True},
            max_result_size_chars=30_000,
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
        to_auto_classifier_input=lambda args: args.get("pattern", ""),
    )


def create_search_files_tool() -> Tool:
    """Compatibilidade: search_files agora é alias de Grep."""
    return create_grep_tool()



async def _grep_with_rg(
    *,
    rg: str,
    search_path: Path,
    pattern: str,
    glob: Any,
    max_results: int,
    timeout_ms: int,
    context: ToolUseContext,
    call: ToolCall,
) -> ToolResult:
    cmd = [
        rg,
        "--hidden",
        "--line-number",
        "--color",
        "never",
        "--max-columns",
        "300",
        "--glob",
        "!.git",
    ]
    if isinstance(glob, str) and glob.strip():
        cmd.extend(["--glob", glob.strip()])
    cmd.extend([pattern, str(search_path)])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_ms / 1000)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return _error(call, "Grep", f"Search timed out after {timeout_ms}ms.")

    if process.returncode not in (0, 1):
        return _error(
            call,
            "Grep",
            stderr.decode("utf-8", errors="replace").strip() or "Search failed.",
        )

    lines = stdout.decode("utf-8", errors="replace").splitlines()
    return _grep_result(lines, search_path, pattern, max_results, context, call)


