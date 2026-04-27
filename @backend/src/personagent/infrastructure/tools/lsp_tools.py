"""LSP tool contract V1."""

from __future__ import annotations

from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolResult,
    ToolUseContext,
    build_tool,
)


def create_lsp_tool(*, enabled: bool = False) -> Tool:
    """Registra LSP como contrato desabilitado até existir um backend configurado."""

    async def handler(
        _arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            tool_name="LSP",
            content="LSP is registered but disabled until an LSP backend is configured.",
            status=ToolExecutionStatus.ERROR,
            is_error=True,
            data={"type": "lsp", "enabled": False},
        )

    return build_tool(
        definition=ToolDefinition(
            name="LSP",
            description="Language-server backed symbols, definitions, references and diagnostics.",
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["symbols", "definition", "references", "diagnostics"],
                    },
                    "path": {"type": "string"},
                    "symbol": {"type": "string"},
                    "line": {"type": "integer", "minimum": 1},
                    "character": {"type": "integer", "minimum": 0},
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.LSP.value,
            search_hint="language server symbols definitions references diagnostics",
            should_defer=True,
            is_read_only=True,
            is_concurrency_safe=True,
            is_lsp=True,
        ),
        handler=handler,
        enabled=enabled,
    )


__all__ = ["create_lsp_tool"]
