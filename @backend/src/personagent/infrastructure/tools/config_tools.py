"""PersonAgent-style Config tool for controlled runtime/session settings."""

from __future__ import annotations

import json
from typing import Any

from personagent.application.tools.runtime_config import DEFAULT_MAX_TOOL_ITERATIONS
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

_SETTINGS: dict[str, dict[str, Any]] = {
    "permission_mode": {
        "source": "permissions",
        "type": "string",
        "allowed": {"read_only", "manual", "ask_for_risk", "accept_edits", "full", "bypass"},
    },
    "default_provider": {"source": "metadata", "type": "string"},
    "default_model": {"source": "metadata", "type": "string"},
    "max_tool_iterations": {
        "source": "limits",
        "type": "integer",
        "min": 1,
        "max": 64,
        "default": DEFAULT_MAX_TOOL_ITERATIONS,
    },
    "max_concurrency": {"source": "limits", "type": "integer", "min": 1, "max": 16},
    "auto_compact": {"source": "metadata", "type": "boolean"},
    "mcp.enabled": {"source": "metadata", "type": "boolean"},
    "brief_tool_enabled": {"source": "metadata", "type": "boolean"},
}


def create_config_tool() -> Tool:
    """Create Config, an allowlisted config get/set tool."""

    async def validate(
        arguments: ToolArguments, _context: ToolUseContext
    ) -> ToolPermissionResult | None:
        action = str(arguments.get("action") or "get")
        if action not in {"get", "set", "list"}:
            return _deny("Config action must be 'get', 'set' or 'list'.")
        key = arguments.get("key")
        if action != "list":
            if not isinstance(key, str) or not key.strip():
                return _deny("Config requires a non-empty 'key' for get/set.")
            if key not in _SETTINGS:
                return _deny(f"Config setting is not allowlisted: {key}")
        if action == "set":
            if "value" not in arguments:
                return _deny("Config set requires a 'value'.")
            error = _validate_value(str(key), arguments.get("value"))
            if error:
                return _deny(error)
        return None

    async def check_permissions(
        arguments: ToolArguments,
        _context: ToolUseContext,
    ) -> ToolPermissionResult:
        if str(arguments.get("action") or "get") == "set":
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.ASK,
                message=(
                    "permission_required: changing runtime/session config requires approval."
                ),
                metadata={"setting": arguments.get("key"), "value": arguments.get("value")},
            )
        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.ALLOW,
            updated_input=arguments,
        )

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        action = str(arguments.get("action") or "get")
        if action == "list":
            data = {
                "type": "config",
                "settings": {
                    key: {
                        "value": _get_config_value(key, context),
                        "source": spec["source"],
                        "type": spec["type"],
                    }
                    for key, spec in _SETTINGS.items()
                },
            }
            return ToolResult(call.id, "Config", json.dumps(data, ensure_ascii=False), data=data)

        key = str(arguments["key"])
        previous = _get_config_value(key, context)
        if action == "get":
            data = {
                "type": "config",
                "key": key,
                "value": previous,
                "content": f"{key} = {previous!r}",
            }
            return ToolResult(call.id, "Config", json.dumps(data, ensure_ascii=False), data=data)

        value = _coerce_value(key, arguments["value"])
        _set_config_value(key, value, context)
        data = {
            "type": "config",
            "key": key,
            "previous": previous,
            "value": _get_config_value(key, context),
            "content": f"Updated {key}.",
        }
        return ToolResult(call.id, "Config", json.dumps(data, ensure_ascii=False), data=data)

    return build_tool(
        definition=ToolDefinition(
            name="Config",
            description=(
                "Read or update a small allowlist of runtime/session settings. Reads are "
                "automatic; writes require user approval."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["get", "set", "list"]},
                    "key": {"type": "string", "enum": sorted(_SETTINGS)},
                    "value": {
                        "description": "New value for set operations.",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "integer"},
                            {"type": "number"},
                            {"type": "boolean"},
                            {"type": "null"},
                        ],
                    },
                },
                "additionalProperties": False,
            },
            group=ToolGroup.CONFIG.value,
            search_hint="config permission provider model iterations mcp brief",
            usage_prompt=(
                "Use Config to inspect allowlisted runtime/session settings. Set only when the "
                "user asked for a runtime policy or default change."
            ),
            is_read_only=False,
        ),
        handler=handler,
        validate_input=validate,
        check_permissions=check_permissions,
        is_concurrency_safe=lambda args: str(args.get("action") or "get") in {"get", "list"},
        is_read_only=lambda args: str(args.get("action") or "get") in {"get", "list"},
    )


def _get_config_value(key: str, context: ToolUseContext) -> Any:
    if key == "permission_mode":
        return context.permissions.get("mode", "manual")
    if key == "max_tool_iterations":
        return context.limits.get("max_tool_iterations", DEFAULT_MAX_TOOL_ITERATIONS)
    if key == "max_concurrency":
        return context.limits.get("max_concurrency", 4)
    values = context.metadata.setdefault("config", {})
    return values.get(key)


def _set_config_value(key: str, value: Any, context: ToolUseContext) -> None:
    value = _coerce_value(key, value)
    if key == "permission_mode":
        context.permissions["mode"] = value
        return
    if key == "max_tool_iterations":
        context.limits["max_tool_iterations"] = value
        return
    if key == "max_concurrency":
        context.limits["max_concurrency"] = value
        return
    context.metadata.setdefault("config", {})[key] = value


def _validate_value(key: str, value: Any) -> str | None:
    try:
        _coerce_value(key, value)
    except ValueError as exc:
        return str(exc)
    return None


def _coerce_value(key: str, value: Any) -> Any:
    spec = _SETTINGS[key]
    value_type = spec["type"]
    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0"}:
            return value.strip().lower() in {"true", "1"}
        raise ValueError(f"{key} must be a boolean.")
    if value_type == "integer":
        if isinstance(value, bool):
            raise ValueError(f"{key} must be an integer.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be an integer.") from exc
        minimum = int(spec.get("min", parsed))
        maximum = int(spec.get("max", parsed))
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}.")
        return parsed
    if value_type == "string":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string.")
        parsed = value.strip()
        allowed = spec.get("allowed")
        if allowed and parsed not in allowed:
            raise ValueError(f"{key} must be one of: {', '.join(sorted(allowed))}.")
        return parsed
    return value


def _deny(message: str) -> ToolPermissionResult:
    return ToolPermissionResult(behavior=ToolPermissionBehavior.DENY, message=message)

