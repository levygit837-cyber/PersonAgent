from __future__ import annotations

import os
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from uuid import UUID

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
from personagent.infrastructure.tools import create_browser_tools

pytestmark = pytest.mark.skipif(
    os.getenv("NVIDIA_LIVE_TESTS") != "1" or not os.getenv("NVIDIA_API_KEY"),
    reason="set NVIDIA_LIVE_TESTS=1 and NVIDIA_API_KEY to run GPT OSS browser-control chat tests",
)


@pytest.mark.asyncio
async def test_gpt_oss_120b_uses_explicit_browser_control_tools(tmp_path):
    model = "openai/gpt-oss-120b"
    explicit_models = {
        item.strip()
        for item in os.getenv("NVIDIA_LIVE_MODEL_IDS", model).split(",")
        if item.strip()
    }
    if model not in explicit_models:
        pytest.skip(f"set NVIDIA_LIVE_MODEL_IDS={model} to run this validation")

    server, url = _serve_local_browser_control_page()
    worker = LightPandaBrowserWorker(
        cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
    )
    llm = NvidiaNimAdapter(
        api_key=os.environ["NVIDIA_API_KEY"],
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "180")),
        stream_read_timeout=float(os.getenv("NVIDIA_STREAM_READ_TIMEOUT_SECONDS", "0") or 0),
        default_model=model,
        default_max_tokens=4096,
    )
    repo = MemoryConversationRepository()
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=llm,
        tool_registry=ToolRegistry(create_browser_tools(worker)),
        tool_runtime_config=ToolRuntimeConfig.from_values(
            workspace_root=tmp_path,
            max_tool_iterations=12,
            web_blocked_domains=(),
            web_allow_private_hosts=True,
        ),
    )

    try:
        response = await use_case.execute(
            ChatRequestDTO(
                message=(
                    "You must use the explicit browser-control tools in this exact sequence against "
                    f"{url}: BrowserOpen, BrowserGetElementMap, BrowserType to fill the Name input "
                    "with Ada, BrowserClick on Save, BrowserScript to read window.clicked and the input "
                    "value, BrowserReadConsole, BrowserScreenshot, BrowserCloseTab. Then summarize the "
                    "observed value and console log in one short sentence."
                ),
                provider="nvidia",
                model=model,
                tools_enabled=True,
                allowed_tools=[
                    "BrowserOpen",
                    "BrowserGetElementMap",
                    "BrowserType",
                    "BrowserClick",
                    "BrowserScript",
                    "BrowserReadConsole",
                    "BrowserScreenshot",
                    "BrowserCloseTab",
                ],
                max_tool_iterations=12,
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
        assert _contains_ordered_subsequence(
            tool_names,
            [
                "BrowserOpen",
                "BrowserGetElementMap",
                "BrowserType",
                "BrowserClick",
                "BrowserScript",
                "BrowserReadConsole",
                "BrowserScreenshot",
                "BrowserCloseTab",
            ],
        )
        assert response.content.strip()
    finally:
        await worker.close()
        close = getattr(llm, "close", None)
        if close is not None:
            await close()
        server.shutdown()
        server.server_close()


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


def _serve_local_browser_control_page() -> tuple[socketserver.TCPServer, str]:
    html = b"""<!doctype html>
<html>
  <head><title>GPT OSS Browser Control Fixture</title></head>
  <body>
    <label>Name <input id="name" aria-label="Name"></label>
    <button id="save" onclick="window.clicked = true; console.log('clicked:' + document.querySelector('#name').value);">Save</button>
    <script>window.clicked = false;</script>
  </body>
</html>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, _format, *args):
            return None

    server = socketserver.TCPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _host, port = server.server_address
    host = _lightpanda_fixture_host()
    return server, f"http://{host}:{port}/"


def _contains_ordered_subsequence(values: list[str | None], expected: list[str]) -> bool:
    index = 0
    for value in values:
        if index < len(expected) and value == expected[index]:
            index += 1
    return index == len(expected)


def _lightpanda_fixture_host() -> str:
    explicit = os.getenv("LIGHTPANDA_FIXTURE_HOST")
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                "personagent_personagent-network",
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        gateway = result.stdout.strip()
        if result.returncode == 0 and gateway:
            return gateway
    except Exception:
        pass
    return "127.0.0.1"
