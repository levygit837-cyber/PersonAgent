from __future__ import annotations

import json
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
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
            "prepared_dom_text",
            "prepared_readable_dom_text",
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
async def test_lightpanda_browser_control_tools_live_local_page(tmp_path):
    server, url = _serve_local_browser_control_page()
    worker = LightPandaBrowserWorker(
        cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
        timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
    )
    registry = ToolRegistry(create_browser_tools(worker))
    orchestrator = ToolOrchestrator(
        registry,
        ToolRuntimeConfig.from_values(workspace_root=tmp_path),
    )
    context = _local_context(tmp_path)

    try:
        opened = await _run(
            orchestrator,
            context,
            ToolCall(id="control_open", name="BrowserOpen", arguments={"url": url}),
        )
        page_id = opened["page_id"]

        element_map = await _run(
            orchestrator,
            context,
            ToolCall(id="control_map", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}),
        )
        input_node = _element_node_id(element_map, tag="input")
        button_node = _element_node_id(element_map, text="Save")
        assert input_node, element_map
        assert button_node, element_map

        typed = await _run(
            orchestrator,
            context,
            ToolCall(
                id="control_type",
                name="BrowserType",
                arguments={"page_id": page_id, "node_id": input_node, "mode": "fill", "text": "Ada"},
            ),
        )
        assert typed["type"] == "browser_type"

        clicked = await _run(
            orchestrator,
            context,
            ToolCall(
                id="control_click",
                name="BrowserClick",
                arguments={"page_id": page_id, "node_id": button_node},
            ),
        )
        assert clicked["type"] == "browser_click"

        script = await _run(
            orchestrator,
            context,
            ToolCall(
                id="control_script",
                name="BrowserScript",
                arguments={
                    "page_id": page_id,
                    "mode": "evaluate",
                    "script": "() => ({ value: document.querySelector('#name').value, clicked: window.clicked })",
                },
            ),
        )
        assert script["result"]["value"] == "Ada"
        assert script["result"]["clicked"] is True

        console = await _run(
            orchestrator,
            context,
            ToolCall(id="control_console", name="BrowserReadConsole", arguments={"page_id": page_id}),
        )
        assert any("clicked:Ada" in entry["text"] for entry in console["entries"]), console

        screenshot = await _run(
            orchestrator,
            context,
            ToolCall(id="control_screenshot", name="BrowserScreenshot", arguments={"page_id": page_id}),
        )
        assert screenshot["type"] == "browser_screenshot"
        assert "can_capture" in screenshot

        switched = await _run(
            orchestrator,
            context,
            ToolCall(id="control_switch", name="BrowserSwitchTab", arguments={"page_id": page_id}),
        )
        assert switched["active_tab_id"] == page_id

        closed = await _run(
            orchestrator,
            context,
            ToolCall(id="control_close", name="BrowserCloseTab", arguments={"page_id": page_id}),
        )
        assert closed["closed_page_id"] == page_id
    finally:
        await worker.close()
        server.shutdown()
        server.server_close()


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


def _local_context(root: Path) -> ToolUseContext:
    return ToolUseContext(
        conversation_id="lightpanda-browser-control-live",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
        limits={
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": (),
            "web_allow_private_hosts": True,
        },
    )


def _element_node_id(element_map: dict, *, tag: str | None = None, text: str | None = None) -> str:
    for element in element_map.get("elements", []):
        if tag and element.get("tag") == tag:
            return str(element.get("node_id") or "")
        if text and text in str(element.get("text") or ""):
            return str(element.get("node_id") or "")
    return ""


def _serve_local_browser_control_page() -> tuple[socketserver.TCPServer, str]:
    html = b"""<!doctype html>
<html>
  <head><title>Browser Control Fixture</title></head>
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

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/"
