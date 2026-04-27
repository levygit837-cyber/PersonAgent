"""Typed contracts for the workflow canvas."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkflowValidationError(ValueError):
    """Raised when a workflow document cannot be executed safely."""


class WorkflowNodeType(StrEnum):
    """Node types known by the workflow canvas."""

    TRIGGER = "trigger"
    AGENT = "agent"
    IF_ELSE = "if_else"
    OUTPUT = "output"
    BROWSER = "browser"
    TOOL = "tool"
    SCHEMA_VALIDATOR = "schema_validator"
    MEMORY = "memory"
    HUMAN_APPROVAL = "human_approval"
    QUEUE_DELAY = "queue_delay"
    SUBWORKFLOW = "subworkflow"
    ARTIFACT_TRANSFORM = "artifact_transform"


class TriggerMode(StrEnum):
    """How a workflow can be triggered."""

    MANUAL = "manual"
    CRON = "cron"


class WorkflowViewport(BaseModel):
    """Canvas viewport state."""

    x: float = 0
    y: float = 0
    zoom: float = 0.72


class WorkflowIOContract(BaseModel):
    """Loose JSON-compatible input/output contract for a node."""

    kind: str = "any"
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    description: str = ""

    model_config = ConfigDict(populate_by_name=True)


class WorkflowNode(BaseModel):
    """A typed executable point in the workflow graph."""

    id: str = Field(min_length=1)
    type: WorkflowNodeType
    title: str = Field(min_length=1)
    description: str = ""
    x: float = 0
    y: float = 0
    width: float = 240
    height: float = 126
    status: str = "queued"
    progress: float = 0
    output_kind: str = "any"
    output_preview: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    input_contract: WorkflowIOContract = Field(default_factory=WorkflowIOContract)
    output_contract: WorkflowIOContract = Field(default_factory=WorkflowIOContract)
    tools: list[str] = Field(default_factory=list)
    perks: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tools", mode="before")
    @classmethod
    def _coerce_tools(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]


class WorkflowEdge(BaseModel):
    """A directional connection between two workflow nodes."""

    id: str = Field(min_length=1)
    from_node_id: str = Field(min_length=1)
    to_node_id: str = Field(min_length=1)
    from_handle: str = "out"
    to_handle: str = "in"
    status: str = "queued"
    label: str = ""


class WorkflowDocument(BaseModel):
    """Persisted workflow document."""

    schema_version: str = "1.0"
    viewport: WorkflowViewport = Field(default_factory=WorkflowViewport)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    selected_node_id: str | None = None
    execution_state: dict[str, Any] = Field(default_factory=lambda: {"mode": "idle"})
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


def serialize_workflow_document(document: WorkflowDocument) -> dict[str, Any]:
    """Return a JSON-compatible workflow document."""

    payload = document.model_dump(mode="json", by_alias=True)
    for node in payload.get("nodes") or []:
        if node.get("type") == WorkflowNodeType.TRIGGER.value:
            node["type"] = "manual_trigger"
    return payload


def default_workflow_document() -> dict[str, Any]:
    """Create a minimal valid workflow document for new canvases."""

    document = WorkflowDocument(
        viewport=WorkflowViewport(),
        nodes=[
            WorkflowNode(
                id="trigger",
                type=WorkflowNodeType.TRIGGER,
                title="Trigger",
                description="Starts the workflow from a run payload or on a schedule.",
                x=80,
                y=260,
                output_kind="payload",
                output_contract=WorkflowIOContract(kind="payload"),
                config={"trigger_mode": "manual", "default_payload": ""},
            ),
            WorkflowNode(
                id="output",
                type=WorkflowNodeType.OUTPUT,
                title="Final Output",
                description="Collects the final workflow output.",
                x=390,
                y=260,
                width=260,
                output_kind="artifact_bundle",
                input_contract=WorkflowIOContract(kind="any"),
            ),
        ],
        edges=[
            WorkflowEdge(
                id="edge_trigger_output",
                from_node_id="trigger",
                to_node_id="output",
            )
        ],
        selected_node_id="trigger",
    )
    return serialize_workflow_document(document)


def parse_workflow_document(payload: dict[str, Any]) -> WorkflowDocument:
    """Parse a document, accepting the legacy Lab shape when possible."""

    return WorkflowDocument.model_validate(_normalize_legacy_payload(payload))


def validate_workflow_document(document: WorkflowDocument) -> None:
    """Validate graph rules required by the sequential runner."""

    if not document.nodes:
        raise WorkflowValidationError("Workflow must contain nodes.")

    node_by_id = {node.id: node for node in document.nodes}
    if len(node_by_id) != len(document.nodes):
        raise WorkflowValidationError("Workflow node IDs must be unique.")

    triggers = [node for node in document.nodes if node.type == WorkflowNodeType.TRIGGER]
    if len(triggers) != 1:
        raise WorkflowValidationError("Workflow must contain exactly one manual trigger.")

    for edge in document.edges:
        if edge.from_node_id not in node_by_id:
            raise WorkflowValidationError(f"Edge {edge.id} has an unknown source node.")
        if edge.to_node_id not in node_by_id:
            raise WorkflowValidationError(f"Edge {edge.id} has an unknown target node.")
        if edge.from_node_id == edge.to_node_id:
            raise WorkflowValidationError(f"Edge {edge.id} cannot connect a node to itself.")

    outgoing = _outgoing_edges(document)
    for node in document.nodes:
        count = len(outgoing.get(node.id, []))
        if node.type == WorkflowNodeType.OUTPUT:
            if count != 0:
                raise WorkflowValidationError("Output nodes cannot have outgoing edges.")
        elif node.type == WorkflowNodeType.IF_ELSE:
            handles = {edge.from_handle for edge in outgoing.get(node.id, [])}
            if handles != {"then", "else"}:
                raise WorkflowValidationError("If/Else nodes must have then and else edges.")
        elif count != 1:
            raise WorkflowValidationError(f"Node {node.id} must have exactly one outgoing edge.")

    _assert_acyclic(document)
    _assert_reachable(document, triggers[0].id)


def _outgoing_edges(document: WorkflowDocument) -> dict[str, list[WorkflowEdge]]:
    outgoing: dict[str, list[WorkflowEdge]] = {}
    for edge in document.edges:
        outgoing.setdefault(edge.from_node_id, []).append(edge)
    return outgoing


def _assert_acyclic(document: WorkflowDocument) -> None:
    outgoing = _outgoing_edges(document)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise WorkflowValidationError("Workflow graph cannot contain cycles.")
        if node_id in visited:
            return
        visiting.add(node_id)
        for edge in outgoing.get(node_id, []):
            visit(edge.to_node_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node in document.nodes:
        visit(node.id)


def _assert_reachable(document: WorkflowDocument, trigger_id: str) -> None:
    outgoing = _outgoing_edges(document)
    reachable: set[str] = set()
    queue: deque[str] = deque([trigger_id])
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        for edge in outgoing.get(node_id, []):
            queue.append(edge.to_node_id)

    missing = {node.id for node in document.nodes} - reachable
    if missing:
        joined = ", ".join(sorted(missing))
        raise WorkflowValidationError(f"All nodes must be reachable from trigger: {joined}.")


def _normalize_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("schema_version", "1.0")

    type_map = {
        "agent_session": WorkflowNodeType.TRIGGER.value,
        "manual_trigger": WorkflowNodeType.TRIGGER.value,
        "instruction": WorkflowNodeType.AGENT.value,
        "router": WorkflowNodeType.IF_ELSE.value,
        "llm_call": WorkflowNodeType.AGENT.value,
        "natural_tool": WorkflowNodeType.TOOL.value,
        "schema_contract": WorkflowNodeType.SCHEMA_VALIDATOR.value,
        "memory_write": WorkflowNodeType.MEMORY.value,
        "output_collector": WorkflowNodeType.OUTPUT.value,
    }

    nodes = []
    for raw_node in normalized.get("nodes") or []:
        node = dict(raw_node)
        raw_type = str(node.get("type") or "")
        node["type"] = type_map.get(raw_type, raw_type)
        if node["type"] not in {item.value for item in WorkflowNodeType}:
            node["type"] = WorkflowNodeType.AGENT.value
        node.setdefault("config", {})
        node.setdefault("input_contract", {"kind": "any"})
        node.setdefault("output_contract", {"kind": node.get("output_kind") or "any"})
        node.setdefault("tools", [])
        node.setdefault("perks", {})
        nodes.append(node)
    normalized["nodes"] = nodes

    edges = []
    for raw_edge in normalized.get("edges") or []:
        edge = dict(raw_edge)
        edge.setdefault("from_node_id", edge.pop("from", ""))
        edge.setdefault("to_node_id", edge.pop("to", ""))
        edge.setdefault("from_handle", "out")
        edge.setdefault("to_handle", "in")
        edges.append(edge)
    normalized["edges"] = edges
    return normalized


def node_config_schema(node_type: WorkflowNodeType) -> dict[str, Any]:
    """Return the typed config schema for a given node type."""

    if node_type == WorkflowNodeType.TRIGGER:
        return {
            "type": "object",
            "properties": {
                "trigger_mode": {
                    "type": "string",
                    "enum": ["manual", "cron"],
                    "default": "manual",
                },
                "cron_expression": {"type": "string", "default": ""},
                "timezone": {"type": "string", "default": "America/Sao_Paulo"},
                "default_payload": {"type": "string", "default": ""},
            },
            "required": ["trigger_mode"],
        }
    if node_type == WorkflowNodeType.AGENT:
        return {
            "type": "object",
            "properties": {
                "system_prompt": {
                    "type": "string",
                    "default": (
                        "You are an agent node inside a sequential PersonAgent workflow. "
                        "Follow the node instruction, ground output in previous node data, "
                        "use tools pragmatically when enabled, and return only the node result.\n\n"
                        "# Shared PersonAgent Policy\n\n"
                        "- Gather evidence before conclusions.\n"
                        "- When TodoWrite is available, use it for multi-step node work.\n"
                        "- Use parallel tools only for independent reads/searches/checks."
                    ),
                },
                "instructions": {
                    "type": "string",
                    "default": "Describe what this agent should do.",
                },
                "model": {"type": "string", "default": ""},
                "temperature": {"type": "number", "default": 0.2, "minimum": 0, "maximum": 2},
                "max_tokens": {"type": "integer", "default": -1},
                "max_tool_iterations": {
                    "type": "integer",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 20,
                },
                "reasoning_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                },
                "reasoning_budget_tokens": {"type": "integer", "default": 0},
            },
            "required": ["instructions"],
        }
    if node_type == WorkflowNodeType.TOOL:
        return {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "default": ""},
                "arguments": {"type": "object", "default": {}},
                "use_previous_output_as_arguments": {"type": "boolean", "default": True},
                "timeout_ms": {"type": "integer", "default": 30000},
            },
            "required": ["tool_name"],
        }
    if node_type == WorkflowNodeType.IF_ELSE:
        return {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "default": "Choose whether the previous output should use then or else.",
                },
                "then_goal": {
                    "type": "string",
                    "default": "The objective matches the expected route.",
                },
                "else_goal": {
                    "type": "string",
                    "default": "The objective does not match the expected route.",
                },
            },
            "required": ["condition"],
        }
    if node_type == WorkflowNodeType.SCHEMA_VALIDATOR:
        return {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "object",
                    "default": {"type": "object", "properties": {}, "required": []},
                },
            },
        }
    if node_type == WorkflowNodeType.ARTIFACT_TRANSFORM:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["text", "json", "markdown"],
                    "default": "text",
                },
                "field": {"type": "string", "default": ""},
                "title": {"type": "string", "default": "Workflow Artifact"},
            },
        }
    if node_type == WorkflowNodeType.OUTPUT:
        return {"type": "object", "properties": {}}
    return {"type": "object", "additionalProperties": True}
