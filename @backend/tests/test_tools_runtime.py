from __future__ import annotations

import asyncio
import json
from uuid import UUID

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.application.tools.runtime_config import DEFAULT_MAX_TOOL_ITERATIONS
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.models.inference_result import InferenceResult, StreamChunk
from personagent.domain.prompts.services import PromptContextAnalyzer
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
from personagent.infrastructure.llm.llama_cpp_adapter import LlamaCppAdapter
from personagent.infrastructure.persistence.context import InMemoryContextRepository
from personagent.infrastructure.tools import (
    classify_read_only_shell,
    create_exit_plan_mode_tool,
    create_read_file_tool,
    create_shell_tool,
    create_skill_tool,
    create_todo_write_tool,
)
from personagent.infrastructure.tools.shell_tool import validate_shell_path_scope


@pytest.mark.asyncio
async def test_build_tool_defaults_are_safe(tmp_path):
    async def handler(args, context, call):
        return None

    tool = build_tool(
        definition=ToolDefinition(
            name="sample",
            description="Sample tool",
            input_schema={"type": "object", "properties": {}},
        ),
        handler=handler,
    )

    assert tool.is_enabled() is True
    assert tool.is_concurrency_safe({}) is False
    assert tool.is_read_only({}) is False
    assert tool.is_destructive({}) is False
    assert tool.to_auto_classifier_input({}) == ""


@pytest.mark.asyncio
async def test_read_file_tool_enforces_allowed_roots_and_returns_lines(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    context = _tool_context(tmp_path)
    tool = create_read_file_tool()
    call = ToolCall(id="call_read", name="read_file", arguments={"path": "notes.txt"})

    validation = await tool.validate_input(call.arguments, context)
    assert validation is None

    result = await tool.call(call.arguments, context, call)
    assert result.status == ToolExecutionStatus.COMPLETED
    assert "1: alpha" in result.data["content"]
    assert result.data["display_path"] == "notes.txt"

    outside = ToolCall(id="call_outside", name="read_file", arguments={"path": "/etc/passwd"})
    denied = await tool.validate_input(outside.arguments, context)
    assert denied is not None
    assert denied.allowed is False


@pytest.mark.asyncio
async def test_shell_blocks_mutating_commands(tmp_path):
    tool = create_shell_tool()
    context = _tool_context(tmp_path)

    assert classify_read_only_shell("ls -la")[0] is True
    assert (
        classify_read_only_shell(
            "pwd && find . -maxdepth 1 -type f | sed 's#^\\./##' | sort | head -200"
        )[0]
        is True
    )
    assert classify_read_only_shell("rm -rf .")[0] is False
    assert classify_read_only_shell("pwd && rm -rf .")[0] is False
    assert classify_read_only_shell("cat $HOME/.ssh/id_rsa")[0] is False
    assert classify_read_only_shell("find . -delete")[0] is False
    assert classify_read_only_shell("sed -i.bak s/a/b/ notes.txt")[0] is False
    assert validate_shell_path_scope("cat /etc/passwd", context)[0] is False
    assert validate_shell_path_scope("pwd && cat /etc/passwd", context)[0] is False

    permission = await tool.check_permissions({"command": "rm -rf ."}, context)
    assert permission.allowed is False
    assert permission.behavior.value == "ask"

    permission = await tool.check_permissions({"command": "cat /etc/passwd"}, context)
    assert permission.allowed is False
    assert permission.behavior.value == "ask"


@pytest.mark.asyncio
async def test_shell_executes_read_only_chains_with_shell_semantics(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    tool = create_shell_tool()
    context = _tool_context(tmp_path)
    command = "pwd && find . -maxdepth 1 -type f | sed 's#^\\./##' | sort | head -200"

    permission = await tool.check_permissions({"command": command}, context)
    assert permission.allowed is True

    result = await tool.call(
        {"command": command},
        context,
        ToolCall(id="call_shell", name="shell", arguments={"command": command}),
    )

    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.data["return_code"] == 0
    assert str(tmp_path) in result.data["stdout"]
    assert "a.txt" in result.data["stdout"]
    assert "unexpected argument" not in result.data["stderr"]


@pytest.mark.asyncio
async def test_orchestrator_returns_permission_required_for_risky_shell(tmp_path):
    registry = ToolRegistry([create_shell_tool()])
    config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    orchestrator = ToolOrchestrator(registry, config)
    context = _tool_context(tmp_path)
    call = ToolCall(id="call_shell", name="shell", arguments={"command": "rm -rf ."})

    events = [event async for event in orchestrator.execute([call], context)]

    assert events[0].event == "tool_call_started"
    assert events[-1].event == "permission_required"
    assert events[-1].result is not None
    assert events[-1].result.status == ToolExecutionStatus.PERMISSION_REQUIRED


@pytest.mark.asyncio
async def test_orchestrator_streams_progress_before_result(tmp_path):
    async def handler(args, context, call):
        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="slow_read",
                status=ToolExecutionStatus.RUNNING,
                message="step",
            )
        )
        await asyncio.sleep(0.01)
        return ToolResult(
            tool_call_id=call.id,
            tool_name="slow_read",
            content="done",
        )

    tool = build_tool(
        definition=ToolDefinition(
            name="slow_read",
            description="Slow read",
            input_schema={"type": "object", "properties": {}},
        ),
        handler=handler,
        is_concurrency_safe=lambda _args: True,
    )
    orchestrator = ToolOrchestrator(
        ToolRegistry([tool]),
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    events = [
        event.event
        async for event in orchestrator.execute(
            [ToolCall(id="call_slow", name="slow_read", arguments={})],
            _tool_context(tmp_path),
        )
    ]

    assert events == ["tool_call_started", "tool_progress", "tool_result"]


@pytest.mark.asyncio
async def test_orchestrator_applies_tool_definition_result_limit(tmp_path):
    async def handler(args, context, call):
        return ToolResult(
            tool_call_id=call.id,
            tool_name="limited_read",
            content="x" * 100,
        )

    tool = build_tool(
        definition=ToolDefinition(
            name="limited_read",
            description="Limited read",
            input_schema={"type": "object", "properties": {}},
            max_result_size_chars=12,
        ),
        handler=handler,
    )
    orchestrator = ToolOrchestrator(
        ToolRegistry([tool]),
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    events = [
        event
        async for event in orchestrator.execute(
            [ToolCall(id="call_limited", name="limited_read", arguments={})],
            _tool_context(tmp_path),
        )
    ]

    result = events[-1].result
    assert result is not None
    assert result.metadata["truncated"] is True
    assert result.metadata["max_result_size_chars"] == 12
    assert result.content == "x" * 12 + "\n[Output truncated.]"


@pytest.mark.asyncio
async def test_orchestrator_emits_parallel_start_events_in_call_order(tmp_path):
    async def handler(args, context, call):
        await asyncio.sleep(0.01 if call.id == "call_1" else 0)
        return ToolResult(
            tool_call_id=call.id,
            tool_name="fast_read",
            content=call.id,
        )

    tool = build_tool(
        definition=ToolDefinition(
            name="fast_read",
            description="Fast read",
            input_schema={"type": "object", "properties": {}},
        ),
        handler=handler,
        is_concurrency_safe=lambda _args: True,
    )
    orchestrator = ToolOrchestrator(
        ToolRegistry([tool]),
        ToolRuntimeConfig.from_values(workspace_root=tmp_path, max_concurrency=2),
    )

    events = [
        event
        async for event in orchestrator.execute(
            [
                ToolCall(id="call_1", name="fast_read", arguments={}),
                ToolCall(id="call_2", name="fast_read", arguments={}),
            ],
            _tool_context(tmp_path),
        )
    ]

    assert [(event.event, event.call.id) for event in events[:2]] == [
        ("tool_call_started", "call_1"),
        ("tool_call_started", "call_2"),
    ]


@pytest.mark.asyncio
async def test_chat_completion_executes_tool_loop(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\nbeta\n", encoding="utf-8")
    repo = MemoryConversationRepository()
    llm = FakeToolCallingLLM()
    registry = ToolRegistry([create_read_file_tool()])
    config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=registry,
        tool_runtime_config=config,
    )

    response = await use_case.execute(ChatRequestDTO(message="Leia notes.txt", tools_enabled=True))

    conversation = await repo.get_by_id(response.conversation_id)
    assert conversation is not None
    assert response.content == "O arquivo contém alpha e beta."
    assert [message.role.value for message in conversation.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation.messages[1].tool_calls is not None
    assert conversation.messages[2].tool_call_id == "call_read"


@pytest.mark.asyncio
async def test_stream_uses_default_tool_iteration_limit_for_repeated_calls(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\nbeta\n", encoding="utf-8")
    repo = MemoryConversationRepository()
    llm = RepeatingStreamingToolCallingLLM()
    registry = ToolRegistry([create_read_file_tool()])
    config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=registry,
        tool_runtime_config=config,
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(message="Leia notes.txt", tools_enabled=True)
        )
    ]
    events = [chunk.metadata.get("event") for chunk in chunks if chunk.metadata]

    assert llm.calls == DEFAULT_MAX_TOOL_ITERATIONS
    assert events.count("tool_result") == DEFAULT_MAX_TOOL_ITERATIONS
    assert "tool_iterations_exceeded" in events
    assert not any(chunk.finish_reason == "tool_calls" for chunk in chunks)


@pytest.mark.asyncio
async def test_stream_keeps_vertex_tool_blocks_distinct_and_suppresses_internal_stop(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")
    repo = MemoryConversationRepository()
    llm = VertexLikeRepeatedToolIdLLM()
    registry = ToolRegistry([create_read_file_tool()])
    config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=registry,
        tool_runtime_config=config,
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(message="Leia a.txt e b.txt", tools_enabled=True)
        )
    ]

    tool_started_ids = [
        str(chunk.metadata["tool_call_id"])
        for chunk in chunks
        if chunk.metadata.get("event") == "tool_call_started"
    ]
    finish_reasons = [chunk.finish_reason for chunk in chunks if chunk.finish_reason]

    assert tool_started_ids[0] == "vertex-call-0"
    assert len(tool_started_ids) == 2
    assert len(set(tool_started_ids)) == 2
    assert finish_reasons == ["stop"]

    conversation = next(iter(repo.conversations.values()))
    persisted_tool_ids = [
        str(message.tool_call_id)
        for message in conversation.messages
        if message.role == Role.TOOL
    ]
    assert persisted_tool_ids == tool_started_ids


def test_chat_completion_tool_context_uses_requested_workspace(tmp_path):
    configured_root = tmp_path / "configured"
    selected_root = tmp_path / "selected"
    configured_root.mkdir()
    selected_root.mkdir()

    use_case = ChatCompletionUseCase(
        conversation_repo=MemoryConversationRepository(),
        llm_backend=FakeToolCallingLLM(),
        tool_registry=ToolRegistry([create_read_file_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(
            workspace_root=configured_root,
        ),
    )

    context = use_case._build_tool_context(
        ChatRequestDTO(
            message="Leia notes.txt",
            tool_context={
                "workspace_root": str(selected_root),
                "cwd": str(selected_root),
                "allowed_roots": [str(selected_root)],
            },
        ),
        Conversation(),
    )

    assert context.workspace_root == selected_root.resolve()
    assert context.cwd == selected_root.resolve()
    assert context.allowed_roots == (selected_root.resolve(),)


@pytest.mark.asyncio
async def test_stream_permission_block_does_not_emit_internal_tool_error(tmp_path):
    repo = MemoryConversationRepository()
    llm = FakeStreamingToolCallingLLM()
    registry = ToolRegistry([create_shell_tool()])
    config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=registry,
        tool_runtime_config=config,
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(
                message="Execute cat /etc/passwd",
                tools_enabled=True,
                max_tool_iterations=1,
            )
        )
    ]
    events = [chunk.metadata.get("event") for chunk in chunks if chunk.metadata]

    assert "permission_required" in events
    assert "tool_error" not in events
    assert "tool_iterations_exceeded" not in events
    assert not any(chunk.finish_reason == "tool_iterations_exceeded" for chunk in chunks)

    saved = next(chunk for chunk in chunks if chunk.metadata.get("event") == "conversation_saved")
    conversation = await repo.get_by_id(UUID(saved.metadata["conversation_id"]))
    assert conversation is not None
    pending = conversation.metadata["pending_tool_approval"]
    assert pending["status"] == "awaiting_approval"
    assert pending["tool_name"] == "shell"
    assert pending["approval_id"]
    assert pending["resume_request"]["message"] == "Execute cat /etc/passwd"
    assert pending["resume_request"]["provider"] == "llama"


@pytest.mark.asyncio
async def test_resume_after_tool_result_stream_does_not_add_synthetic_user(tmp_path):
    repo = MemoryConversationRepository()
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Execute echo ok"))
    conversation.add_message(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                {
                    "id": "call_shell",
                    "type": "function",
                    "function": {
                        "name": "shell",
                        "arguments": '{"command":"echo ok"}',
                    },
                }
            ],
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="ok\n",
            tool_call_id="call_shell",
            metadata={"tool_name": "shell", "status": "completed"},
        )
    )
    await repo.create(conversation)
    llm = ApprovalResumeLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_shell_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    chunks = [
        chunk
        async for chunk in use_case.resume_after_tool_result_stream(
            ChatRequestDTO(
                conversation_id=conversation.id,
                message="Execute echo ok",
                tools_enabled=True,
                tool_context={
                    "workspace_root": str(tmp_path),
                    "cwd": str(tmp_path),
                    "allowed_roots": [str(tmp_path)],
                },
            )
        )
    ]

    assert any(chunk.content == "final after tool" for chunk in chunks)
    assert "Continue after the approved tool result." not in json.dumps(
        llm.calls[0]["messages"]
    )
    stored = await repo.get_by_id(conversation.id)
    assert stored is not None
    user_messages = [message.content for message in stored.messages if message.role == Role.USER]
    assert user_messages == ["Execute echo ok"]
    assert stored.messages[-1].role == Role.ASSISTANT
    assert stored.messages[-1].content == "final after tool"


@pytest.mark.asyncio
async def test_stream_exit_plan_mode_requests_visual_approval(tmp_path):
    repo = MemoryConversationRepository()
    llm = ExitPlanStreamingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry([create_exit_plan_mode_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(
                message="Crie um plano",
                tools_enabled=True,
                max_tool_iterations=3,
            )
        )
    ]
    events = [chunk.metadata.get("event") for chunk in chunks if chunk.metadata]

    assert events.count("plan_approval_requested") == 1
    assert "tool_iterations_exceeded" not in events
    assert llm.calls == 1

    approval = next(chunk for chunk in chunks if chunk.metadata.get("event") == "plan_approval_requested")
    assert approval.metadata["plan_status"] == "awaiting_approval"
    assert "## Plan" in approval.metadata["plan_content"]

    saved = next(chunk for chunk in chunks if chunk.metadata.get("event") == "conversation_saved")
    conversation = await repo.get_by_id(UUID(saved.metadata["conversation_id"]))
    assert conversation is not None
    state = conversation.metadata["plan_mode"]
    assert state["active"] is True
    assert state["status"] == "awaiting_approval"
    assert state["approval_id"] == approval.metadata["approval_id"]


@pytest.mark.asyncio
async def test_stream_saved_event_does_not_replay_reasoning_payload():
    repo = MemoryConversationRepository()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=ReasoningStreamingLLM(),
    )

    chunks = [
        chunk
        async for chunk in use_case.execute_stream(
            ChatRequestDTO(message="Use long reasoning", tools_enabled=False)
        )
    ]

    saved = next(chunk for chunk in chunks if chunk.metadata.get("event") == "conversation_saved")
    assert "reasoning_content" not in saved.metadata

    conversation = await repo.get_by_id(UUID(saved.metadata["conversation_id"]))
    assert conversation is not None
    assert conversation.messages[-1].metadata["reasoning_content"] == "hidden analysis"
    assert conversation.messages[-1].content == "final answer"


@pytest.mark.asyncio
async def test_chat_uses_dynamic_prompt_and_user_context_reminder(tmp_path):
    (tmp_path / "persona.md").write_text("Project instruction from persona.", encoding="utf-8")
    repo = MemoryConversationRepository()
    llm = CapturingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        build_context_use_case=BuildContextUseCase(
            workspace_root=tmp_path,
            context_repository=InMemoryContextRepository(),
        ),
    )

    await use_case.execute(
        ChatRequestDTO(message="Analise a codebase", tools_enabled=False)
    )

    messages = llm.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "# Mode Overlay: Exploring" in messages[0]["content"]
    assert "# System Context" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "<system-reminder>" in messages[1]["content"]
    assert "Project instruction from persona." in messages[1]["content"]


@pytest.mark.asyncio
async def test_local_llama_auto_prompt_mode_skips_llm_prompt_analysis(tmp_path):
    llm = CapturingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=MemoryConversationRepository(),
        llm_backend=llm,
        prompt_context_analyzer=PromptContextAnalyzer(llm),
        build_context_use_case=BuildContextUseCase(
            workspace_root=tmp_path,
            context_repository=InMemoryContextRepository(),
        ),
    )

    await use_case.execute(
        ChatRequestDTO(
            message="Ola",
            provider="llama",
            model="local-model",
            prompt_mode="auto",
            tools_enabled=False,
        )
    )

    assert len(llm.calls) == 1
    assert "# Mode Overlay: Exploring" in llm.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_chat_custom_system_prompt_is_appended_to_dynamic_prompt(tmp_path):
    (tmp_path / "persona.md").write_text("Keep user context.", encoding="utf-8")
    llm = CapturingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=MemoryConversationRepository(),
        llm_backend=llm,
        build_context_use_case=BuildContextUseCase(
            workspace_root=tmp_path,
            context_repository=InMemoryContextRepository(),
        ),
    )

    await use_case.execute(
        ChatRequestDTO(
            message="Implemente algo",
            system_prompt="CUSTOM SYSTEM",
            prompt_mode="writing",
            tools_enabled=False,
        )
    )

    messages = llm.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "# Mode Overlay: Writing" in messages[0]["content"]
    assert "# Custom System Instructions" in messages[0]["content"]
    assert "CUSTOM SYSTEM" in messages[0]["content"]
    assert "Keep user context." in messages[1]["content"]


@pytest.mark.asyncio
async def test_prompt_preview_returns_final_prompt_metrics_without_completion(tmp_path):
    llm = CapturingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=MemoryConversationRepository(),
        llm_backend=llm,
        tool_registry=ToolRegistry([create_read_file_tool(), create_todo_write_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
        build_context_use_case=BuildContextUseCase(
            workspace_root=tmp_path,
            context_repository=InMemoryContextRepository(),
        ),
    )

    preview = await use_case.preview_prompt(
        ChatRequestDTO(
            message="Implemente e valide a mudança",
            provider="nvidia",
            model="hosted-model",
            prompt_mode="writing",
            tools_enabled=True,
            allowed_tools=["Read", "TodoWrite"],
            tool_context={"workspace_root": str(tmp_path)},
        )
    )

    assert llm.calls == []
    assert preview["system_prompt"]
    assert preview["line_count"] == len(preview["system_prompt"].splitlines())
    assert preview["char_count"] == len(preview["system_prompt"])
    assert preview["estimated_tokens"] > 0
    assert preview["provider_data_boundary"] == "hosted_model_external_provider_local_tools"
    assert preview["mode"] == "writing"
    assert "todo_write_policy" in preview["sections"]
    assert "parallel_tool_use" in preview["sections"]
    assert "todo" in preview["surfaces"]
    assert "parallel_tool_use" in preview["surfaces"]
    assert "# TodoWrite Policy" in preview["system_prompt"]
    assert "# Parallel Tool Use" in preview["system_prompt"]


@pytest.mark.asyncio
async def test_chat_prompt_includes_deferred_tool_prompts(tmp_path):
    llm = CapturingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=MemoryConversationRepository(),
        llm_backend=llm,
        tool_registry=ToolRegistry([create_skill_tool()]),
        tool_runtime_config=ToolRuntimeConfig.from_values(workspace_root=tmp_path),
        build_context_use_case=BuildContextUseCase(
            workspace_root=tmp_path,
            context_repository=InMemoryContextRepository(),
        ),
    )

    await use_case.execute(ChatRequestDTO(message="Analise skills disponíveis", tools_enabled=True))

    messages = llm.calls[0]["messages"]
    assert "## Skill" in messages[0]["content"]
    assert "Load a SKILL.md" in messages[0]["content"]
    assert "may be deferred from the initial callable schema" in messages[0]["content"]
    assert "You have access to the following tools: Skill" not in messages[0]["content"]
    assert not llm.calls[0]["kwargs"]["tools"]


@pytest.mark.asyncio
async def test_chat_compacts_history_when_context_threshold_is_exceeded():
    repo = MemoryConversationRepository()
    conversation = await repo.create(Conversation())
    for index in range(12):
        conversation.add_message(
            Message(role=Role.USER, content=f"old message {index} " + ("x" * 2_000))
        )
    await repo.update(conversation)
    llm = CompactingLLM()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        context_window_tokens=4_096,
        default_output_tokens=512,
    )

    await use_case.execute(
        ChatRequestDTO(
            conversation_id=conversation.id,
            message="Continue",
            tools_enabled=False,
            max_tokens=512,
        )
    )

    saved = await repo.get_by_id(conversation.id)
    assert saved is not None
    assert saved.metadata["context_compaction"]["compacted"] is True
    assert saved.messages[0].metadata["context_compaction"] is True
    assert "Summary of old work" in saved.messages[0].content


def test_llama_payload_and_stream_tool_call_parsing():
    adapter = LlamaCppAdapter()
    payload = adapter._build_payload(
        [{"role": "user", "content": "hi"}],
        0.7,
        -1,
        False,
        {},
        tools=[{"type": "function", "function": {"name": "read_file"}}],
        tool_choice="auto",
    )
    assert payload["tools"]
    assert payload["tool_choice"] == "auto"

    accumulator = {}
    chunk = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        accumulator,
    )
    assert chunk.is_empty
    chunk = adapter._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": 'notes.txt"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        accumulator,
    )
    assert chunk.tool_calls is not None
    call = chunk.tool_calls[0]
    assert call["id"] == "call_1"
    assert json.loads(call["function"]["arguments"]) == {"path": "notes.txt"}


def _tool_context(root):
    return ToolUseContext(
        conversation_id="test",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        limits={
            "read_max_bytes": 128_000,
            "read_default_limit": 200,
            "read_max_lines": 1_000,
            "search_timeout_ms": 15_000,
            "shell_timeout_ms": 10_000,
            "result_max_chars": 20_000,
        },
    )


class MemoryConversationRepository(ConversationRepository):
    def __init__(self):
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


class FakeToolCallingLLM(LLMBackendRepository):
    def __init__(self):
        self.calls = 0

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        self.calls += 1
        if self.calls == 1:
            return InferenceResult(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"notes.txt"}',
                        },
                    }
                ],
            )
        return InferenceResult(content="O arquivo contém alpha e beta.")

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(content="unused")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class CapturingLLM(LLMBackendRepository):
    def __init__(self):
        self.calls: list[dict] = []

    async def chat_completion(self, messages, *args, **kwargs) -> InferenceResult:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return InferenceResult(content="ok")

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(content="ok")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class ApprovalResumeLLM(CapturingLLM):
    async def chat_completion_stream(self, messages, *args, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        yield StreamChunk(content="final after tool")
        yield StreamChunk(finish_reason="stop")


class CompactingLLM(CapturingLLM):
    async def chat_completion(self, messages, *args, **kwargs) -> InferenceResult:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if messages and messages[0].get("role") == "system" and "Summarize" in messages[0].get("content", ""):
            return InferenceResult(content="Summary of old work")
        return InferenceResult(content="final")


class FakeStreamingToolCallingLLM(LLMBackendRepository):
    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        return InferenceResult(content="unused")

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(
            tool_calls=[
                {
                    "id": "call_shell",
                    "type": "function",
                    "function": {
                        "name": "shell",
                        "arguments": '{"command":"cat /etc/passwd"}',
                    },
                }
            ],
            finish_reason="tool_calls",
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class ExitPlanStreamingLLM(LLMBackendRepository):
    def __init__(self):
        self.calls = 0

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        return InferenceResult(content="unused")

    async def chat_completion_stream(self, *args, **kwargs):
        self.calls += 1
        yield StreamChunk(
            tool_calls=[
                {
                    "id": "call_exit_plan",
                    "type": "function",
                    "function": {
                        "name": "ExitPlanMode",
                        "arguments": '{"plan":"## Plan\\n\\n1. Update backend."}',
                    },
                }
            ],
            finish_reason="tool_calls",
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class RepeatingStreamingToolCallingLLM(LLMBackendRepository):
    def __init__(self):
        self.calls = 0

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        return InferenceResult(content="unused")

    async def chat_completion_stream(self, *args, **kwargs):
        self.calls += 1
        yield StreamChunk(
            tool_calls=[
                {
                    "id": f"call_read_{self.calls}",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"notes.txt"}',
                    },
                }
            ],
            finish_reason="tool_calls",
        )

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class VertexLikeRepeatedToolIdLLM(LLMBackendRepository):
    def __init__(self):
        self.calls = 0

    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        return InferenceResult(content="unused")

    async def chat_completion_stream(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield StreamChunk(reasoning_content="think before first tool", is_thinking=True)
            yield StreamChunk(
                tool_calls=[
                    {
                        "id": "vertex-call-0",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"a.txt"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
            yield StreamChunk(finish_reason="stop", usage={"thoughtsTokenCount": 4})
            return
        if self.calls == 2:
            yield StreamChunk(
                tool_calls=[
                    {
                        "id": "vertex-call-0",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"b.txt"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
            yield StreamChunk(finish_reason="stop", usage={"thoughtsTokenCount": 2})
            return
        yield StreamChunk(content="final answer")
        yield StreamChunk(finish_reason="stop")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}


class ReasoningStreamingLLM(LLMBackendRepository):
    async def chat_completion(self, *args, **kwargs) -> InferenceResult:
        return InferenceResult(content="unused")

    async def chat_completion_stream(self, *args, **kwargs):
        yield StreamChunk(reasoning_content="hidden ", is_thinking=True)
        yield StreamChunk(reasoning_content="analysis", is_thinking=True)
        yield StreamChunk(content="final answer")
        yield StreamChunk(finish_reason="stop")

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def get_model_info(self) -> dict:
        return {}
