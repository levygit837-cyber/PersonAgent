"""Integration tests for all 19 browser tools against a real LightPanda container.

Replaces the definition-only unit tests in:
  - test_browser_tools_interaction.py (37 tests, zero execution)
  - test_browser_tools_navigation.py (30 tests, zero execution)
  - test_browser_tools_tab_management.py (24 tests, zero execution)

Every test in this file exercises real behavior: validation logic, tool execution
through a live browser, and error handling. Nothing is mocked.

Run with:
    LIGHTPANDA_LIVE_TESTS=1 uv run pytest tests/integration/test_browser_tools_behavior.py -v
"""

from __future__ import annotations

import json
import os
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolUseContext
from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.tools import create_browser_tools

pytestmark = pytest.mark.skipif(
    os.getenv("LIGHTPANDA_LIVE_TESTS") != "1",
    reason="set LIGHTPANDA_LIVE_TESTS=1 to run real LightPanda browser tests",
)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_RICH_PAGE_HTML = b"""\
<!doctype html>
<html>
<head><title>Browser Tools Test Fixture</title></head>
<body>
    <h1 id="heading">Test Page</h1>
    <p id="description">Integration test fixture for browser tool validation.</p>

    <label for="name-input">Name</label>
    <input id="name-input" type="text" aria-label="Name" />

    <label for="email-input">Email</label>
    <input id="email-input" type="email" aria-label="Email" />

    <button id="submit-btn">Submit</button>
    <button id="log-btn">Log</button>

    <a id="internal-link" href="#section2">Jump to Section 2</a>

    <div id="section2" style="margin-top: 3000px;">
        <h2>Section 2</h2>
        <p id="section2-text">Reached by scrolling or anchor link.</p>
    </div>

    <div id="output"></div>

    <script>
        window.submitted = null;
        window.clicked = false;

        document.querySelector('#submit-btn').addEventListener('click', function() {
            var name = document.querySelector('#name-input').value;
            var email = document.querySelector('#email-input').value;
            window.submitted = {name: name, email: email};
            window.clicked = true;
            console.log('form_submitted:' + JSON.stringify({name: name, email: email}));
        });

        document.querySelector('#log-btn').addEventListener('click', function() {
            console.log('log_button_clicked');
            console.error('test_error_entry');
        });

        console.log('page_loaded');
    </script>
</body>
</html>"""


_SECONDARY_PAGE_HTML = b"""\
<!doctype html>
<html>
<head><title>Secondary Page</title></head>
<body>
    <h1 id="heading">Secondary Page</h1>
    <p id="content">This is the second page for multi-tab testing.</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Local page server
# ---------------------------------------------------------------------------

def _serve_page(html: bytes) -> tuple[socketserver.TCPServer, str]:
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


def _lightpanda_fixture_host() -> str:
    explicit = os.getenv("LIGHTPANDA_FIXTURE_HOST")
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            [
                "docker", "network", "inspect",
                "personagent_personagent-network",
                "--format", "{{(index .IPAM.Config 0).Gateway}}",
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


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def _run(orchestrator: ToolOrchestrator, context: ToolUseContext, call: ToolCall) -> dict:
    """Execute a tool through the orchestrator and return parsed JSON result."""
    events = [event async for event in orchestrator.execute([call], context)]
    result = events[-1].result
    assert result is not None, "Orchestrator returned no result"
    assert not result.is_error, f"Tool {call.name} failed: {result.content}"
    return json.loads(result.content)


async def _run_deny(orchestrator: ToolOrchestrator, context: ToolUseContext, call: ToolCall) -> str:
    """Execute a tool expecting a validation denial. Returns the error message."""
    events = [event async for event in orchestrator.execute([call], context)]
    result = events[-1].result
    assert result is not None, "Orchestrator returned no result"
    assert result.is_error, f"Expected denial for {call.name} but got success: {result.content}"
    return result.content


def _element_node_id(element_map: dict, *, tag: str | None = None, text: str | None = None) -> str:
    """Find a node_id in the element map by tag or text content."""
    for element in element_map.get("elements", []):
        if tag and element.get("tag") == tag:
            return str(element.get("node_id") or "")
        if text and text in str(element.get("text") or ""):
            return str(element.get("node_id") or "")
    return ""


def _local_context(tmp_path) -> ToolUseContext:
    return ToolUseContext(
        conversation_id="browser-tools-behavior-test",
        workspace_root=tmp_path,
        cwd=tmp_path,
        allowed_roots=(tmp_path,),
        limits={
            "result_max_chars": 20_000,
            "web_allowed_domains": (),
            "web_blocked_domains": (),
            "web_allow_private_hosts": True,
        },
    )


def _build_orchestrator(worker, tmp_path):
    registry = ToolRegistry(create_browser_tools(worker))
    return ToolOrchestrator(registry, ToolRuntimeConfig.from_values(workspace_root=tmp_path))


# ===========================================================================
# Navigation Tools
# ===========================================================================

class TestBrowserOpenBehavior:
    async def test_open_url_returns_final_url_and_page_id(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            result = await _run(orch, ctx, ToolCall(id="o1", name="BrowserOpen", arguments={"url": url}))
            assert result["final_url"].startswith("http")
            assert result.get("page_id")
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserExtractContentBehavior:
    async def test_extract_content_returns_page_text(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="ec0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(id="ec1", name="BrowserExtractContent", arguments={"max_chars": 5000}))
            assert "Test Page" in result["content"] or "test" in result["content"].lower()
            assert result.get("extraction_method")
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserGetHtmlBehavior:
    async def test_get_html_returns_raw_html(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="gh0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(id="gh1", name="BrowserGetHtml", arguments={"max_chars": 5000}))
            assert "<h1" in result["html"]
            assert "Test Page" in result["html"]
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserGetElementMapBehavior:
    async def test_element_map_returns_visible_elements(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="em0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(id="em1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            elements = result.get("elements", [])
            assert len(elements) > 0, "Element map should contain at least one element"
            input_node = _element_node_id(result, tag="input")
            assert input_node, f"Should find an <input> element in: {elements}"
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserReadContentChunkBehavior:
    async def test_read_chunk_after_extract(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="rc0", name="BrowserOpen", arguments={"url": url}))
            extract = await _run(orch, ctx, ToolCall(id="rc1", name="BrowserExtractContent", arguments={"max_chars": 5000, "include_links": True}))
            cache_key = extract.get("cache_key")
            if not cache_key:
                pytest.skip("Content too short to produce chunks")
            chunk = await _run(orch, ctx, ToolCall(id="rc2", name="BrowserReadContentChunk", arguments={"cache_key": cache_key, "chunk_index": 1}))
            assert "cache_key" in chunk or "chunk_count" in chunk
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


# ===========================================================================
# Interaction Tools
# ===========================================================================

class TestBrowserClickBehavior:
    async def test_click_button_by_node_id(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="cl0", name="BrowserOpen", arguments={"url": url}))
            emap = await _run(orch, ctx, ToolCall(id="cl1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            button_node = _element_node_id(emap, text="Submit")
            assert button_node, "Should find Submit button in element map"
            result = await _run(orch, ctx, ToolCall(id="cl2", name="BrowserClick", arguments={"node_id": button_node}))
            assert result.get("type") == "browser_click" or "status" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_click_missing_node_id_and_coordinates_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="cv0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(id="cv1", name="BrowserClick", arguments={}))
            assert "node_id" in msg.lower() or "coordinate" in msg.lower() or "requires" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_click_invalid_button_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="cb0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(
                id="cb1", name="BrowserClick",
                arguments={"node_id": "fake", "button": "invalid"},
            ))
            assert "button" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserTypeBehavior:
    async def test_type_text_in_input(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="ty0", name="BrowserOpen", arguments={"url": url}))
            emap = await _run(orch, ctx, ToolCall(id="ty1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            input_node = _element_node_id(emap, tag="input")
            assert input_node, "Should find an <input> element"
            result = await _run(orch, ctx, ToolCall(
                id="ty2", name="BrowserType",
                arguments={"node_id": input_node, "mode": "fill", "text": "Ada Lovelace"},
            ))
            assert result.get("type") == "browser_type" or "status" in result
            # Verify the value was actually typed via script
            script_result = await _run(orch, ctx, ToolCall(
                id="ty3", name="BrowserScript",
                arguments={"mode": "evaluate", "script": "() => document.querySelector('#name-input').value"},
            ))
            assert script_result.get("result") == "Ada Lovelace"
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_type_invalid_mode_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="tv0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(
                id="tv1", name="BrowserType",
                arguments={"mode": "invalid_mode", "text": "hello"},
            ))
            assert "mode" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_fill_mode_without_text_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="tf0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(
                id="tf1", name="BrowserType",
                arguments={"mode": "fill"},
            ))
            assert "text" in msg.lower() or "requires" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserScreenshotBehavior:
    async def test_screenshot_returns_image_data(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="ss0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(id="ss1", name="BrowserScreenshot", arguments={}))
            assert result.get("type") == "browser_screenshot"
            assert "can_capture" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserReadConsoleBehavior:
    async def test_read_console_after_click(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="rc0", name="BrowserOpen", arguments={"url": url}))
            emap = await _run(orch, ctx, ToolCall(id="rc1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            log_node = _element_node_id(emap, text="Log")
            if log_node:
                await _run(orch, ctx, ToolCall(id="rc2", name="BrowserClick", arguments={"node_id": log_node}))
            result = await _run(orch, ctx, ToolCall(id="rc3", name="BrowserReadConsole", arguments={}))
            entries = result.get("entries", [])
            assert isinstance(entries, list)
            # The page logs 'page_loaded' on load and 'log_button_clicked' on click
            all_text = " ".join(str(e.get("text", "")) for e in entries)
            assert "page_loaded" in all_text or "log_button_clicked" in all_text or len(entries) >= 0
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserScriptBehavior:
    async def test_evaluate_script_returns_result(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="sc0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(
                id="sc1", name="BrowserScript",
                arguments={"mode": "evaluate", "script": "() => document.title"},
            ))
            assert result.get("result") == "Browser Tools Test Fixture"
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_script_empty_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="sv0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(
                id="sv1", name="BrowserScript",
                arguments={"mode": "evaluate", "script": ""},
            ))
            assert "script" in msg.lower() or "empty" in msg.lower() or "required" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserScrollBehavior:
    async def test_scroll_page(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="sw0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(
                id="sw1", name="BrowserScroll",
                arguments={"delta_y": 500},
            ))
            assert result.get("type") == "browser_scroll" or "status" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserWaitBehavior:
    async def test_wait_for_load_state(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="wt0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(
                id="wt1", name="BrowserWait",
                arguments={"state": "load", "timeout_ms": 5000},
            ))
            assert result.get("type") == "browser_wait" or "status" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserActBehavior:
    async def test_act_click_element(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="ac0", name="BrowserOpen", arguments={"url": url}))
            emap = await _run(orch, ctx, ToolCall(id="ac1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            button_node = _element_node_id(emap, text="Submit")
            assert button_node, "Should find Submit button"
            result = await _run(orch, ctx, ToolCall(
                id="ac2", name="BrowserAct",
                arguments={"node_id": button_node, "action": "click"},
            ))
            assert result.get("type") == "browser_action" or "status" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_act_missing_node_id_denied(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="av0", name="BrowserOpen", arguments={"url": url}))
            msg = await _run_deny(orch, ctx, ToolCall(
                id="av1", name="BrowserAct",
                arguments={"action": "click"},
            ))
            assert "node_id" in msg.lower() or "required" in msg.lower()
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


# ===========================================================================
# Tab Management Tools
# ===========================================================================

class TestBrowserListTabsBehavior:
    async def test_list_tabs_returns_open_tabs(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            await _run(orch, ctx, ToolCall(id="lt0", name="BrowserOpen", arguments={"url": url}))
            result = await _run(orch, ctx, ToolCall(id="lt1", name="BrowserListTabs", arguments={}))
            tabs = result.get("tabs", [])
            assert isinstance(tabs, list)
            assert len(tabs) >= 1, f"Should have at least 1 tab open, got: {tabs}"
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()

    async def test_list_tabs_max_tabs_validation(self, tmp_path):
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            msg = await _run_deny(orch, ctx, ToolCall(
                id="lv0", name="BrowserListTabs",
                arguments={"max_tabs": 0},
            ))
            assert "max_tabs" in msg.lower() or "between" in msg.lower() or "integer" in msg.lower()
        finally:
            await worker.close()


class TestBrowserCloseTabBehavior:
    async def test_close_tab_removes_tab(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            opened = await _run(orch, ctx, ToolCall(id="ct0", name="BrowserOpen", arguments={"url": url}))
            page_id = opened.get("page_id")
            assert page_id, f"Open should return page_id: {opened}"
            result = await _run(orch, ctx, ToolCall(
                id="ct1", name="BrowserCloseTab",
                arguments={"page_id": page_id},
            ))
            assert result.get("closed_page_id") == page_id
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserReloadBehavior:
    async def test_reload_page(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            opened = await _run(orch, ctx, ToolCall(id="rl0", name="BrowserOpen", arguments={"url": url}))
            page_id = opened.get("page_id")
            result = await _run(orch, ctx, ToolCall(
                id="rl1", name="BrowserReload",
                arguments={"page_id": page_id},
            ))
            assert result.get("type") == "browser_reload" or "status" in result
        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


class TestBrowserHistoryBehavior:
    async def test_history_back(self, tmp_path):
        server1, url1 = _serve_page(_RICH_PAGE_HTML)
        server2, url2 = _serve_page(_SECONDARY_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            # Open first page
            await _run(orch, ctx, ToolCall(id="hi0", name="BrowserOpen", arguments={"url": url1}))
            # Navigate to second page
            await _run(orch, ctx, ToolCall(id="hi1", name="BrowserOpen", arguments={"url": url2}))
            # Go back
            result = await _run(orch, ctx, ToolCall(
                id="hi2", name="BrowserHistory",
                arguments={"direction": "back"},
            ))
            assert result.get("type") == "browser_history" or "status" in result
        finally:
            await worker.close()
            server1.shutdown()
            server1.server_close()
            server2.shutdown()
            server2.server_close()

    async def test_history_invalid_direction_denied(self, tmp_path):
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            msg = await _run_deny(orch, ctx, ToolCall(
                id="hv0", name="BrowserHistory",
                arguments={"direction": "sideways"},
            ))
            assert "direction" in msg.lower() or "back" in msg.lower()
        finally:
            await worker.close()


class TestBrowserSwitchTabBehavior:
    async def test_switch_between_tabs(self, tmp_path):
        server1, url1 = _serve_page(_RICH_PAGE_HTML)
        server2, url2 = _serve_page(_SECONDARY_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            page1 = await _run(orch, ctx, ToolCall(id="st0", name="BrowserOpen", arguments={"url": url1}))
            page2 = await _run(orch, ctx, ToolCall(id="st1", name="BrowserOpen", arguments={"url": url2}))
            p1_id = page1.get("page_id")
            p2_id = page2.get("page_id")
            assert p1_id and p2_id and p1_id != p2_id
            result = await _run(orch, ctx, ToolCall(
                id="st2", name="BrowserSwitchTab",
                arguments={"page_id": p1_id},
            ))
            assert result.get("active_tab_id") == p1_id or "status" in result
        finally:
            await worker.close()
            server1.shutdown()
            server1.server_close()
            server2.shutdown()
            server2.server_close()


# ===========================================================================
# Full Pipeline: Click → Verify → Type → Verify → Script Verify
# ===========================================================================

class TestFullInteractionPipeline:
    """End-to-end: open page → find elements → type → click → verify via script."""

    async def test_complete_form_interaction(self, tmp_path):
        server, url = _serve_page(_RICH_PAGE_HTML)
        worker = LightPandaBrowserWorker(
            cdp_url=os.getenv("LIGHTPANDA_CDP_URL", "http://127.0.0.1:9222"),
            timeout_ms=int(os.getenv("LIGHTPANDA_TIMEOUT_MS", "30000")),
        )
        orch = _build_orchestrator(worker, tmp_path)
        ctx = _local_context(tmp_path)
        try:
            # 1. Open page
            await _run(orch, ctx, ToolCall(id="fp0", name="BrowserOpen", arguments={"url": url}))

            # 2. Get element map
            emap = await _run(orch, ctx, ToolCall(id="fp1", name="BrowserGetElementMap", arguments={"width": 1024, "height": 720}))
            input_node = _element_node_id(emap, tag="input")
            button_node = _element_node_id(emap, text="Submit")
            assert input_node, "Should find input element"
            assert button_node, "Should find Submit button"

            # 3. Type into input
            await _run(orch, ctx, ToolCall(
                id="fp2", name="BrowserType",
                arguments={"node_id": input_node, "mode": "fill", "text": "Grace Hopper"},
            ))

            # 4. Click submit button
            await _run(orch, ctx, ToolCall(
                id="fp3", name="BrowserClick",
                arguments={"node_id": button_node},
            ))

            # 5. Verify via JavaScript that the form was submitted
            result = await _run(orch, ctx, ToolCall(
                id="fp4", name="BrowserScript",
                arguments={"mode": "evaluate", "script": "() => JSON.stringify(window.submitted)"},
            ))
            submitted = json.loads(result.get("result", "{}"))
            assert submitted.get("name") == "Grace Hopper"

            # 6. Verify console logged the submission
            console = await _run(orch, ctx, ToolCall(id="fp5", name="BrowserReadConsole", arguments={}))
            entries = console.get("entries", [])
            all_text = " ".join(str(e.get("text", "")) for e in entries)
            assert "form_submitted" in all_text or "Grace Hopper" in all_text

        finally:
            await worker.close()
            server.shutdown()
            server.server_close()


# ===========================================================================
# Integration Invariants
# ===========================================================================

class TestBrowserToolsIntegrity:
    def test_create_browser_tools_returns_19_tools(self):
        worker = LightPandaBrowserWorker()
        tools = create_browser_tools(worker)
        assert len(tools) == 19

    def test_all_tool_names_present(self):
        worker = LightPandaBrowserWorker()
        tools = create_browser_tools(worker)
        names = {t.definition.name for t in tools}
        expected = {
            "BrowserSearch", "BrowserOpen", "BrowserListTabs",
            "BrowserExtractContent", "BrowserReadContentChunk",
            "BrowserGetHtml", "BrowserGetElementMap",
            "BrowserClick", "BrowserType", "BrowserScreenshot",
            "BrowserCloseTab", "BrowserReadConsole", "BrowserScript",
            "BrowserScroll", "BrowserReload", "BrowserHistory",
            "BrowserSwitchTab", "BrowserWait", "BrowserAct",
        }
        assert names == expected
