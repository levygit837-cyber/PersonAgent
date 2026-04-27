"""Sequential workflow runner for the canvas V1."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.application.workflows.contracts import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    validate_workflow_document,
)
from personagent.domain.models.inference_result import InferenceResult
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolCall, ToolUseContext


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow node cannot execute."""


class WorkflowRunner:
    """Runs workflow nodes by following edges, never by visual position."""

    def __init__(
        self,
        *,
        llm_backend: LLMBackendRepository,
        tool_registry: ToolRegistry | None = None,
        tool_runtime_config: ToolRuntimeConfig | None = None,
    ) -> None:
        self._llm_backend = llm_backend
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config

    async def execute(
        self,
        *,
        workflow_id: str,
        title: str,
        document: WorkflowDocument,
        run_input: Any = "",
        tool_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a workflow and yield SSE-ready metadata dictionaries."""

        validate_workflow_document(document)
        run_id = f"run_{uuid4().hex}"
        node_by_id = {node.id: node for node in document.nodes}
        outgoing = _outgoing_edges(document)
        trigger = next(node for node in document.nodes if node.type == WorkflowNodeType.TRIGGER)

        yield {
            "event": "workflow_run_started",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "title": title,
        }

        current = trigger
        current_input = run_input
        visited: set[str] = set()
        while True:
            if current.id in visited:
                raise WorkflowExecutionError("Workflow execution encountered a cycle.")
            visited.add(current.id)

            yield _event("node_started", current, run_id, workflow_id)
            current_output = None
            async for payload in self._execute_node_events(
                current,
                current_input,
                run_id=run_id,
                workflow_id=workflow_id,
                tool_context=tool_context or {},
            ):
                if "_node_output" in payload:
                    current_output = payload["_node_output"]
                else:
                    yield payload
            yield _event(
                "node_completed",
                current,
                run_id,
                workflow_id,
                output=_preview(current_output),
                output_value=current_output,
            )

            if current.type == WorkflowNodeType.OUTPUT:
                yield {
                    "event": "workflow_run_completed",
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "output": current_output,
                }
                return

            next_edge = await self._select_next_edge(current, current_output, outgoing)
            yield {
                "event": "edge_selected",
                "workflow_id": workflow_id,
                "run_id": run_id,
                "node_id": current.id,
                "edge_id": next_edge.id,
                "from_handle": next_edge.from_handle,
                "to_node_id": next_edge.to_node_id,
            }
            current = node_by_id[next_edge.to_node_id]
            current_input = current_output

    async def _execute_node_events(
        self,
        node: WorkflowNode,
        node_input: Any,
        *,
        run_id: str,
        workflow_id: str,
        tool_context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        self._assert_supported_perks(node)

        if node.type == WorkflowNodeType.TRIGGER:
            yield {
                "_node_output": (
                    node_input if node_input not in (None, "") else node.config.get("payload", "")
                )
            }
            return
        if node.type == WorkflowNodeType.AGENT:
            async for payload in self._execute_agent_node(
                node,
                node_input,
                run_id=run_id,
                workflow_id=workflow_id,
                tool_context=tool_context,
            ):
                yield payload
            return
        if node.type == WorkflowNodeType.IF_ELSE:
            yield {"_node_output": node_input}
            return
        if node.type == WorkflowNodeType.TOOL:
            async for payload in self._execute_tool_node(
                node,
                node_input,
                run_id=run_id,
                workflow_id=workflow_id,
                tool_context=tool_context,
            ):
                yield payload
            return
        if node.type == WorkflowNodeType.SCHEMA_VALIDATOR:
            yield {"_node_output": self._execute_schema_validator_node(node, node_input)}
            return
        if node.type == WorkflowNodeType.ARTIFACT_TRANSFORM:
            yield {"_node_output": self._execute_artifact_transform_node(node, node_input)}
            return
        if node.type == WorkflowNodeType.OUTPUT:
            yield {"_node_output": node_input}
            return
        if node.type == WorkflowNodeType.BROWSER:
            raise WorkflowExecutionError("Browser node is contracted but has no V1 adapter yet.")

        raise WorkflowExecutionError(f"Node type {node.type.value} has no V1 executor.")

    async def _execute_agent_node(
        self,
        node: WorkflowNode,
        node_input: Any,
        *,
        run_id: str,
        workflow_id: str,
        tool_context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        system_prompt = str(
            node.config.get("system_prompt")
            or "You are an agent node inside a sequential PersonAgent workflow."
        )
        messages.append({"role": "system", "content": system_prompt})
        instruction = str(
            node.config.get("instructions") or node.config.get("prompt") or node.description
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Node instruction:\n{instruction}\n\n"
                    f"Previous node output:\n{_stringify(node_input)}"
                ),
            }
        )

        tool_schemas = self._tool_schemas_for_node(node)
        context = self._tool_context_for_node(node, tool_context) if tool_schemas else None
        max_iterations = int(node.config.get("max_tool_iterations") or 4)
        temperature = float(node.config.get("temperature", 0.2))
        max_tokens = int(node.config.get("max_tokens", -1))
        model = node.config.get("model")
        reasoning_level = node.config.get("reasoning_level")
        reasoning_budget_tokens = node.config.get("reasoning_budget_tokens")

        result: InferenceResult | None = None
        for _iteration in range(max_iterations):
            result = await self._llm_backend.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                tools=tool_schemas,
                tool_choice="auto" if tool_schemas else None,
                model=model,
                reasoning_level=reasoning_level,
                reasoning_budget_tokens=reasoning_budget_tokens,
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": result.tool_calls,
                }
            )
            tool_calls = _parse_tool_calls(result.tool_calls)
            if not tool_calls or context is None:
                yield {"_node_output": result.content}
                return

            async for metadata in self._execute_tool_calls(
                tool_calls,
                context,
                node_id=node.id,
                run_id=run_id,
                workflow_id=workflow_id,
            ):
                tool_message = metadata.pop("_tool_message")
                if tool_message["content"]:
                    messages.append(tool_message)
                yield metadata

        if result is not None and result.content:
            yield {"_node_output": result.content}
            return
        raise WorkflowExecutionError(f"Agent node {node.id} exceeded tool iteration limit.")

    async def _execute_tool_node(
        self,
        node: WorkflowNode,
        node_input: Any,
        *,
        run_id: str,
        workflow_id: str,
        tool_context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        tool_name = str(
            node.config.get("tool_name")
            or node.config.get("tool")
            or node.config.get("name")
            or (node.tools[0] if node.tools else "")
        ).strip()
        if not tool_name:
            raise WorkflowExecutionError(f"Tool node {node.id} must define config.tool_name.")

        raw_arguments = node.config.get("arguments")
        if raw_arguments is None and bool(
            node.config.get("use_previous_output_as_arguments", True)
        ):
            raw_arguments = node_input
        arguments = _coerce_tool_arguments(raw_arguments)
        context = self._tool_context_for_node(node, tool_context)
        call = ToolCall(
            id=f"workflow_tool_{uuid4().hex}",
            name=tool_name,
            arguments=arguments,
            raw={"workflow_node_id": node.id},
        )

        node_output: Any = ""
        async for metadata in self._execute_tool_calls(
            [call],
            context,
            node_id=node.id,
            run_id=run_id,
            workflow_id=workflow_id,
        ):
            tool_message = metadata.pop("_tool_message")
            if tool_message["content"]:
                node_output = tool_message["content"]
            yield metadata
        yield {"_node_output": node_output}

    def _execute_schema_validator_node(self, node: WorkflowNode, node_input: Any) -> Any:
        schema = (
            node.config.get("schema") or node.input_contract.schema_ or node.output_contract.schema_
        )
        if not schema:
            return node_input
        if not isinstance(schema, dict):
            raise WorkflowExecutionError(f"Schema validator node {node.id} has invalid schema.")
        errors = _validate_json_schema_subset(node_input, schema)
        if errors:
            joined = "; ".join(errors[:6])
            raise WorkflowExecutionError(f"Schema validator node {node.id} failed: {joined}")
        return node_input

    def _execute_artifact_transform_node(self, node: WorkflowNode, node_input: Any) -> Any:
        value = node_input
        field = node.config.get("field")
        if field and isinstance(value, dict):
            value = value.get(str(field))

        target_format = str(node.config.get("format") or node.config.get("target_format") or "text")
        title = str(node.config.get("title") or node.title)
        if target_format == "json":
            return json.dumps(value, ensure_ascii=False, indent=2)
        if target_format == "markdown":
            return f"## {title}\n\n{_stringify(value)}"
        return _stringify(value)

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        context: ToolUseContext,
        *,
        node_id: str,
        run_id: str,
        workflow_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._tool_registry is None or self._tool_runtime_config is None:
            raise WorkflowExecutionError("Tool runtime is not configured.")

        orchestrator = ToolOrchestrator(self._tool_registry, self._tool_runtime_config)
        async for event in orchestrator.execute(tool_calls, context):
            payload = event.to_stream_metadata()
            payload.update({"workflow_id": workflow_id, "run_id": run_id, "node_id": node_id})
            if event.result is not None:
                payload["_tool_message"] = {
                    "role": "tool",
                    "tool_call_id": event.call.id,
                    "content": event.result.content,
                }
            else:
                payload["_tool_message"] = {
                    "role": "tool",
                    "tool_call_id": event.call.id,
                    "content": "",
                }
            yield payload

    async def _select_next_edge(
        self,
        node: WorkflowNode,
        node_output: Any,
        outgoing: dict[str, list[WorkflowEdge]],
    ) -> WorkflowEdge:
        edges = outgoing.get(node.id, [])
        if node.type != WorkflowNodeType.IF_ELSE:
            return edges[0]

        route = await self._route_if_else(node, node_output)
        for edge in edges:
            if edge.from_handle == route:
                return edge
        raise WorkflowExecutionError(f"If/Else node {node.id} selected missing route {route}.")

    async def _route_if_else(self, node: WorkflowNode, node_output: Any) -> str:
        then_goal = str(node.config.get("then_goal") or node.config.get("then") or "true")
        else_goal = str(node.config.get("else_goal") or node.config.get("else") or "false")
        condition = str(node.config.get("condition") or node.description or node.title)
        result = await self._llm_backend.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "Return only one token: then or else.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Condition: {condition}\n"
                        f"Then route goal: {then_goal}\n"
                        f"Else route goal: {else_goal}\n"
                        f"Input: {_stringify(node_output)}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=8,
            stream=False,
        )
        normalized = result.content.strip().lower()
        return "else" if normalized.startswith("else") else "then"

    def _tool_schemas_for_node(self, node: WorkflowNode) -> list[dict[str, Any]]:
        if self._tool_registry is None:
            return []
        tools_enabled = bool(node.tools) or bool(node.perks.get("tools"))
        if not tools_enabled:
            return []
        allowed_tools = set(node.tools) if node.tools else None
        return self._tool_registry.openai_schemas(
            allowed_tools=allowed_tools,
            cache_scope=f"workflow:{node.id}",
        )

    def _tool_context_for_node(
        self,
        node: WorkflowNode,
        run_context: dict[str, Any],
    ) -> ToolUseContext:
        if self._tool_runtime_config is None:
            raise WorkflowExecutionError("Tool runtime is not configured.")

        config = self._tool_runtime_config
        node_context = dict(run_context)
        node_context.update(dict(node.config.get("tool_context") or {}))
        workspace_root = _resolve_workspace_root(
            node_context.get("workspace_root"),
            fallback=config.workspace_root,
        )
        allowed_roots = tuple(
            _resolve_allowed_path(str(path), workspace_root, (workspace_root,))
            for path in node_context.get("allowed_roots", [workspace_root])
        )
        cwd = _resolve_allowed_path(
            str(node_context.get("cwd", workspace_root)), workspace_root, allowed_roots
        )
        if not cwd.is_dir():
            raise WorkflowExecutionError(f"Tool cwd is not a directory: {cwd}")

        return ToolUseContext(
            conversation_id=f"workflow:{node.id}",
            workspace_root=workspace_root,
            cwd=cwd,
            allowed_roots=allowed_roots,
            permissions={
                "mode": "ask_for_risk",
                "plan_mode": bool(node_context.get("plan_mode")),
            },
            limits={
                "read_max_bytes": config.read_max_bytes,
                "read_default_limit": config.read_default_limit,
                "read_max_lines": config.read_max_lines,
                "search_timeout_ms": config.search_timeout_ms,
                "shell_timeout_ms": config.shell_timeout_ms,
                "web_timeout_ms": config.web_timeout_ms,
                "web_max_bytes": config.web_max_bytes,
                "result_max_chars": config.result_max_chars,
                "tool_result_storage_root": (
                    str(config.tool_result_storage_root)
                    if config.tool_result_storage_root
                    else None
                ),
                "web_allowed_domains": config.web_allowed_domains,
                "web_blocked_domains": config.web_blocked_domains,
                "skill_roots": tuple(str(path) for path in config.skill_roots),
            },
            metadata={"workflow_node": node.id, "request": node_context},
        )

    def _assert_supported_perks(self, node: WorkflowNode) -> None:
        unsupported = {"queue", "database", "memory", "browser", "redis"}
        enabled = [name for name in unsupported if bool(node.perks.get(name))]
        if enabled:
            joined = ", ".join(sorted(enabled))
            raise WorkflowExecutionError(f"Node {node.id} requires unsupported V1 perks: {joined}.")


def _event(
    event: str,
    node: WorkflowNode,
    run_id: str,
    workflow_id: str,
    *,
    output: str | None = None,
    output_value: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "node_id": node.id,
        "node_type": node.type.value,
        "node_title": node.title,
    }
    if output is not None:
        payload["output_preview"] = output
    if output_value is not None:
        payload["output"] = output_value
    return payload


def _outgoing_edges(document: WorkflowDocument) -> dict[str, list[WorkflowEdge]]:
    outgoing: dict[str, list[WorkflowEdge]] = {}
    for edge in document.edges:
        outgoing.setdefault(edge.from_node_id, []).append(edge)
    return outgoing


def _parse_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
    if not tool_calls:
        return []
    calls = [ToolCall.from_openai(call) for call in tool_calls]
    return [call for call in calls if call.id and call.name]


def _resolve_workspace_root(value: Any, *, fallback: Path) -> Path:
    if not value:
        return fallback
    path = Path(str(value)).expanduser().resolve()
    if not path.is_dir():
        raise WorkflowExecutionError(f"Workspace root is not a directory: {path}")
    return path


def _resolve_allowed_path(
    raw_path: str,
    base_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    path = Path(raw_path).expanduser()
    candidate = path if path.is_absolute() else base_root / path
    resolved = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise WorkflowExecutionError(f"Tool path is outside configured roots: {raw_path}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _preview(value: Any) -> str:
    text = _stringify(value)
    return text if len(text) <= 600 else f"{text[:600]}..."


def _coerce_tool_arguments(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"input": value}
        if isinstance(decoded, dict):
            return decoded
        return {"input": decoded}
    return {"input": value}


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

    if expected_type == "object" or "properties" in schema:
        if not isinstance(value, dict):
            errors.append(f"{path} expected object")
            return errors
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{path}.{field} is required")
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            for field, field_schema in properties.items():
                if field in value and isinstance(field_schema, dict):
                    errors.extend(
                        _validate_json_schema_subset(value[field], field_schema, f"{path}.{field}")
                    )

    if expected_type == "array" or "items" in schema:
        if not isinstance(value, list):
            errors.append(f"{path} expected array")
            return errors
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_json_schema_subset(item, item_schema, f"{path}[{index}]"))

    return errors


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True
