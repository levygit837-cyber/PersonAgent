"""Read file tool."""

from __future__ import annotations

import json

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
    _file_output_schema,
    _positive_int,
)
from personagent.infrastructure.tools.path_safety import resolve_within_allowed_roots


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


