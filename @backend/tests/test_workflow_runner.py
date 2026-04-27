"""Tests for the sequential workflow runner."""

import pytest

from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.application.workflows.contracts import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
)
from personagent.application.workflows.runner import (
    WorkflowExecutionError,
    WorkflowRunner,
)
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import ToolDefinition, ToolResult, build_tool


@pytest.mark.asyncio
async def test_workflow_runner_executes_trigger_agent_output_sequence():
    llm = StaticLLM(["agent output"])
    runner = WorkflowRunner(llm_backend=llm)
    document = WorkflowDocument(
        nodes=[
            WorkflowNode(id="trigger", type=WorkflowNodeType.TRIGGER, title="Trigger"),
            WorkflowNode(
                id="agent",
                type=WorkflowNodeType.AGENT,
                title="Agent",
                description="Summarize the payload.",
                x=280,
            ),
            WorkflowNode(id="output", type=WorkflowNodeType.OUTPUT, title="Output", x=560),
        ],
        edges=[
            WorkflowEdge(id="edge_trigger_agent", from_node_id="trigger", to_node_id="agent"),
            WorkflowEdge(id="edge_agent_output", from_node_id="agent", to_node_id="output"),
        ],
    )

    events = [
        event
        async for event in runner.execute(
            workflow_id="wf_1",
            title="Runner",
            document=document,
            run_input="input payload",
        )
    ]

    assert [event["event"] for event in events] == [
        "workflow_run_started",
        "node_started",
        "node_completed",
        "edge_selected",
        "node_started",
        "node_completed",
        "edge_selected",
        "node_started",
        "node_completed",
        "workflow_run_completed",
    ]
    assert events[-1]["output"] == "agent output"
    assert "input payload" in llm.prompts[0]


@pytest.mark.asyncio
async def test_workflow_runner_routes_if_else_with_llm_decision():
    llm = StaticLLM(["else"])
    runner = WorkflowRunner(llm_backend=llm)
    document = WorkflowDocument(
        nodes=[
            WorkflowNode(id="trigger", type=WorkflowNodeType.TRIGGER, title="Trigger"),
            WorkflowNode(id="router", type=WorkflowNodeType.IF_ELSE, title="Router", x=260),
            WorkflowNode(id="then_output", type=WorkflowNodeType.OUTPUT, title="Then", x=560),
            WorkflowNode(id="else_output", type=WorkflowNodeType.OUTPUT, title="Else", x=560, y=180),
        ],
        edges=[
            WorkflowEdge(id="edge_trigger_router", from_node_id="trigger", to_node_id="router"),
            WorkflowEdge(
                id="edge_router_then",
                from_node_id="router",
                to_node_id="then_output",
                from_handle="then",
            ),
            WorkflowEdge(
                id="edge_router_else",
                from_node_id="router",
                to_node_id="else_output",
                from_handle="else",
            ),
        ],
    )

    events = [
        event
        async for event in runner.execute(
            workflow_id="wf_router",
            title="Router",
            document=document,
            run_input="payload",
        )
    ]
    selected_edges = [event["edge_id"] for event in events if event["event"] == "edge_selected"]

    assert "edge_router_else" in selected_edges
    assert events[-1]["output"] == "payload"


@pytest.mark.asyncio
async def test_workflow_runner_blocks_browser_without_adapter():
    runner = WorkflowRunner(llm_backend=StaticLLM([]))
    document = WorkflowDocument(
        nodes=[
            WorkflowNode(id="trigger", type=WorkflowNodeType.TRIGGER, title="Trigger"),
            WorkflowNode(id="browser", type=WorkflowNodeType.BROWSER, title="Browser", x=260),
            WorkflowNode(id="output", type=WorkflowNodeType.OUTPUT, title="Output", x=560),
        ],
        edges=[
            WorkflowEdge(id="edge_trigger_browser", from_node_id="trigger", to_node_id="browser"),
            WorkflowEdge(id="edge_browser_output", from_node_id="browser", to_node_id="output"),
        ],
    )

    with pytest.raises(WorkflowExecutionError, match="Browser node"):
        [
            event
            async for event in runner.execute(
                workflow_id="wf_browser",
                title="Browser",
                document=document,
            )
        ]


@pytest.mark.asyncio
async def test_workflow_runner_executes_direct_tool_node(tmp_path):
    async def echo_handler(args, context, call):
        return ToolResult(
            tool_call_id=call.id,
            tool_name="echo",
            content=f"echo:{args['value']}",
        )

    tool = build_tool(
        definition=ToolDefinition(
            name="echo",
            description="Echo test tool",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        ),
        handler=echo_handler,
    )
    runner = WorkflowRunner(
        llm_backend=StaticLLM([]),
        tool_registry=ToolRegistry([tool]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )
    document = WorkflowDocument(
        nodes=[
            WorkflowNode(id="trigger", type=WorkflowNodeType.TRIGGER, title="Trigger"),
            WorkflowNode(
                id="tool",
                type=WorkflowNodeType.TOOL,
                title="Tool",
                config={"tool_name": "echo", "arguments": {"value": "real"}},
            ),
            WorkflowNode(id="output", type=WorkflowNodeType.OUTPUT, title="Output"),
        ],
        edges=[
            WorkflowEdge(id="edge_trigger_tool", from_node_id="trigger", to_node_id="tool"),
            WorkflowEdge(id="edge_tool_output", from_node_id="tool", to_node_id="output"),
        ],
    )

    events = [
        event
        async for event in runner.execute(
            workflow_id="wf_tool",
            title="Tool",
            document=document,
        )
    ]

    assert any(event["event"] == "tool_result" for event in events)
    assert events[-1]["output"] == "echo:real"


@pytest.mark.asyncio
async def test_workflow_runner_validates_schema_and_transforms_artifact():
    runner = WorkflowRunner(llm_backend=StaticLLM([]))
    document = WorkflowDocument(
        nodes=[
            WorkflowNode(id="trigger", type=WorkflowNodeType.TRIGGER, title="Trigger"),
            WorkflowNode(
                id="schema",
                type=WorkflowNodeType.SCHEMA_VALIDATOR,
                title="Schema",
                config={
                    "schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    }
                },
            ),
            WorkflowNode(
                id="artifact",
                type=WorkflowNodeType.ARTIFACT_TRANSFORM,
                title="Artifact",
                config={"format": "markdown", "title": "Validated"},
            ),
            WorkflowNode(id="output", type=WorkflowNodeType.OUTPUT, title="Output"),
        ],
        edges=[
            WorkflowEdge(id="edge_trigger_schema", from_node_id="trigger", to_node_id="schema"),
            WorkflowEdge(id="edge_schema_artifact", from_node_id="schema", to_node_id="artifact"),
            WorkflowEdge(id="edge_artifact_output", from_node_id="artifact", to_node_id="output"),
        ],
    )

    events = [
        event
        async for event in runner.execute(
            workflow_id="wf_schema",
            title="Schema",
            document=document,
            run_input={"title": "OK"},
        )
    ]

    assert events[-1]["output"].startswith("## Validated")
    assert '"title": "OK"' in events[-1]["output"]


class StaticLLM(LLMBackendRepository):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def chat_completion(self, messages, *args, **kwargs) -> InferenceResult:
        self.prompts.append(str(messages[-1]["content"]))
        content = self.responses.pop(0) if self.responses else ""
        return InferenceResult(content=content)

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(content="")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}
