"""Ferramentas de descoberta, skills e saída estruturada."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from personagent.application.tools import ToolRegistry
from personagent.domain.prompts.skills import find_skill, is_skill_enabled
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


def create_tool_search_tool(registry_provider: Callable[[], ToolRegistry]) -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        query = arguments.get("query")
        if query is not None and not isinstance(query, str):
            return _deny("ToolSearch query must be a string.")
        return None

    async def handler(
        arguments: ToolArguments, _context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        registry = registry_provider()
        query = str(arguments.get("query") or "")
        limit = _positive_int(arguments.get("limit"), 8)
        tools = registry.search(query, limit=limit, include_disabled=True)
        results = [tool.definition.to_discovery_dict(enabled=tool.is_enabled()) for tool in tools]
        data = {"type": "tool_search", "query": query, "tools": results, "count": len(results)}
        return ToolResult(call.id, "ToolSearch", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="ToolSearch",
            description="Discover available or deferred tools by query, group, name or select:<tool_name>.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.DISCOVERY.value,
            search_hint="discover find tools schema select",
            always_load=True,
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def create_skill_tool() -> Tool:
    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return _deny("Skill requires a non-empty 'name' string.")
        if "/" in name or "\\" in name or ".." in name:
            return _deny("Skill name cannot contain path traversal.")
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        name = str(arguments["name"]).strip()
        skill = find_skill(
            name,
            workspace_root=context.workspace_root,
            cwd=context.cwd,
            extra_roots=tuple(str(path) for path in context.limits.get("skill_roots", ())),
        )
        if skill is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name="Skill",
                content=f"Skill not found: {name}",
                status=ToolExecutionStatus.ERROR,
                is_error=True,
            )
        skill_roots = tuple(str(path) for path in context.limits.get("skill_roots", ()))
        if not is_skill_enabled(
            skill,
            workspace_root=context.workspace_root,
            cwd=context.cwd,
            extra_roots=skill_roots,
        ):
            return ToolResult(
                tool_call_id=call.id,
                tool_name="Skill",
                content=f"Skill is disabled: {name}",
                status=ToolExecutionStatus.ERROR,
                is_error=True,
            )
        content = skill.body
        max_chars = int(context.limits.get("result_max_chars", 20_000))
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars] + "\n[Skill truncated.]"
        data = {
            "type": "skill",
            "name": skill.name,
            "path": str(skill.path),
            "description": skill.description,
            "allowed_tools": list(skill.allowed_tools),
            "argument_hint": skill.argument_hint,
            "model": skill.model,
            "disable_model_invocation": skill.disable_model_invocation,
            "user_invocable": skill.user_invocable,
            "model_invocable": skill.model_invocable,
            "when_to_use": skill.when_to_use,
            "context": skill.context,
            "frontmatter": skill.metadata,
            "content": content,
            "truncated": truncated,
        }
        return ToolResult(call.id, "Skill", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="Skill",
            description="Load a local skill's SKILL.md instructions by name.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.DISCOVERY.value,
            search_hint="skill load instructions capability",
            should_defer=True,
            is_read_only=True,
            is_concurrency_safe=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def create_structured_output_tool() -> Tool:
    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        schema = arguments.get("schema") or context.metadata.get("structured_output_schema")
        if not isinstance(schema, dict):
            return _deny("StructuredOutput requires a JSON schema object.")
        if "value" not in arguments:
            return _deny("StructuredOutput requires a 'value'.")
        errors = _validate_json_schema_subset(arguments["value"], schema)
        if errors:
            return _deny("Structured output validation failed: " + "; ".join(errors[:6]))
        return None

    async def handler(
        arguments: ToolArguments, context: ToolUseContext, call: ToolCall
    ) -> ToolResult:
        schema = arguments.get("schema") or context.metadata.get("structured_output_schema")
        value = arguments["value"]
        data = {"type": "structured_output", "schema": schema, "value": value}
        return ToolResult(
            call.id, "StructuredOutput", json.dumps(data, ensure_ascii=False), data=data
        )

    return build_tool(
        definition=ToolDefinition(
            name="StructuredOutput",
            description="Return a value only if it validates against the provided JSON schema.",
            input_schema={
                "type": "object",
                "properties": {
                    "schema": {"type": "object", "additionalProperties": True},
                    "value": {"description": "JSON value to validate."},
                },
                "required": ["value"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            group=ToolGroup.OUTPUT.value,
            search_hint="json schema structured output validate",
            is_read_only=True,
        ),
        handler=handler,
        validate_input=validate,
    )


def _validate_json_schema_subset(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_json_type_matches(value, item) for item in expected_type):
            errors.append(f"{path} expected one of {expected_type}")
            return errors
    elif isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        errors.append(f"{path} expected {expected_type}")
        return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} expected one of {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        properties = schema.get("properties") or {}
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(
                    _validate_json_schema_subset(value[key], child_schema, f"{path}.{key}")
                )
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                errors.append(f"{path} has unexpected keys: {', '.join(sorted(extra))}")

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_validate_json_schema_subset(item, schema["items"], f"{path}[{index}]"))
    return errors


def _json_type_matches(value: Any, expected_type: str) -> bool:
    return (
        (expected_type == "object" and isinstance(value, dict))
        or (expected_type == "array" and isinstance(value, list))
        or (expected_type == "string" and isinstance(value, str))
        or (expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool))
        or (
            expected_type == "number"
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        )
        or (expected_type == "boolean" and isinstance(value, bool))
        or (expected_type == "null" and value is None)
    )


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 50))


__all__ = [
    "create_skill_tool",
    "create_structured_output_tool",
    "create_tool_search_tool",
]
