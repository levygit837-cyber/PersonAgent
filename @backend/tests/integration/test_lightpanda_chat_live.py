from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.tools import ToolCall, ToolUseContext
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.llm.llama_cpp_adapter import LlamaCppAdapter
from personagent.infrastructure.tools import create_browser_tools

pytestmark = pytest.mark.skipif(
    os.getenv("LIGHTPANDA_CHAT_LIVE_TESTS") != "1",
    reason="set LIGHTPANDA_CHAT_LIVE_TESTS=1 to run real chat+browser tests",
)


@pytest.mark.asyncio
async def test_chat_agent_uses_lightpanda_browser_tools(tmp_path):
    worker = LightPandaBrowserWorker(
        cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
    )
    repo = MemoryConversationRepository()
    tool_registry = ToolRegistry(create_browser_tools(worker))
    tool_runtime_config = ToolRuntimeConfig.from_values(workspace_root=tmp_path)
    llm = LlamaCppAdapter(
        base_url=os.getenv("LLAMA_SERVER_URL", "http://localhost:8080/v1"),
        api_key=os.getenv("LLAMA_SERVER_API_KEY", "local"),
        timeout=180,
        default_max_tokens=4096,
    )
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=tool_registry,
        tool_runtime_config=tool_runtime_config,
    )

    try:
        await _xfail_if_search_provider_blocks(tool_registry, tool_runtime_config, tmp_path)
        response = await use_case.execute(
            ChatRequestDTO(
                message=(
                    "Use as ferramentas de browser, nesta ordem: BrowserSearch para "
                    "`IANA example domain`, BrowserOpen no resultado 1, "
                    "BrowserExtractContent e BrowserGetHtml. Depois responda em uma frase "
                    "o que a página diz."
                ),
                tools_enabled=True,
                allowed_tools=[
                    "BrowserSearch",
                    "BrowserOpen",
                    "BrowserExtractContent",
                    "BrowserGetHtml",
                ],
                max_tool_iterations=6,
                max_tokens=4096,
            )
        )
        conversation = await repo.get_by_id(response.conversation_id)
        assert conversation is not None
        tool_names = [
            message.metadata.get("tool_name")
            for message in conversation.messages
            if message.role.value == "tool"
        ]
        assert {"BrowserSearch", "BrowserOpen", "BrowserExtractContent", "BrowserGetHtml"} <= set(
            tool_names
        )
        assert response.content.strip()
    finally:
        await worker.close()
        close = getattr(llm, "close", None)
        if close is not None:
            await close()


async def _xfail_if_search_provider_blocks(
    registry: ToolRegistry,
    config: ToolRuntimeConfig,
    root: Path,
) -> None:
    context = ToolUseContext(
        conversation_id="lightpanda-chat-preflight",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        limits={
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": ("localhost", "127.0.0.1", "0.0.0.0"),
        },
    )
    events = [
        event
        async for event in ToolOrchestrator(registry, config).execute(
            [
                ToolCall(
                    id="call_search_preflight",
                    name="BrowserSearch",
                    arguments={"query": "IANA example domain", "max_results": 1},
                )
            ],
            context,
        )
    ]
    result = events[-1].result
    assert result is not None
    if result.is_error and "blocked this browser session" in result.content:
        pytest.xfail(result.content)
    assert not result.is_error, result.content
    assert json.loads(result.content)["results"]


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
