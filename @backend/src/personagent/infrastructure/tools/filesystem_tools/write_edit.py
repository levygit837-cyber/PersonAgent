"""Write and edit file tools."""

from __future__ import annotations

import json

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.dev.path_safety import resolve_within_allowed_roots
from personagent.infrastructure.tools.filesystem_tools.helpers import (
    _deny,
    _diff,
    _diff_line_counts,
    _display_path,
    _error,
    _line_count,
    _mutation_output_schema,
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

