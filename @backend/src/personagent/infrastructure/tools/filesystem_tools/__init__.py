"""Ferramentas de workspace: leitura, escrita, edição e busca."""

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
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.filesystem_tools.helpers import (
    _deny,
    _diff,
    _diff_line_counts,
    _display_path,
    _error,
    _file_output_schema,
    _grep_result,
    _grep_with_python,
    _is_ignored,
    _line_count,
    _mutation_output_schema,
    _positive_int,
    _search_output_schema,
)
from personagent.infrastructure.tools.path_safety import resolve_within_allowed_roots

_IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}


def create_read_file_tool() -> Tool:
    """Cria a ferramenta Read com alias legado read_file."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return _deny("Read requires a non-empty 'path' string.")

        try:
            resolved = resolve_within_allowed_roots(path, context)
        except ValueError as exc:
            return _deny(str(exc))

        if not resolved.exists():
            return _deny(f"File not found: {path}")
        if not resolved.is_file():
            return _deny(f"Path is not a file: {path}")
        return None

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        path = str(arguments["path"])
        resolved = resolve_within_allowed_roots(path, context)
        offset = _positive_int(arguments.get("offset"), default=1)
        explicit_limit = arguments.get("limit") is not None
        requested_limit = _positive_int(
            arguments.get("limit"),
            default=int(context.limits.get("read_default_limit", 200)),
        )
        max_lines = int(context.limits.get("read_max_lines", 1_000))
        max_bytes = int(context.limits.get("read_max_bytes", 128_000))
        limit = min(requested_limit, max_lines)
        limit_was_capped = requested_limit > max_lines

        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="Read",
                status=ToolExecutionStatus.RUNNING,
                message="Reading...",
                data={"path": str(resolved)},
            )
        )

        file_size = resolved.stat().st_size
        if file_size > max_bytes:
            return _error(
                call,
                "Read",
                (
                    f"File is too large ({file_size} bytes). "
                    f"Maximum allowed size is {max_bytes} bytes."
                ),
                {"path": str(resolved), "size_bytes": file_size},
            )

        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start_index = max(offset - 1, 0)
        end_index = min(start_index + limit, len(lines))
        selected = lines[start_index:end_index]
        numbered = [
            f"{line_number}: {line}"
            for line_number, line in enumerate(selected, start=start_index + 1)
        ]
        has_more = end_index < len(lines)
        truncated = limit_was_capped and has_more
        content = "\n".join(numbered)
        if truncated:
            content += f"\n[Output truncated. Continue at offset {end_index + 1}.]"
        elif has_more and not explicit_limit:
            content += f"\n[More lines available. Continue at offset {end_index + 1} if needed.]"

        data = {
            "type": "file_read",
            "path": str(resolved),
            "display_path": _display_path(resolved, context.workspace_root),
            "content": content,
            "start_line": start_index + 1 if selected else offset,
            "end_line": end_index,
            "total_lines": len(lines),
            "returned_lines": len(selected),
            "requested_offset": offset,
            "requested_limit": requested_limit,
            "effective_limit": limit,
            "limit_was_capped": limit_was_capped,
            "has_more": has_more,
            "next_offset": end_index + 1 if has_more else None,
            "truncated": truncated,
        }
        return ToolResult(
            tool_call_id=call.id,
            tool_name="Read",
            content=json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="Read",
            aliases=("read_file",),
            description="Read a text file inside the allowed workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or workspace-relative path to read.",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-based line number to start reading from.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Maximum number of lines to return.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema=_file_output_schema(),
            group=ToolGroup.WORKSPACE.value,
            search_hint="read open inspect file text lines",
            metadata={"category": "filesystem", "read_only": True},
            max_result_size_chars=40_000,
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
        to_auto_classifier_input=lambda args: args.get("path", ""),
    )


def create_write_file_tool() -> Tool:
    """Cria a ferramenta Write."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        path = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(path, str) or not path.strip():
            return _deny("Write requires a non-empty 'path' string.")
        if not isinstance(content, str):
            return _deny("Write requires a string 'content'.")
        try:
            resolved = resolve_within_allowed_roots(path, context)
        except ValueError as exc:
            return _deny(str(exc))
        if resolved.exists() and resolved.is_dir():
            return _deny(f"Path is a directory: {path}")
        max_bytes = int(
            context.limits.get("write_max_bytes", context.limits.get("read_max_bytes", 128_000))
        )
        if len(content.encode("utf-8")) > max_bytes:
            return _deny(f"Write content exceeds {max_bytes} bytes.")
        if resolved.exists() and arguments.get("overwrite") is False:
            return _deny(f"File already exists and overwrite is false: {path}")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        resolved = resolve_within_allowed_roots(str(arguments["path"]), context)
        content = str(arguments["content"])
        create_dirs = arguments.get("create_dirs", True) is not False
        if create_dirs:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        if not resolved.parent.is_dir():
            return _error(call, "Write", f"Parent directory does not exist: {resolved.parent}")

        existed = resolved.exists()
        old_content = resolved.read_text(encoding="utf-8", errors="replace") if existed else ""
        resolved.write_text(content, encoding="utf-8")
        diff = _diff(old_content, content, resolved.name) if existed else ""
        added_lines, removed_lines = (
            _diff_line_counts(diff) if existed else (_line_count(content), 0)
        )
        data = {
            "type": "file_write",
            "path": str(resolved),
            "display_path": _display_path(resolved, context.workspace_root),
            "bytes": len(content.encode("utf-8")),
            "created": not existed,
            "overwritten": existed,
            "diff": diff,
            "written_content": content,
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "content": f"Wrote {_display_path(resolved, context.workspace_root)}",
        }
        result_data = {key: value for key, value in data.items() if key != "written_content"}
        return ToolResult(
            tool_call_id=call.id,
            tool_name="Write",
            content=json.dumps(result_data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="Write",
            description="Create or replace a text file inside the allowed workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether an existing file may be replaced. Defaults to true.",
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": "Whether missing parent directories may be created. Defaults to true.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            output_schema=_mutation_output_schema("file_write"),
            group=ToolGroup.WORKSPACE.value,
            search_hint="write create replace save file",
            is_destructive=False,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_workspace_mutation_permission,
        to_auto_classifier_input=lambda args: args.get("path", ""),
    )


def create_edit_file_tool() -> Tool:
    """Cria a ferramenta Edit."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        path = arguments.get("path")
        old_string = arguments.get("old_string")
        new_string = arguments.get("new_string")
        if not isinstance(path, str) or not path.strip():
            return _deny("Edit requires a non-empty 'path' string.")
        if not isinstance(old_string, str) or old_string == "":
            return _deny("Edit requires a non-empty 'old_string'.")
        if not isinstance(new_string, str):
            return _deny("Edit requires a string 'new_string'.")
        try:
            resolved = resolve_within_allowed_roots(path, context)
        except ValueError as exc:
            return _deny(str(exc))
        if not resolved.exists():
            return _deny(f"File not found: {path}")
        if not resolved.is_file():
            return _deny(f"Path is not a file: {path}")
        text = resolved.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_string)
        if count == 0:
            return _deny("old_string was not found in the file.")
        if count > 1 and arguments.get("replace_all") is not True:
            return _deny("old_string matched multiple times. Set replace_all=true to replace all.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        resolved = resolve_within_allowed_roots(str(arguments["path"]), context)
        old_string = str(arguments["old_string"])
        new_string = str(arguments["new_string"])
        replace_all = arguments.get("replace_all") is True
        old_content = resolved.read_text(encoding="utf-8", errors="replace")
        new_content = (
            old_content.replace(old_string, new_string)
            if replace_all
            else old_content.replace(old_string, new_string, 1)
        )
        resolved.write_text(new_content, encoding="utf-8")
        data = {
            "type": "file_edit",
            "path": str(resolved),
            "display_path": _display_path(resolved, context.workspace_root),
            "replacements": old_content.count(old_string) if replace_all else 1,
            "diff": _diff(old_content, new_content, resolved.name),
            "content": f"Edited {_display_path(resolved, context.workspace_root)}",
        }
        return ToolResult(
            tool_call_id=call.id,
            tool_name="Edit",
            content=json.dumps(data, ensure_ascii=False),
            data=data,
        )

    return build_tool(
        definition=ToolDefinition(
            name="Edit",
            description="Replace exact text inside a workspace file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit."},
                    "old_string": {"type": "string", "description": "Exact text to replace."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all matches. Defaults to false and requires a unique match.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
                "additionalProperties": False,
            },
            output_schema=_mutation_output_schema("file_edit"),
            group=ToolGroup.WORKSPACE.value,
            search_hint="edit replace patch exact string file",
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=_workspace_mutation_permission,
        to_auto_classifier_input=lambda args: args.get("path", ""),
    )


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


async def _workspace_mutation_permission(
    arguments: ToolArguments,
    context: ToolUseContext,
) -> ToolPermissionResult:
    if context.permissions.get("plan_mode"):
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.DENY,
            message="Mutating workspace tools are blocked while Plan Mode is active.",
            metadata={"policy": "plan_mode_blocks_workspace_mutation"},
        )
    return ToolPermissionResult(
        behavior=ToolPermissionBehavior.ALLOW,
        updated_input=arguments,
        metadata={"policy": "workspace_root_scoped_mutation"},
    )


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


