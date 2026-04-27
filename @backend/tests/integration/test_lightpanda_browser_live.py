from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolUseContext
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools import create_browser_tools

pytestmark = pytest.mark.skipif(
    os.getenv("LIGHTPANDA_LIVE_TESTS") != "1",
    reason="set LIGHTPANDA_LIVE_TESTS=1 to run real LightPanda browser tests",
)


@pytest.mark.asyncio
async def test_lightpanda_direct_page_tools_live_flow(tmp_path):
    worker = LightPandaBrowserWorker(
        cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
    )
    registry = ToolRegistry(create_browser_tools(worker))
    orchestrator = ToolOrchestrator(
        registry,
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )
    context = _context(tmp_path)

    try:
        opened = await _run(
            orchestrator,
            context,
            ToolCall(
                id="call_open_direct",
                name="BrowserOpen",
                arguments={"url": "https://example.com/"},
            ),
        )
        assert opened["final_url"] == "https://example.com/"

        content = await _run(
            orchestrator,
            context,
            ToolCall(
                id="call_content_direct",
                name="BrowserExtractContent",
                arguments={"max_chars": 5000, "include_links": True},
            ),
        )
        assert "Example Domain" in content["content"], content
        assert content["extraction_method"] in {
            "lightpanda_markdown",
            "readable_dom_text",
        }, content

        html = await _run(
            orchestrator,
            context,
            ToolCall(id="call_html_direct", name="BrowserGetHtml", arguments={"max_chars": 5000}),
        )
        assert "<h1>Example Domain</h1>" in html["html"], html
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_lightpanda_search_tools_live_flow(tmp_path):
    worker = LightPandaBrowserWorker(
        cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
    )
    registry = ToolRegistry(create_browser_tools(worker))
    orchestrator = ToolOrchestrator(
        registry,
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )
    context = _context(tmp_path)

    try:
        search = await _run(
            orchestrator,
            context,
                ToolCall(
                    id="call_search",
                    name="BrowserSearch",
                    arguments={"query": "IANA example domain", "max_results": 3},
                ),
            )
        assert search["results"], search

        opened = await _run(
            orchestrator,
            context,
            ToolCall(id="call_open", name="BrowserOpen", arguments={"result_index": 1}),
        )
        assert opened["final_url"].startswith("http"), opened

        content = await _run(
            orchestrator,
            context,
            ToolCall(
                id="call_content",
                name="BrowserExtractContent",
                arguments={"max_chars": 5000, "include_links": True},
            ),
        )
        assert content["content"], content

        html = await _run(
            orchestrator,
            context,
            ToolCall(id="call_html", name="BrowserGetHtml", arguments={"max_chars": 5000}),
        )
        assert "<" in html["html"], html
    finally:
        await worker.close()


async def _run(
    orchestrator: ToolOrchestrator,
    context: ToolUseContext,
    call: ToolCall,
) -> dict:
    events = [event async for event in orchestrator.execute([call], context)]
    result = events[-1].result
    assert result is not None
    if result.is_error and "blocked this browser session" in result.content:
        pytest.xfail(result.content)
    assert not result.is_error, result.content
    return json.loads(result.content)


def _context(root: Path) -> ToolUseContext:
    return ToolUseContext(
        conversation_id="lightpanda-live",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        limits={
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": ("localhost", "127.0.0.1", "0.0.0.0"),
        },
    )
