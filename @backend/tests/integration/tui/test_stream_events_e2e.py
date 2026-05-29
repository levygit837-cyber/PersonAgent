"""E2E-style TUI stream rendering tests over real HTTP/SSE."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from rich.console import Console
from starlette.responses import StreamingResponse

from personagent.adapters.tui.app import ChatApp
from personagent.adapters.tui.widgets import InputBar
from personagent.adapters.tui.widgets.tool_call_group import (
    MemoryRecallBlock,
    ToolCallGroup,
)
from personagent.domain.token_counting import token_animation_step


@pytest.mark.asyncio
async def test_tui_renders_tools_mcp_skills_memory_tokens_and_preview(
    unused_tcp_port: int,
) -> None:
    long_output = "\n".join(f"line {index}" for index in range(1, 101))
    events: list[dict[str, Any]] = [
        {"event": "status", "status": "streaming"},
        {"event": "memory_recall_started", "memory_status": "running"},
        {
            "event": "memory_recall_finished",
            "memory_status": "completed",
            "memory_count": 2,
            "memory_trace": {
                "classic": [{"path": "memory/project.md", "snippet": "classic"}],
                "operational": [{"summary": "recent tool evidence"}],
                "summary": {
                    "total_used": 2,
                    "classic_count": 1,
                    "rag_count": 1,
                    "omitted_count": 0,
                    "budget_used": 20,
                    "budget_tokens": 100,
                    "latency_ms": 4,
                },
            },
        },
        {"reasoning_content": "thinking through tool use", "is_thinking": True},
        {"content": "I will inspect the workspace."},
        {
            "event": "tool_call_started",
            "tool_call_id": "call_skill",
            "tool_name": "Skill",
            "tool_status": "running",
            "tool_input": {"name": "writer"},
        },
        {
            "event": "tool_result",
            "tool_call_id": "call_skill",
            "tool_name": "Skill",
            "tool_status": "completed",
            "tool_input": {"name": "writer"},
            "tool_result": '{"type":"skill","name":"writer"}',
            "tool_data": {"type": "skill", "name": "writer", "content": "Skill body"},
        },
        {
            "event": "tool_call_started",
            "tool_call_id": "call_mcp",
            "tool_name": "mcp__fake__lookup",
            "tool_status": "running",
            "tool_input": {"query": "alpha"},
        },
        {
            "event": "tool_result",
            "tool_call_id": "call_mcp",
            "tool_name": "mcp__fake__lookup",
            "tool_status": "completed",
            "tool_input": {"query": "alpha"},
            "tool_result": '{"ok":true}',
            "tool_data": {"type": "mcp_tool_result", "server": "fake", "tool": "lookup"},
        },
        {
            "event": "tool_call_started",
            "tool_call_id": "call_read",
            "tool_name": "Read",
            "tool_status": "running",
            "tool_input": {"path": "src/big.txt"},
        },
        {
            "event": "tool_result",
            "tool_call_id": "call_read",
            "tool_name": "Read",
            "tool_status": "completed",
            "tool_input": {"path": "src/big.txt"},
            "tool_result": long_output,
            "tool_data": {"type": "file_read", "path": "src/big.txt", "content": long_output},
        },
        {"content": "Done.", "finish_reason": "stop"},
        {"event": "conversation_saved", "conversation_id": "conv-e2e", "title": "E2E"},
    ]

    async with _sse_backend(events, unused_tcp_port) as base_url:
        app = ChatApp(base_url=base_url)
        async with app.run_test(size=(120, 40)) as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "exercise stream UI"
            await pilot.press("enter")
            await _wait_for(lambda: not app.is_streaming)

            memory_blocks = list(app.query(MemoryRecallBlock))
            assert len(memory_blocks) == 1
            assert memory_blocks[0].state.count == 2
            assert "Recalled 2 memories" in _render_text(memory_blocks[0])

            groups = list(app.query(ToolCallGroup))
            assert len(groups) == 1
            assert [call.name for call in groups[0].calls] == [
                "Skill",
                "mcp__fake__lookup",
                "Read",
            ]

            await _wait_for(lambda: groups[0]._displayed_tokens > 0)
            rendered = _render_text(groups[0])
            assert "Completed 3 tool calls" in rendered
            assert "Invoked writer" in rendered
            assert "MCP fake/lookup" in rendered
            assert "Read src/big.txt" in rendered
            assert "(+90 lines)" in rendered
            assert "tok" in rendered

    assert token_animation_step(0, 50) == 1
    assert token_animation_step(0, 500) == 10
    assert token_animation_step(0, 5_000) == 100


@pytest.mark.asyncio
async def test_tui_groups_registered_tool_surface_in_one_sequential_phase(
    unused_tcp_port: int,
) -> None:
    tool_cases: list[tuple[str, dict[str, Any]]] = [
        ("Read", {"path": "src/app.py"}),
        ("Write", {"path": "src/app.py", "content": "updated"}),
        ("Edit", {"path": "src/app.py", "old_string": "a", "new_string": "b"}),
        ("Glob", {"pattern": "**/*.py"}),
        ("Grep", {"pattern": "PersonAgent", "path": "src"}),
        ("shell", {"command": "pytest tests/unit/tui -q"}),
        ("WebFetch", {"url": "https://example.com"}),
        ("WebSearch", {"query": "personagent"}),
        ("BrowserSearch", {"query": "docs"}),
        ("BrowserOpen", {"url": "https://example.com"}),
        ("BrowserListTabs", {}),
        ("BrowserExtractContent", {"url": "https://example.com"}),
        ("BrowserReadContentChunk", {"cache_key": "page", "chunk_index": 1}),
        ("BrowserGetHtml", {"url": "https://example.com"}),
        ("BrowserGetElementMap", {"page_id": "page-1"}),
        ("BrowserClick", {"node_id": "button-1"}),
        ("BrowserType", {"node_id": "input-1", "text": "hello"}),
        ("BrowserScreenshot", {"page_id": "page-1"}),
        ("BrowserCloseTab", {"page_id": "page-1"}),
        ("BrowserReadConsole", {"page_id": "page-1"}),
        ("BrowserScript", {"script": "document.title"}),
        ("BrowserScroll", {"delta_y": 500}),
        ("BrowserReload", {"page_id": "page-1"}),
        ("BrowserHistory", {"page_id": "page-1"}),
        ("BrowserSwitchTab", {"page_id": "page-1"}),
        ("BrowserWait", {"ms": 250}),
        ("BrowserAct", {"action": "click"}),
        ("ListMcpResourcesTool", {"server": "fake"}),
        ("ReadMcpResourceTool", {"server": "fake", "uri": "memory://one"}),
        ("McpAuth", {"server": "fake"}),
        ("mcp__fake__lookup", {"query": "alpha"}),
        ("Config", {"key": "permission_mode"}),
        ("EnterPlanMode", {"reason": "plan"}),
        ("ExitPlanMode", {"reason": "done"}),
        ("EnterWorktree", {"branch": "feature/tui"}),
        ("ExitWorktree", {}),
        ("AskUserQuestion", {"question": "Proceed?"}),
        ("SendUserMessage", {"message": "Need input"}),
        ("Agent", {"message": "research"}),
        ("SendMessage", {"message": "handoff"}),
        ("TodoWrite", {"todos": [{"content": "ship", "status": "pending"}]}),
        ("Task", {"title": "Implement TUI"}),
        ("TaskCreate", {"title": "Implement TUI"}),
        ("TaskGet", {"task_id": "task-1"}),
        ("TaskUpdate", {"task_id": "task-1"}),
        ("TaskList", {}),
        ("TaskOutput", {"task_id": "task-1"}),
        ("TaskStop", {"task_id": "task-1"}),
        ("ToolSearch", {"query": "browser"}),
        ("Skill", {"name": "writer"}),
        ("StructuredOutput", {"schema": "summary"}),
    ]
    events: list[dict[str, Any]] = [{"event": "status", "status": "streaming"}]
    for index, (name, args) in enumerate(tool_cases):
        call_id = f"call_{index}"
        events.append(
            {
                "event": "tool_call_started",
                "tool_call_id": call_id,
                "tool_name": name,
                "tool_status": "running",
                "tool_input": args,
            }
        )
        events.append(
            {
                "event": "tool_result",
                "tool_call_id": call_id,
                "tool_name": name,
                "tool_status": "completed",
                "tool_input": args,
                "tool_result": "{}",
                "tool_data": args,
            }
        )
    events.extend(
        [
            {"content": "All tools rendered.", "finish_reason": "stop"},
            {"event": "conversation_saved", "conversation_id": "conv-tools", "title": "Tools"},
        ]
    )

    async with _sse_backend(events, unused_tcp_port) as base_url:
        app = ChatApp(base_url=base_url)
        async with app.run_test(size=(160, 50)) as pilot:
            input_bar = app.query_one("#input-bar", InputBar)
            input_bar.text = "map every tool"
            await pilot.press("enter")
            await _wait_for(lambda: not app.is_streaming, timeout=4.0)

            groups = list(app.query(ToolCallGroup))
            assert len(groups) == 1
            assert [call.name for call in groups[0].calls] == [name for name, _ in tool_cases]

            rendered = _render_text(groups[0])
            assert f"Completed {len(tool_cases)} tool calls" in rendered
            assert "pytest tests/unit/tui -q" in rendered
            assert "BrowserOpen https://example.com" in rendered
            assert "MCP fake/lookup" in rendered
            assert "TodoWrite 1 items" in rendered
            assert "TaskCreate Implement TUI" in rendered
            assert "Invoked writer" in rendered


def _render_text(widget: Any) -> str:
    console = Console(width=160, record=True, file=io.StringIO())
    renderable = widget._build_renderable() if hasattr(widget, "_build_renderable") else widget.render()
    console.print(renderable)
    return console.export_text()


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    assert predicate()


class _sse_backend:
    def __init__(self, events: list[dict[str, Any]], port: int) -> None:
        self.events = events
        self.base_url = f"http://127.0.0.1:{port}"
        self.server: uvicorn.Server | None = None
        self.task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> str:
        app = FastAPI()

        @app.get("/health")
        async def health() -> dict[str, bool]:
            return {"ok": True}

        @app.post("/chat/completions/stream")
        async def stream() -> StreamingResponse:
            async def body() -> AsyncIterator[str]:
                for event in self.events:
                    yield f"data: {json.dumps(event)}\n\n"
                    await asyncio.sleep(0.005)
                yield "data: [DONE]\n\n"

            return StreamingResponse(body(), media_type="text/event-stream")

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=int(self.base_url.rsplit(":", 1)[1]),
            lifespan="off",
            log_level="warning",
        )
        self.server = uvicorn.Server(config)
        self.task = asyncio.create_task(self.server.serve())
        async with httpx.AsyncClient(timeout=1.0) as client:
            await _wait_for_health(client, self.base_url)
        return self.base_url

    async def __aexit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None:
            await self.task


async def _wait_for_health(client: httpx.AsyncClient, base_url: str) -> None:
    async def ready() -> bool:
        try:
            response = await client.get(f"{base_url}/health")
            return response.is_success
        except Exception:
            return False

    deadline = asyncio.get_running_loop().time() + 3.0
    while asyncio.get_running_loop().time() < deadline:
        if await ready():
            return
        await asyncio.sleep(0.02)
    raise RuntimeError("TUI E2E backend did not start.")
