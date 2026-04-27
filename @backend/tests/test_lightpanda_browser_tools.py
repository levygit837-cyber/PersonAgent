from __future__ import annotations

import json
from pathlib import Path

import pytest

from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolUseContext
from personagent.infrastructure.browser import (
    LightPandaBrowserWorker,
    normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.tools import create_browser_tools
from personagent.interfaces.config.di_container import DIContainer


def test_normalize_lightpanda_cdp_endpoint_prefers_json_version_websocket():
    assert (
        normalize_lightpanda_cdp_endpoint(
            "http://127.0.0.1:9222/",
            {"webSocketDebuggerUrl": "ws://0.0.0.0:9222/devtools/browser/abc"},
        )
        == "ws://127.0.0.1:9222/devtools/browser/abc"
    )
    assert normalize_lightpanda_cdp_endpoint("http://127.0.0.1:9222/") == "ws://127.0.0.1:9222"
    assert normalize_lightpanda_cdp_endpoint("ws://127.0.0.1:9222") == "ws://127.0.0.1:9222"


def test_lightpanda_search_url_defaults_to_yahoo_parameters():
    worker = LightPandaBrowserWorker()

    url = worker.search_url("site:example.com Example Domain", max_results=7)

    assert worker.search_provider == "yahoo"
    assert url == (
        "https://search.yahoo.com/search?"
        "p=site%3Aexample.com+Example+Domain&pz=7"
    )


def test_lightpanda_search_url_adds_stable_bing_parameters():
    worker = LightPandaBrowserWorker(search_base_url="https://www.bing.com/search")

    url = worker.search_url("site:example.com Example Domain", max_results=7)

    assert worker.search_provider == "bing"
    assert url == (
        "https://www.bing.com/search?"
        "q=site%3Aexample.com+Example+Domain&setlang=en-US&cc=US&count=7"
    )


def test_lightpanda_search_url_adds_stable_google_parameters():
    worker = LightPandaBrowserWorker(search_base_url="https://www.google.com/search")

    url = worker.search_url("site:example.com Example Domain", max_results=7)

    assert worker.search_provider == "google"
    assert url == (
        "https://www.google.com/search?"
        "q=site%3Aexample.com+Example+Domain&hl=en&gl=us&pws=0&num=7"
    )


@pytest.mark.asyncio
async def test_lightpanda_worker_uses_connector_after_reset():
    endpoints: list[str] = []

    async def connector(endpoint: str):
        endpoints.append(endpoint)
        return FakeBrowser()

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    first = await worker._ensure_browser()
    await worker._reset_browser()
    second = await worker._ensure_browser()

    assert first is not second
    assert endpoints == ["ws://127.0.0.1:9222", "ws://127.0.0.1:9222"]


@pytest.mark.asyncio
async def test_browser_tools_preserve_state_by_conversation(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path, conversation_id="conversation-a")

    search_call = ToolCall(
        id="call_search",
        name="BrowserSearch",
        arguments={"query": "site:example.com Example Domain", "max_results": 1},
    )
    assert await tools["BrowserSearch"].validate_input(search_call.arguments, context) is None
    search_result = await tools["BrowserSearch"].call(search_call.arguments, context, search_call)
    assert search_result.status == ToolExecutionStatus.COMPLETED
    assert json.loads(search_result.content)["results"][0]["url"] == "https://example.com/"

    open_call = ToolCall(
        id="call_open",
        name="BrowserOpen",
        arguments={"result_index": 1},
    )
    open_result = await tools["BrowserOpen"].call(open_call.arguments, context, open_call)
    assert json.loads(open_result.content)["final_url"] == "https://example.com/"

    content_call = ToolCall(id="call_content", name="BrowserExtractContent", arguments={})
    content_result = await tools["BrowserExtractContent"].call(
        content_call.arguments,
        context,
        content_call,
    )
    content_data = json.loads(content_result.content)
    assert "Example Domain" in content_data["content"]
    assert content_data["cache_key"]
    assert content_data["chunk_count"] == 1

    chunk_call = ToolCall(
        id="call_chunk",
        name="BrowserReadContentChunk",
        arguments={"cache_key": content_data["cache_key"], "chunk_index": 1},
    )
    chunk_result = await tools["BrowserReadContentChunk"].call(
        chunk_call.arguments,
        context,
        chunk_call,
    )
    chunk_data = json.loads(chunk_result.content)
    assert chunk_data["total_chunks"] == 1
    assert "Example Domain" in chunk_data["chunks"][0]["content"]

    html_call = ToolCall(id="call_html", name="BrowserGetHtml", arguments={})
    html_result = await tools["BrowserGetHtml"].call(html_call.arguments, context, html_call)
    assert "<h1>Example Domain</h1>" in json.loads(html_result.content)["html"]
    assert worker.sessions["conversation-a"]["opened"] == "https://example.com/"


@pytest.mark.asyncio
async def test_browser_tools_block_private_urls(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path)

    denied = await tools["BrowserOpen"].validate_input({"url": "http://127.0.0.1:9222"}, context)

    assert denied is not None
    assert denied.allowed is False


def test_tool_registry_exposes_browser_tools():
    registry = DIContainer().get_tool_registry()
    names = {tool.definition.name for tool in registry.list_enabled()}

    assert {
        "BrowserSearch",
        "BrowserOpen",
        "BrowserExtractContent",
        "BrowserReadContentChunk",
        "BrowserGetHtml",
    } <= names


def _tool_context(root: Path, *, conversation_id: str = "test") -> ToolUseContext:
    return ToolUseContext(
        conversation_id=conversation_id,
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        limits={
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": ("localhost", "127.0.0.1", "0.0.0.0"),
        },
    )


class FakeBrowserWorker:
    def __init__(self) -> None:
        self.search_base_url = "https://search.yahoo.com/search"
        self.search_provider_label = "Yahoo"
        self.sessions: dict[str, dict] = {}

    def search_url(self, query: str) -> str:
        return f"https://search.yahoo.com/search?p={query.replace(' ', '+')}"

    async def search(self, *, conversation_id: str, query: str, max_results: int):
        session = self.sessions.setdefault(conversation_id, {})
        session["results"] = [{"index": 1, "title": "Example Domain", "url": "https://example.com/", "snippet": "Example"}]
        return {
            "type": "browser_search",
            "query": query,
            "search_url": self.search_url(query),
            "results": session["results"][:max_results],
        }

    async def open(self, *, conversation_id: str, url=None, result_index=None):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session["results"][int(result_index) - 1]["url"]
        session["opened"] = target
        return {
            "type": "browser_open",
            "url": target,
            "final_url": target,
            "title": "Example Domain",
        }

    async def extract_content(self, *, conversation_id: str, url=None, max_chars: int, include_links: bool):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session.get("opened") or "https://example.com/"
        session["opened"] = target
        return {
            "type": "browser_extract_content",
            "url": target,
            "title": "Example Domain",
            "content": "Example Domain\nThis domain is for use in illustrative examples."[:max_chars],
            "links": [{"url": "https://www.iana.org/domains/example", "text": "More information"}] if include_links else [],
            "truncated": False,
        }

    async def get_html(self, *, conversation_id: str, url=None, max_chars: int):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session.get("opened") or "https://example.com/"
        session["opened"] = target
        html = "<html><body><h1>Example Domain</h1></body></html>"
        return {
            "type": "browser_get_html",
            "url": target,
            "title": "Example Domain",
            "html": html[:max_chars],
            "truncated": False,
        }


class FakeBrowser:
    async def close(self):
        return None
