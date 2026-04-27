from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools import (
    InMemoryTaskStore,
    ToolOrchestrator,
    ToolRegistry,
    ToolRuntimeConfig,
)
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.models.conversation import Conversation
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository
from personagent.domain.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools import (
    create_edit_file_tool,
    create_enter_plan_mode_tool,
    create_exit_plan_mode_tool,
    create_glob_tool,
    create_grep_tool,
    create_lsp_tool,
    create_read_file_tool,
    create_skill_tool,
    create_structured_output_tool,
    create_task_tools,
    create_todo_write_tool,
    create_tool_search_tool,
    create_web_fetch_tool,
    create_web_search_tool,
    create_write_file_tool,
    web_tools,
)


def test_registry_exposes_claude_names_aliases_deferred_and_schema_cache(tmp_path):
    registry = ToolRegistry(
        [
            create_read_file_tool(),
            create_skill_tool(),
            create_web_search_tool(enabled=False),
        ]
    )
    registry.register(create_tool_search_tool(lambda: registry))

    schemas = registry.openai_schemas(cache_scope="test")
    names = [schema["function"]["name"] for schema in schemas]

    assert "Read" in names
    assert "ToolSearch" in names
    assert "Skill" not in names
    assert "WebSearch" not in names
    assert registry.get("read_file") is registry.get("Read")

    registry.openai_schemas(cache_scope="test")
    assert registry.schema_cache.hits == 1

    skill_schema = registry.openai_schemas(allowed_tools={"Skill"}, cache_scope="test")
    assert [schema["function"]["name"] for schema in skill_schema] == ["Skill"]

    search = registry.get("ToolSearch")
    assert search is not None
    result = asyncio.run(
        search.call({"query": "web"}, _tool_context(tmp_path), ToolCall("search", "ToolSearch", {}))
    )
    data = json.loads(result.content)
    assert any(tool["name"] == "WebSearch" and tool["enabled"] is False for tool in data["tools"])


def test_plan_mode_tool_descriptions_are_explicit_request_only():
    enter = create_enter_plan_mode_tool()
    exit_plan = create_exit_plan_mode_tool()

    assert "only when the user explicitly asks" in enter.definition.description
    assert "normal task execution" in enter.definition.description
    assert "only after EnterPlanMode is active" in exit_plan.definition.description
    assert "generic approval request" in exit_plan.definition.description


@pytest.mark.asyncio
async def test_workspace_write_edit_glob_grep_and_plan_mode_policy(tmp_path):
    context = _tool_context(tmp_path)
    write = create_write_file_tool()
    edit = create_edit_file_tool()
    glob = create_glob_tool()
    grep = create_grep_tool()

    write_call = ToolCall("write", "Write", {"path": "src/notes.txt", "content": "alpha\nbeta\n"})
    result = await write.call(write_call.arguments, context, write_call)
    assert result.status == ToolExecutionStatus.COMPLETED
    assert (tmp_path / "src" / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"
    write_data = json.loads(result.content)
    assert write_data["added_lines"] == 2
    assert write_data["removed_lines"] == 0
    assert "written_content" not in write_data
    assert result.data["written_content"] == "alpha\nbeta\n"

    edit_call = ToolCall(
        "edit",
        "Edit",
        {"path": "src/notes.txt", "old_string": "beta", "new_string": "gamma"},
    )
    validation = await edit.validate_input(edit_call.arguments, context)
    assert validation is None
    edit_result = await edit.call(edit_call.arguments, context, edit_call)
    assert "gamma" in (tmp_path / "src" / "notes.txt").read_text(encoding="utf-8")
    assert "diff" in edit_result.data

    multi = ToolCall(
        "edit_multi",
        "Edit",
        {"path": "src/notes.txt", "old_string": "a", "new_string": "x"},
    )
    denied = await edit.validate_input(multi.arguments, context)
    assert denied is not None
    assert denied.allowed is False

    glob_result = await glob.call(
        {"path": ".", "pattern": "**/*.txt"},
        context,
        ToolCall("glob", "Glob", {}),
    )
    assert "src/notes.txt" in glob_result.data["matches"]

    grep_result = await grep.call(
        {"path": ".", "pattern": "gamma"},
        context,
        ToolCall("grep", "Grep", {}),
    )
    assert "gamma" in grep_result.data["content"]

    plan_context = _tool_context(tmp_path, plan_mode=True)
    permission = await write.check_permissions(write_call.arguments, plan_context)
    assert permission.allowed is False


@pytest.mark.asyncio
async def test_web_fetch_validates_hosts_and_extracts_html(monkeypatch, tmp_path):
    tool = create_web_fetch_tool()
    context = _tool_context(tmp_path)

    denied = await tool.validate_input({"url": "http://127.0.0.1:8000"}, context)
    assert denied is not None
    assert denied.allowed is False

    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html><script>bad()</script><body><h1>Hello</h1><p>World</p></body></html>"
        encoding = "utf-8"
        url = "https://example.com/page"
        status_code = 200
        is_success = True

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, _url):
            return FakeResponse()

    monkeypatch.setattr(web_tools.httpx, "AsyncClient", FakeClient)
    result = await tool.call(
        {"url": "https://example.com/page"},
        context,
        ToolCall("fetch", "WebFetch", {}),
    )
    assert result.status == ToolExecutionStatus.COMPLETED
    assert "Hello" in result.data["content"]
    assert "bad()" not in result.data["content"]


@pytest.mark.asyncio
async def test_task_todo_and_plan_tools(tmp_path):
    context = _tool_context(tmp_path)
    store = InMemoryTaskStore()
    task_by_name = {tool.definition.name: tool for tool in create_task_tools(store)}
    todo = create_todo_write_tool()
    enter = create_enter_plan_mode_tool()
    exit_plan = create_exit_plan_mode_tool()

    created = await task_by_name["TaskCreate"].call(
        {"title": "Document tool runtime", "priority": "high"},
        context,
        ToolCall("create", "TaskCreate", {}),
    )
    task_id = created.data["task"]["id"]

    listed = await task_by_name["TaskList"].call({}, context, ToolCall("list", "TaskList", {}))
    assert listed.data["count"] == 1

    updated = await task_by_name["TaskUpdate"].call(
        {"task_id": task_id, "status": "completed", "output": "Done"},
        context,
        ToolCall("update", "TaskUpdate", {}),
    )
    assert updated.data["task"]["status"] == "completed"

    output = await task_by_name["TaskOutput"].call(
        {"task_id": task_id},
        context,
        ToolCall("output", "TaskOutput", {}),
    )
    assert output.data["output"] == "Done"

    stopped = await task_by_name["TaskStop"].call(
        {"task_id": task_id},
        context,
        ToolCall("stop", "TaskStop", {}),
    )
    assert stopped.data["task"]["status"] == "cancelled"

    todos = await todo.call(
        {"todos": [{"content": "Inspect runtime", "status": "in_progress"}]},
        context,
        ToolCall("todos", "TodoWrite", {}),
    )
    assert context.metadata["todos"][0]["content"] == "Inspect runtime"
    assert todos.data["todos"][0]["status"] == "in_progress"

    enter_result = await enter.call({"reason": "Need a plan"}, context, ToolCall("enter", "EnterPlanMode", {}))
    assert context.permissions["plan_mode"] is True
    assert enter_result.data["state"]["active"] is True
    assert enter_result.data["state"]["status"] == "draft"
    permission = await task_by_name["TaskUpdate"].check_permissions({"task_id": task_id}, context)
    assert permission.allowed is False
    exit_result = await exit_plan.call(
        {"plan": "## Plan\n\n1. Update backend."},
        context,
        ToolCall("exit", "ExitPlanMode", {}),
    )
    assert context.permissions["plan_mode"] is True
    assert exit_result.data["action"] == "request_approval"
    assert exit_result.data["state"]["status"] == "awaiting_approval"
    assert exit_result.data["state"]["plan_content"] == "## Plan\n\n1. Update backend."
    assert exit_result.data["state"]["approval_id"]


@pytest.mark.asyncio
async def test_skill_structured_output_lsp_and_websearch_contracts(tmp_path):
    skill_dir = tmp_path / ".personagent" / "skills" / "writer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Writer\n\nUse concise prose.", encoding="utf-8")

    context = _tool_context(tmp_path)
    skill = create_skill_tool()
    structured = create_structured_output_tool()
    lsp = create_lsp_tool(enabled=False)
    web_search = create_web_search_tool(enabled=False)

    skill_result = await skill.call({"name": "writer"}, context, ToolCall("skill", "Skill", {}))
    assert "Use concise prose" in skill_result.data["content"]

    valid = await structured.validate_input(
        {
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "value": {"answer": "ok"},
        },
        context,
    )
    assert valid is None

    invalid = await structured.validate_input(
        {
            "schema": {"type": "object", "required": ["answer"]},
            "value": {},
        },
        context,
    )
    assert invalid is not None
    assert invalid.allowed is False

    assert lsp.is_enabled() is False
    assert web_search.is_enabled() is False


@pytest.mark.asyncio
async def test_orchestrator_preserves_parallel_result_order_and_emits_group_events(tmp_path):
    async def handler(args, context, call):
        await asyncio.sleep(0.02 if call.id == "call_1" else 0)
        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="ordered",
                status=ToolExecutionStatus.RUNNING,
                message=f"progress {call.id}",
            )
        )
        return ToolResult(call.id, "ordered", call.id)

    tool = build_tool(
        definition=ToolDefinition(
            name="ordered",
            description="Ordered test tool",
            input_schema={"type": "object", "properties": {}},
            is_concurrency_safe=True,
        ),
        handler=handler,
    )
    orchestrator = ToolOrchestrator(
        ToolRegistry([tool]),
        ToolRuntimeConfig.from_values(workspace_root=tmp_path, max_concurrency=2),
    )

    events = [
        event
        async for event in orchestrator.execute(
            [
                ToolCall("call_1", "ordered", {}),
                ToolCall("call_2", "ordered", {}),
            ],
            _tool_context(tmp_path),
        )
    ]
    result_ids = [event.call.id for event in events if event.result is not None]
    event_names = [event.event for event in events]

    assert result_ids == ["call_1", "call_2"]
    assert "tool_group_started" in event_names
    assert "tool_group_finished" in event_names


@pytest.mark.asyncio
async def test_agent_selects_search_tool_from_indirect_prompt(tmp_path):
    (tmp_path / "notes.txt").write_text("alpha\ngamma\n", encoding="utf-8")
    repo = MemoryConversationRepository()
    llm = HeuristicSearchLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_grep_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    response = await use_case.execute(
        ChatRequestDTO(message="Quais arquivos mencionam gamma?", tools_enabled=True)
    )
    conversation = await repo.get_by_id(response.conversation_id)

    assert response.content == "gamma aparece em notes.txt."
    assert conversation is not None
    tool_messages = [message for message in conversation.messages if message.tool_call_id]
    assert tool_messages
    assert tool_messages[0].metadata["tool_name"] == "Grep"


def _tool_context(root: Path, *, plan_mode: bool = False) -> ToolUseContext:
    return ToolUseContext(
        conversation_id="test",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        permissions={"mode": "ask_for_risk", "plan_mode": plan_mode},
        limits={
            "read_max_bytes": 128_000,
            "read_default_limit": 200,
            "read_max_lines": 1_000,
            "search_timeout_ms": 15_000,
            "shell_timeout_ms": 10_000,
            "web_timeout_ms": 15_000,
            "web_max_bytes": 512_000,
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": ("localhost", "127.0.0.1", "0.0.0.0"),
            "skill_roots": (),
        },
        metadata={},
    )


class MemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return [
            conversation
            for conversation in self.conversations.values()
            if query in conversation.title
        ][:limit]


class HeuristicSearchLLM(LLMBackendRepository):
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        self.calls += 1
        if self.calls == 1:
            tool_names = {tool["function"]["name"] for tool in kwargs["tools"]}
            assert "Grep" in tool_names
            return InferenceResult(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "call_grep",
                        "type": "function",
                        "function": {
                            "name": "Grep",
                            "arguments": '{"pattern":"gamma","path":"."}',
                        },
                    }
                ],
            )
        return InferenceResult(content="gamma aparece em notes.txt.")

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(content="unused")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}
