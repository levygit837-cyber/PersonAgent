from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from personagent.application.tools import ToolOrchestrator, ToolRegistry, ToolRuntimeConfig
from personagent.domain.tools import ToolCall, ToolExecutionStatus, ToolUseContext
from personagent.infrastructure.browser import (
    BrowserSearchResult,
    BrowserUnavailableError,
    LightPandaBrowserWorker,
    normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.browser.lightpanda import (
    _BrowserSession,
    _clean_browser_url,
    _clean_extracted_content,
)
from personagent.infrastructure.tools import create_browser_tools
from personagent.infrastructure.tools.browser_tools import _summarize_element_map
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
    assert url == ("https://search.yahoo.com/search?p=site%3Aexample.com+Example+Domain&pz=7")


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
        "https://www.google.com/search?q=site%3Aexample.com+Example+Domain&hl=en&gl=us&pws=0&num=7"
    )


def test_lightpanda_stylesheet_hrefs_include_preload_and_css_paths():
    html = """
    <html><head>
      <link rel="preload" as="style" href="/_next/static/css/app.css">
      <link rel="modulepreload" href="/_next/static/chunk.js">
      <link href="https://cdn.example.com/site.css?hash=1" rel="prefetch">
      <link rel="stylesheet" href="/styles/theme.css">
    </head></html>
    """

    hrefs = LightPandaBrowserWorker._stylesheet_hrefs(
        html,
        "https://example.com/docs/page",
        max_hrefs=8,
    )

    assert hrefs == [
        "https://example.com/_next/static/css/app.css",
        "https://cdn.example.com/site.css?hash=1",
        "https://example.com/styles/theme.css",
    ]


@pytest.mark.asyncio
async def test_stylesheet_cache_uses_persistent_disk_cache(tmp_path):
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
    worker._stylesheet_cache_dir = tmp_path
    client = FakeStylesheetClient("body { background: url('../bg.png'); }")

    css_text, first_hit = await worker._fetch_stylesheet_css(client, "https://example.com/assets/app.css")
    worker._stylesheet_cache.clear()
    cached_css_text, second_hit = await worker._fetch_stylesheet_css(client, "https://example.com/assets/app.css")

    assert first_hit is False
    assert second_hit is True
    assert client.calls == 1
    assert "https://example.com/bg.png" in css_text
    assert cached_css_text == css_text


@pytest.mark.asyncio
async def test_lightpanda_browser_view_navigation_returns_screenshot_payload():
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    result = await worker.view_navigate(
        browser_id="panel-browser",
        url="example.com",
        width=800,
        height=500,
    )

    assert result["type"] == "browser_view"
    assert result["url"] == "https://example.com"
    assert result["image_mime_type"] == "image/png"
    assert result["image_data"] == base64.b64encode(b"browser-image").decode("ascii")
    assert page.viewport_size == {"width": 800, "height": 500}


@pytest.mark.asyncio
async def test_lightpanda_browser_view_waits_for_css_visual_ready():
    page = StyleReadyPage()
    context = FakeContext(page=page)

    async def connector(_endpoint):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def no_embed(html, _current_url):
        return html, {"stylesheet_count": 1, "embedded_stylesheet_count": 0, "stylesheet_cached_count": 0}

    worker._html_with_embedded_stylesheet_fallbacks = no_embed
    result = await worker.view_navigate(
        browser_id="panel-browser",
        url="https://styled.example",
        width=800,
        height=500,
    )

    assert page.goto_wait_until == "load"
    assert "load" in page.wait_load_states
    assert page.style_ready_checks >= 1
    assert result["style_ready"] is True
    assert result["stylesheet_count"] == 1
    assert result["stylesheet_loaded_count"] == 1


@pytest.mark.asyncio
async def test_lightpanda_browser_fast_view_prioritizes_html_css_over_mapping():
    page = StyleReadyPage()
    context = FakeContext(page=page)

    async def connector(_endpoint):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    worker._element_map_cache["panel-browser"] = [{"node_id": "cached_button", "text": "Cached", "bounds": {}}]

    async def no_embed(html, _current_url):
        return html, {"stylesheet_count": 1, "embedded_stylesheet_count": 0, "stylesheet_cached_count": 0}

    worker._html_with_embedded_stylesheet_fallbacks = no_embed
    result = await worker.view_navigate(
        browser_id="panel-browser",
        url="https://styled.example",
        width=800,
        height=500,
        wait_for_styles=False,
    )

    assert page.goto_wait_until == "domcontentloaded"
    assert page.style_ready_checks == 0
    assert result["style_ready"] is True
    assert result["element_map"][0]["node_id"] == "cached_button"


@pytest.mark.asyncio
async def test_lightpanda_browser_view_uses_computed_fallback_when_css_not_ready():
    page = StyleFailurePage()
    context = FakeContext(page=page)

    async def connector(_endpoint):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def no_embed(html, _current_url):
        return html, {"stylesheet_count": 1, "embedded_stylesheet_count": 0, "stylesheet_cached_count": 0}

    worker._html_with_embedded_stylesheet_fallbacks = no_embed
    result = await worker.view_navigate(
        browser_id="panel-browser",
        url="https://styled.example",
        width=800,
        height=500,
    )

    assert result["render_mode"] == "computed_html"
    assert result["css_fidelity"] == "computed"
    assert result["style_ready"] is True
    assert "personagent-css-fidelity" in result["document_html"]


@pytest.mark.asyncio
async def test_lightpanda_browser_render_cache_returns_cached_snapshot():
    page = StyleReadyPage()
    context = FakeContext(page=page)

    async def connector(_endpoint):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def no_embed(html, _current_url):
        return html, {"stylesheet_count": 1, "embedded_stylesheet_count": 0, "stylesheet_cached_count": 0}

    worker._html_with_embedded_stylesheet_fallbacks = no_embed
    first = await worker.view_navigate(
        browser_id="panel-browser",
        url="https://styled.example",
        width=800,
        height=500,
    )
    cached = await worker.view_snapshot(
        browser_id="panel-browser",
        width=1024,
        height=720,
        cache_mode="prefer_cached",
    )

    assert first["render_cache_key"] == cached["render_cache_key"]
    assert cached["render_cache_status"] == "hit"
    assert cached["browser_snapshot"]["render_cache_status"] == "hit"
    assert cached["document_html"] == first["document_html"]


def test_clean_browser_url_strips_encoded_invisible_suffix():
    assert (
        _clean_browser_url("https://hai.stanford.edu/ai-index/2026-ai-index-report%C2%A0")
        == "https://hai.stanford.edu/ai-index/2026-ai-index-report"
    )
    assert _clean_browser_url("  https://example.com/path%E2%80%8B  ") == "https://example.com/path"


def test_clean_extracted_content_removes_link_dense_navigation_blocks():
    noisy_nav = "\n".join(
        f"- [Category {index}](https://www.forbes.com/vetted/category-{index}/)"
        for index in range(30)
    )
    raw = (
        f"{noisy_nav}\n\n"
        "Mini Crossword By Forbes\nQuick solve. Big win.\n([]())\n\n"
        "The 8 Biggest AI Trends For 2026\n\n"
        "Enterprise AI adoption is moving from experiments into operational systems.\n\n"
        "Leaders should evaluate agents, data quality, governance, and cost controls."
    )

    cleaned, stats = _clean_extracted_content(raw)

    assert "Category 1" not in cleaned
    assert "Mini Crossword" not in cleaned
    assert "([]())" not in cleaned
    assert "The 8 Biggest AI Trends For 2026" in cleaned
    assert "Enterprise AI adoption" in cleaned
    assert stats["removed_link_noise_blocks"] == 1


def test_summarize_element_map_keeps_bounds_for_browser_visual_overlay():
    elements = _summarize_element_map(
        [
            {
                "node_id": "pa_signin",
                "role": "link",
                "tag": "a",
                "text": "Sign in",
                "selector": "a[href='/login']",
                "bounds": {"x": 930, "y": 24, "width": 76, "height": 34},
                "visible": True,
            }
        ]
    )

    assert elements[0]["node_id"] == "pa_signin"
    assert elements[0]["bounds"] == {"x": 930, "y": 24, "width": 76, "height": 34}


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
async def test_lightpanda_worker_keeps_recent_search_cache_after_session_reset():
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
    conversation_id = "conversation-a"
    session = _BrowserSession(browser=FakeBrowser(), context=FakeContext(), page=FakePage())
    worker._sessions[conversation_id] = session
    snapshot = worker._cache_search_results(
        conversation_id=conversation_id,
        query="langchain framework",
        search_url="https://search.yahoo.com/search?p=langchain+framework",
        results=[
            BrowserSearchResult(
                index=5,
                title="LangChain docs",
                url="https://python.langchain.com/docs/",
                snippet="Docs",
            )
        ],
    )

    await worker._reset_browser()
    empty_session = _BrowserSession(
        browser=FakeBrowser(),
        context=FakeContext(),
        page=FakePage(),
    )

    target_url, matched_search_id = worker._result_url(
        conversation_id,
        empty_session,
        5,
    )

    assert worker._sessions == {}
    assert target_url == "https://python.langchain.com/docs/"
    assert matched_search_id == snapshot.search_id


@pytest.mark.asyncio
async def test_lightpanda_worker_remembers_single_target_sessions():
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
    context = TargetAlreadyLoadedContext(page=FakePage())
    session = _BrowserSession(
        browser=FakeBrowser(context=context), context=context, page=context.page
    )

    first = await worker._new_session_page(session)
    second = await worker._new_session_page(session)

    assert first is None
    assert second is None
    assert context.new_page_calls == 1
    assert session.new_pages_supported is False


@pytest.mark.asyncio
async def test_browser_open_reuses_single_target_page_when_new_targets_are_unavailable():
    page = ScriptedPage()
    context = TargetAlreadyLoadedContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    raw_labels: list[str] = []

    async def raw_runtime_value(url: str, _expression: str, *, label: str, timeout: float):
        raw_labels.append(label)
        assert label == "search_results"
        assert "first+query" in url
        return [
            {
                "title": "Cached Search Title",
                "url": "https://source-a.test/article",
                "snippet": "Cached snippet",
            }
        ]

    worker._raw_runtime_evaluate_value = raw_runtime_value

    search = await worker.search(
        conversation_id="conversation-single-target",
        query="first query",
        max_results=1,
    )
    opened = await worker.open(
        conversation_id="conversation-single-target",
        result_index=1,
        search_id=search["search_id"],
    )

    assert opened["final_url"] == "https://source-a.test/article"
    assert opened["title"] == "Source A"
    assert raw_labels == ["search_results"]
    assert context.new_page_calls == 1
    assert page.goto_history == ["https://source-a.test/article"]


@pytest.mark.asyncio
async def test_extract_defaults_to_last_browser_open_after_followup_search():
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def no_markdown_url(_url):
        return ""

    async def raw_runtime_value(url, _expression, *, label, timeout):
        return f"Content from {url}"

    worker._lightpanda_markdown_url = no_markdown_url
    worker._raw_runtime_evaluate_value = raw_runtime_value

    await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    opened = await worker.open(conversation_id="conversation-a", result_index=1)
    assert opened["final_url"] == "https://source-a.test/article"

    await worker.search(
        conversation_id="conversation-a",
        query="second query",
        max_results=1,
    )
    goto_history_before_extract = list(page.goto_history)

    content = await worker.extract_content(
        conversation_id="conversation-a",
        max_chars=2_000,
        include_links=False,
    )

    assert content["url"] == "https://source-a.test/article"
    assert content["page_id"] == opened["page_id"]
    assert "source-a.test/article" in content["content"]
    assert page.goto_history == goto_history_before_extract


@pytest.mark.asyncio
async def test_lightpanda_markdown_uses_isolated_raw_cdp_target():
    page = ScriptedPage()
    page.url = "https://example.com/"
    context = FakeContext(page=page)
    session = _BrowserSession(
        browser=FakeBrowser(context=context),
        context=context,
        page=page,
    )
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")

    async def raw_cdp_command(**_kwargs):
        return {"markdown": "Isolated target markdown"}

    worker._lightpanda_raw_cdp_command = raw_cdp_command

    markdown = await worker._lightpanda_markdown(session)

    assert markdown == "Isolated target markdown"


@pytest.mark.asyncio
async def test_navigation_failure_closes_only_failed_session():
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
    failed = _BrowserSession(
        browser=FakeBrowser(),
        context=FakeContext(),
        page=ScriptedPage(fail_on_goto=True),
    )
    other = _BrowserSession(
        browser=FakeBrowser(),
        context=FakeContext(),
        page=FakePage(),
    )
    worker._sessions["failed"] = failed
    worker._sessions["other"] = other

    with pytest.raises(BrowserUnavailableError):
        await worker._goto("failed", failed, "https://broken.example/")

    assert "failed" not in worker._sessions
    assert "other" in worker._sessions


@pytest.mark.asyncio
async def test_release_browser_closes_browser_without_stopping_playwright_connection():
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222")
    browser = FakeCdpBrowser()

    await worker._release_browser(browser)

    assert browser.closed is True
    assert browser.connection.stopped is False


@pytest.mark.asyncio
async def test_navigation_partial_timeout_keeps_session_and_open_succeeds():
    page = PartialTimeoutPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    opened = await worker.open(
        conversation_id="conversation-a",
        url="https://www.ibm.com/think/news/ai-tech-trends-predictions-2026",
    )

    assert opened["final_url"] == "https://www.ibm.com/think/news/ai-tech-trends-predictions-2026"
    assert opened["page_id"]
    assert "conversation-a" in worker._sessions


@pytest.mark.asyncio
async def test_extract_url_uses_cleaned_prepared_page_target():
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    content = await worker.extract_content(
        conversation_id="conversation-a",
        url="https://hai.stanford.edu/ai-index/2026-ai-index-report%C2%A0",
        max_chars=2_000,
        include_links=False,
    )

    assert content["url"] == "https://hai.stanford.edu/ai-index/2026-ai-index-report"
    assert (
        content["content"] == "Content from https://hai.stanford.edu/ai-index/2026-ai-index-report"
    )
    assert content["extraction_method"] == "prepared_dom_text"
    assert page.goto_history == ["https://hai.stanford.edu/ai-index/2026-ai-index-report"]


@pytest.mark.asyncio
async def test_extract_prepares_live_page_by_dismissing_popups_and_scrolling():
    page = PopupScrollPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    opened = await worker.open(
        conversation_id="conversation-a",
        url="https://example.com/article",
    )
    content = await worker.extract_content(
        conversation_id="conversation-a",
        page_id=opened["page_id"],
        max_chars=5_000,
        include_links=False,
    )

    assert content["content"] == "Loaded article body after incremental scroll."
    assert content["extraction_method"] == "prepared_readable_dom_text"
    assert content["content_cleanup"]["prepared_page"] is True
    assert content["content_cleanup"]["popup_dismissed_count"] == 1
    assert content["content_cleanup"]["scroll_steps"] == 4
    assert page.popup_evaluations == 2
    assert page.scroll_evaluations == 1


@pytest.mark.asyncio
async def test_extract_uses_cached_last_open_when_playwright_session_disconnected():
    page = ScriptedPage()
    context = FakeContext(page=page)
    browser = FakeBrowser(context=context)
    endpoints: list[str] = []

    async def connector(endpoint: str):
        endpoints.append(endpoint)
        return browser

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def raw_markdown(url: str):
        return f"Cached content from {url}"

    worker._lightpanda_markdown_url = raw_markdown

    await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    opened = await worker.open(conversation_id="conversation-a", result_index=1)
    browser.closed = True
    page.closed = True

    content = await worker.extract_content(
        conversation_id="conversation-a",
        max_chars=2_000,
        include_links=False,
    )

    assert content["url"] == opened["final_url"]
    assert content["page_id"] == opened["page_id"]
    assert "source-a.test/article" in content["content"]
    assert endpoints == ["ws://127.0.0.1:9222"]


@pytest.mark.asyncio
async def test_browser_list_tabs_returns_recent_opened_pages():
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    first = await worker.open(conversation_id="conversation-a", result_index=1)
    await worker.search(
        conversation_id="conversation-a",
        query="second query",
        max_results=1,
    )
    second = await worker.open(conversation_id="conversation-a", result_index=1)

    tabs = await worker.list_tabs(conversation_id="conversation-a", max_tabs=10)

    assert tabs["type"] == "browser_tabs"
    assert tabs["tab_count"] == 2
    assert tabs["last_open_page_id"] == second["page_id"]
    assert [tab["page_id"] for tab in tabs["tabs"]] == [second["page_id"], first["page_id"]]
    assert tabs["tabs"][0]["is_last_open"] is True
    assert tabs["tabs"][0]["is_current_page"] is True
    assert tabs["tabs"][0]["domain"] == "source-b.test"
    assert tabs["tabs"][1]["domain"] == "source-a.test"


@pytest.mark.asyncio
async def test_browser_list_tabs_returns_single_shared_current_url_without_opened_pages():
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._current_url_cache["conversation-a"] = "https://github.com/personagent/personagent"

    tabs = await worker.list_tabs(conversation_id="conversation-a", max_tabs=10)

    assert tabs["type"] == "browser_tabs"
    assert tabs["tab_count"] == 1
    assert tabs["current_url"] == "https://github.com/personagent/personagent"
    assert tabs["last_open_page_id"] == "conversation-a"
    assert tabs["tabs"][0]["page_id"] == "conversation-a"
    assert tabs["tabs"][0]["domain"] == "github.com"
    assert tabs["tabs"][0]["is_current_page"] is True


@pytest.mark.asyncio
async def test_browser_list_tabs_falls_back_to_pre_conversation_panel_session():
    page = ScriptedPage()
    page.url = "https://github.com/"
    context = FakeContext(page=page)
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._sessions["browser:panel-tab"] = _BrowserSession(
        browser=FakeBrowser(context=context),
        context=context,
        page=page,
        current_url="https://github.com/",
        current_page_id="browser:panel-tab",
    )

    tabs = await worker.list_tabs(conversation_id="conversation-a", max_tabs=10)

    assert tabs["type"] == "browser_tabs"
    assert tabs["source"] == "shared_panel_sessions"
    assert tabs["tab_count"] == 1
    assert tabs["tabs"][0]["browser_id"] == "browser:panel-tab"
    assert tabs["tabs"][0]["page_id"] == "browser:panel-tab"
    assert tabs["tabs"][0]["final_url"] == "https://github.com/"


@pytest.mark.asyncio
async def test_browser_list_tabs_merges_current_conversation_and_panel_sessions():
    conversation_page = ScriptedPage()
    conversation_page.url = "https://example.com/"
    panel_page = ScriptedPage()
    panel_page.url = "https://github.com/"
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._sessions["conversation-a"] = _BrowserSession(
        browser=FakeBrowser(context=FakeContext(page=conversation_page)),
        context=FakeContext(page=conversation_page),
        page=conversation_page,
        current_url="https://example.com/",
        current_page_id="conversation-a",
    )
    worker._sessions["browser:panel-tab"] = _BrowserSession(
        browser=FakeBrowser(context=FakeContext(page=panel_page)),
        context=FakeContext(page=panel_page),
        page=panel_page,
        current_url="https://github.com/",
        current_page_id="browser:panel-tab",
    )

    tabs = await worker.list_tabs(conversation_id="conversation-a", max_tabs=10)

    assert tabs["tab_count"] == 2
    assert [tab["page_id"] for tab in tabs["tabs"]] == ["conversation-a", "browser:panel-tab"]
    assert [tab["final_url"] for tab in tabs["tabs"]] == ["https://example.com/", "https://github.com/"]


@pytest.mark.asyncio
async def test_panel_browser_page_id_targets_live_panel_session_without_browser_open(tmp_path):
    page = ScriptedPage()
    page.url = "https://github.com/"
    context = FakeContext(page=page)
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._sessions["browser:panel-tab"] = _BrowserSession(
        browser=FakeBrowser(context=context),
        context=context,
        page=page,
        current_url="https://github.com/",
    )
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    tool_context = _tool_context(tmp_path, conversation_id="conversation-a")

    switch_call = ToolCall(
        id="call_switch",
        name="BrowserSwitchTab",
        arguments={"page_id": "browser:panel-tab"},
    )
    switch_result = await tools["BrowserSwitchTab"].call(
        switch_call.arguments,
        tool_context,
        switch_call,
    )
    switch_data = json.loads(switch_result.content)

    assert switch_result.status == ToolExecutionStatus.COMPLETED
    assert switch_data["active_tab_id"] == "browser:panel-tab"
    assert switch_data["tab_count"] == 1
    assert switch_data["tabs"][0]["final_url"] == "https://github.com/"

    map_call = ToolCall(
        id="call_map",
        name="BrowserGetElementMap",
        arguments={"page_id": "browser:panel-tab"},
    )
    map_result = await tools["BrowserGetElementMap"].call(
        map_call.arguments,
        tool_context,
        map_call,
    )
    map_data = json.loads(map_result.content)

    assert map_result.status == ToolExecutionStatus.COMPLETED
    assert map_data["active_tab_id"] == "browser:panel-tab"
    assert map_data["url"] == "https://github.com/"


@pytest.mark.asyncio
async def test_browser_act_uses_previous_element_metadata_when_remap_drops_node():
    page = StaleNodeActionPage()
    page.url = "https://github.com/"
    context = FakeContext(page=page)
    browser_id = "browser:panel-tab"
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._sessions[browser_id] = _BrowserSession(
        browser=FakeBrowser(context=context),
        context=context,
        page=page,
        current_url="https://github.com/",
        current_page_id=browser_id,
    )
    worker._element_map_cache[browser_id] = [
        {
            "node_id": "pa_1eidf0u",
            "role": "link",
            "tag": "a",
            "text": "Sign in Sign in",
            "href": "https://github.com/login",
            "selector": "a[href='/login']",
            "bounds": {"x": 930, "y": 24, "width": 76, "height": 34},
            "visible": True,
        }
    ]

    view = await worker.view_act(
        browser_id=browser_id,
        node_id="pa_1eidf0u",
        action="click",
        width=1024,
        height=720,
    )

    assert page.action_arg is not None
    assert page.action_arg["selector"] == "a[href='/login']"
    assert page.action_arg["targetText"] == "Sign in Sign in"
    assert view["last_action"]["target"]["selector"] == "a[href='/login']"
    assert view["last_action"]["result"]["ok"] is True


@pytest.mark.asyncio
async def test_panel_browser_page_id_can_extract_content_without_browser_open():
    page = ScriptedPage()
    page.url = "https://github.com/"
    context = FakeContext(page=page)
    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=lambda _endpoint: None)
    worker._sessions["browser:panel-tab"] = _BrowserSession(
        browser=FakeBrowser(context=context),
        context=context,
        page=page,
        current_url="https://github.com/",
    )

    html = await worker.get_html(
        conversation_id="browser:panel-tab",
        page_id="browser:panel-tab",
        max_chars=1_000,
    )
    content = await worker.extract_content(
        conversation_id="browser:panel-tab",
        page_id="browser:panel-tab",
        max_chars=1_000,
        include_links=False,
    )

    assert html["page_id"] == "browser:panel-tab"
    assert "https://github.com/" in html["html"]
    assert content["page_id"] == "browser:panel-tab"
    assert "Content from https://github.com/" in content["content"]


@pytest.mark.asyncio
async def test_browser_open_accepts_url_with_matching_search_id(tmp_path):
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    tool_context = _tool_context(tmp_path, conversation_id="conversation-a")

    search = await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    search_id = search["search_id"]
    target_url = search["results"][0]["url"]

    denied = await tools["BrowserOpen"].validate_input(
        {"url": target_url, "search_id": search_id},
        tool_context,
    )
    result = await tools["BrowserOpen"].call(
        {"url": target_url, "search_id": search_id},
        tool_context,
        ToolCall("open_url_search", "BrowserOpen", {}),
    )
    opened = json.loads(result.content)

    assert denied is None
    assert opened["final_url"] == target_url
    assert opened["search_id"] == search_id
    assert opened["window_id"] == opened["page_id"]


@pytest.mark.asyncio
async def test_browser_open_defaults_search_id_only_to_first_result(tmp_path):
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    tool_context = _tool_context(tmp_path, conversation_id="conversation-a")

    search = await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    search_id = search["search_id"]

    denied = await tools["BrowserOpen"].validate_input({"search_id": search_id}, tool_context)
    result = await tools["BrowserOpen"].call(
        {"search_id": search_id},
        tool_context,
        ToolCall("open_first_from_search", "BrowserOpen", {}),
    )
    opened = json.loads(result.content)

    assert denied is None
    assert opened["final_url"] == "https://source-a.test/article"
    assert opened["search_id"] == search_id


@pytest.mark.asyncio
async def test_browser_open_recovers_index_alias_and_url_takes_precedence(tmp_path):
    page = ScriptedPage()
    context = FakeContext(page=page)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    tool_context = _tool_context(tmp_path, conversation_id="conversation-a")

    search = await worker.search(
        conversation_id="conversation-a",
        query="first query",
        max_results=1,
    )
    search_id = search["search_id"]

    alias_result = await tools["BrowserOpen"].call(
        {"index": 1, "search_id": search_id},
        tool_context,
        ToolCall("open_index_alias", "BrowserOpen", {}),
    )
    alias_opened = json.loads(alias_result.content)
    url_result = await tools["BrowserOpen"].call(
        {
            "url": "https://manual-source.test/article",
            "result_index": 1,
            "search_id": search_id,
        },
        tool_context,
        ToolCall("open_url_wins", "BrowserOpen", {}),
    )
    url_opened = json.loads(url_result.content)

    assert alias_opened["final_url"] == "https://source-a.test/article"
    assert alias_opened["search_id"] == search_id
    assert url_opened["final_url"] == "https://manual-source.test/article"
    assert url_opened["search_id"] is None


@pytest.mark.asyncio
async def test_parallel_browser_search_runs_as_concurrency_safe_distinct_targets(tmp_path):
    context = FakeContext(page_factory=ScriptedPage)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)
    raw_search_urls: list[str] = []

    async def no_playwright_page(_session):
        return None

    async def raw_runtime_value(url: str, _expression: str, *, label: str, timeout: float):
        raw_search_urls.append(url)
        if "alpha" in url:
            return [
                {
                    "title": "Alpha Source",
                    "url": "https://alpha-source.test/article",
                    "snippet": "Alpha result",
                }
            ]
        if "beta" in url:
            return [
                {
                    "title": "Beta Source",
                    "url": "https://beta-source.test/article",
                    "snippet": "Beta result",
                }
            ]
        return [
            {
                "title": "Gamma Source",
                "url": "https://gamma-source.test/article",
                "snippet": "Gamma result",
            }
        ]

    worker._new_session_page = no_playwright_page
    worker._raw_runtime_evaluate_value = raw_runtime_value
    registry = ToolRegistry(create_browser_tools(worker))
    orchestrator = ToolOrchestrator(
        registry,
        ToolRuntimeConfig.from_values(workspace_root=tmp_path, max_concurrency=4),
    )
    tool_context = _tool_context(tmp_path, conversation_id="conversation-search-parallel")
    calls = [
        ToolCall("search_alpha", "BrowserSearch", {"query": "alpha", "max_results": 1}),
        ToolCall("search_beta", "BrowserSearch", {"query": "beta", "max_results": 1}),
        ToolCall("search_gamma", "BrowserSearch", {"query": "gamma", "max_results": 1}),
    ]

    events = [event async for event in orchestrator.execute(calls, tool_context)]
    grouped = [
        event
        for event in events
        if event.event == "tool_group_started" and event.progress is not None
    ]
    results = [
        json.loads(event.result.content)
        for event in events
        if event.result is not None and event.result.status == ToolExecutionStatus.COMPLETED
    ]

    assert grouped
    assert grouped[0].progress.data["tool_call_ids"] == [
        "search_alpha",
        "search_beta",
        "search_gamma",
    ]
    assert [result["results"][0]["url"] for result in results] == [
        "https://alpha-source.test/article",
        "https://beta-source.test/article",
        "https://gamma-source.test/article",
    ]
    assert len({result["search_id"] for result in results}) == 3
    assert len(raw_search_urls) == 3


@pytest.mark.asyncio
async def test_parallel_browser_open_and_extract_target_distinct_windows(tmp_path):
    context = FakeContext(page_factory=ScriptedPage)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def raw_markdown(url: str):
        return f"Readable content from {url}"

    worker._lightpanda_markdown_url = raw_markdown
    registry = ToolRegistry(create_browser_tools(worker))
    orchestrator = ToolOrchestrator(
        registry,
        ToolRuntimeConfig.from_values(workspace_root=tmp_path, max_concurrency=4),
    )
    tool_context = _tool_context(tmp_path, conversation_id="conversation-parallel")
    urls = [
        "https://source-a.test/article",
        "https://source-b.test/article",
        "https://source-c.test/article",
    ]
    open_calls = [
        ToolCall(f"open_{index}", "BrowserOpen", {"url": url})
        for index, url in enumerate(urls, start=1)
    ]

    open_events = [event async for event in orchestrator.execute(open_calls, tool_context)]
    open_results = [
        json.loads(event.result.content)
        for event in open_events
        if event.result is not None and event.result.status == ToolExecutionStatus.COMPLETED
    ]
    extract_calls = [
        ToolCall(
            f"extract_{index}",
            "BrowserExtractContent",
            {"window_id": opened["window_id"], "max_chars": 2_000},
        )
        for index, opened in enumerate(open_results, start=1)
    ]
    extract_events = [event async for event in orchestrator.execute(extract_calls, tool_context)]
    extracted = [
        json.loads(event.result.content)
        for event in extract_events
        if event.result is not None and event.result.status == ToolExecutionStatus.COMPLETED
    ]

    assert [result["final_url"] for result in open_results] == urls
    assert len({result["window_id"] for result in open_results}) == 3
    assert [result["url"] for result in extracted] == urls
    assert all(
        result["window_id"] == open_results[index]["window_id"]
        for index, result in enumerate(extracted)
    )
    assert [result["content"] for result in extracted] == [f"Content from {url}" for url in urls]


@pytest.mark.asyncio
async def test_default_extract_walks_unextracted_opened_pages():
    context = FakeContext(page_factory=ScriptedPage)

    async def connector(_endpoint: str):
        return FakeBrowser(context=context)

    worker = LightPandaBrowserWorker(cdp_url="ws://127.0.0.1:9222", connector=connector)

    async def raw_markdown(url: str):
        return f"Readable content from {url}"

    worker._lightpanda_markdown_url = raw_markdown

    first = await worker.open(conversation_id="conversation-a", url="https://source-a.test/article")
    second = await worker.open(
        conversation_id="conversation-a", url="https://source-b.test/article"
    )

    first_content = await worker.extract_content(
        conversation_id="conversation-a",
        max_chars=2_000,
        include_links=False,
    )
    second_content = await worker.extract_content(
        conversation_id="conversation-a",
        max_chars=2_000,
        include_links=False,
    )

    assert first_content["page_id"] == first["page_id"]
    assert second_content["page_id"] == second["page_id"]
    assert first_content["url"] != second_content["url"]


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

    tabs_call = ToolCall(id="call_tabs", name="BrowserListTabs", arguments={})
    tabs_result = await tools["BrowserListTabs"].call(tabs_call.arguments, context, tabs_call)
    tabs_data = json.loads(tabs_result.content)
    assert tabs_data["tabs"][0]["final_url"] == "https://example.com/"

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
    assert chunk_data["chunk_size"] == 3_000
    assert chunk_data["returned_chars"] == chunk_data["chunks"][0]["char_count"]
    assert "Example Domain" in chunk_data["chunks"][0]["content"]
    assert chunk_data["links"] == []

    html_call = ToolCall(id="call_html", name="BrowserGetHtml", arguments={})
    html_result = await tools["BrowserGetHtml"].call(html_call.arguments, context, html_call)
    assert "<h1>Example Domain</h1>" in json.loads(html_result.content)["html"]
    assert worker.sessions["conversation-a"]["opened"] == "https://example.com/"


@pytest.mark.asyncio
async def test_browser_tools_default_to_attached_browser_tab_and_block_conflicts(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path, conversation_id="conversation-a")
    context.metadata["browser_target"] = {
        "type": "browser_tab",
        "browser_id": "conversation-a",
        "page_id": "page_attached",
        "window_id": "page_attached",
        "url": "https://github.com/personagent/personagent",
    }

    content_call = ToolCall(id="call_content", name="BrowserExtractContent", arguments={})
    content_result = await tools["BrowserExtractContent"].call(
        content_call.arguments,
        context,
        content_call,
    )
    content_data = json.loads(content_result.content)
    assert content_result.status == ToolExecutionStatus.COMPLETED
    assert content_data["page_id"] == "page_attached"

    screenshot_call = ToolCall(
        id="call_screenshot",
        name="BrowserScreenshot",
        arguments={"page_id": "page_other"},
    )
    screenshot_result = await tools["BrowserScreenshot"].call(
        screenshot_call.arguments,
        context,
        screenshot_call,
    )
    screenshot_data = json.loads(screenshot_result.content)
    assert screenshot_result.status == ToolExecutionStatus.ERROR
    assert screenshot_data["browser_target_conflict"] is True


@pytest.mark.asyncio
async def test_browser_content_chunks_read_multiple_chunks_without_link_dump(tmp_path):
    worker = LongNoisyContentWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path, conversation_id="conversation-long")

    content_call = ToolCall(
        id="call_long_content",
        name="BrowserExtractContent",
        arguments={"include_links": True},
    )
    content_result = await tools["BrowserExtractContent"].call(
        content_call.arguments,
        context,
        content_call,
    )
    content_data = json.loads(content_result.content)

    assert content_data["content_chars"] > len(content_data["content"])
    assert content_data["inline_content_truncated"] is True
    assert content_data["chunk_count"] >= 3
    assert content_data["links"] == []
    assert content_data["links_summary"]["suppressed"] is True

    chunk_call = ToolCall(
        id="call_long_chunks",
        name="BrowserReadContentChunk",
        arguments={
            "cache_key": content_data["cache_key"],
            "chunk_index": 1,
            "chunk_count": 2,
        },
    )
    chunk_result = await tools["BrowserReadContentChunk"].call(
        chunk_call.arguments,
        context,
        chunk_call,
    )
    chunk_data = json.loads(chunk_result.content)

    assert chunk_data["chunk_count"] == 2
    assert len(chunk_data["chunks"]) == 2
    assert chunk_data["links"] == []
    assert chunk_data["links_summary"]["suppressed"] is True
    assert chunk_data["returned_chars"] <= 6_000


@pytest.mark.asyncio
async def test_browser_extract_empty_content_does_not_create_empty_chunks(tmp_path):
    worker = EmptyContentWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path, conversation_id="conversation-empty")

    content_call = ToolCall(id="call_empty_content", name="BrowserExtractContent", arguments={})
    content_result = await tools["BrowserExtractContent"].call(
        content_call.arguments,
        context,
        content_call,
    )
    content_data = json.loads(content_result.content)

    assert content_data["content_unavailable"] is True
    assert content_data["chunk_count"] == 0
    assert content_data["cache_key"] is None
    denied = await tools["BrowserReadContentChunk"].validate_input({}, context)
    assert denied is not None
    assert denied.allowed is False


@pytest.mark.asyncio
async def test_browser_tools_block_private_urls(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path)

    denied = await tools["BrowserOpen"].validate_input({"url": "http://127.0.0.1:9222"}, context)

    assert denied is not None
    assert denied.allowed is False


def test_tool_runtime_config_can_opt_into_private_browser_fixtures(tmp_path):
    config = ToolRuntimeConfig.from_values(
        workspace_root=tmp_path,
        web_blocked_domains=(),
        web_allow_private_hosts=True,
    )

    assert config.web_blocked_domains == ()
    assert config.web_allow_private_hosts is True


def test_tool_registry_exposes_browser_tools():
    registry = DIContainer().get_tool_registry()
    names = {tool.definition.name for tool in registry.list_enabled()}

    assert {
        "BrowserSearch",
        "BrowserOpen",
        "BrowserListTabs",
        "BrowserExtractContent",
        "BrowserReadContentChunk",
        "BrowserGetHtml",
        "BrowserGetElementMap",
        "BrowserClick",
        "BrowserType",
        "BrowserScreenshot",
        "BrowserCloseTab",
        "BrowserReadConsole",
        "BrowserScript",
        "BrowserScroll",
        "BrowserReload",
        "BrowserHistory",
        "BrowserSwitchTab",
        "BrowserWait",
        "BrowserAct",
    } <= names


@pytest.mark.asyncio
async def test_browser_element_map_and_act_tools(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path)

    map_call = ToolCall(id="call_map", name="BrowserGetElementMap", arguments={})
    map_result = await tools["BrowserGetElementMap"].call(map_call.arguments, context, map_call)
    map_data = json.loads(map_result.content)

    assert map_data["type"] == "browser_element_map"
    assert map_data["elements"][0]["node_id"] == "pa_link"

    act_call = ToolCall(
        id="call_act",
        name="BrowserAct",
        arguments={"node_id": "pa_link", "action": "click"},
    )
    act_result = await tools["BrowserAct"].call(act_call.arguments, context, act_call)
    act_data = json.loads(act_result.content)

    assert act_data["type"] == "browser_action"
    assert act_data["last_action"]["node_id"] == "pa_link"
    assert act_data["last_action"]["action"] == "click"


@pytest.mark.asyncio
async def test_browser_control_tools_execute_with_strict_targets(tmp_path):
    worker = FakeBrowserWorker()
    tools = {tool.definition.name: tool for tool in create_browser_tools(worker)}
    context = _tool_context(tmp_path)

    alias_denied = await tools["BrowserClick"].validate_input(
        {"page_id": "page_one", "window_id": "page_two", "node_id": "pa_link"},
        context,
    )
    assert alias_denied is not None
    assert alias_denied.allowed is False

    script_denied = await tools["BrowserScript"].validate_input(
        {"mode": "cdp", "cdp_method": "Target.closeTarget"},
        context,
    )
    assert script_denied is not None
    assert script_denied.allowed is False

    calls = [
        ToolCall(id="click", name="BrowserClick", arguments={"node_id": "pa_link"}),
        ToolCall(id="type", name="BrowserType", arguments={"node_id": "pa_input", "mode": "fill", "text": "hello"}),
        ToolCall(id="screenshot", name="BrowserScreenshot", arguments={"format": "png"}),
        ToolCall(id="console", name="BrowserReadConsole", arguments={"levels": ["log"], "limit": 5}),
        ToolCall(id="script", name="BrowserScript", arguments={"mode": "evaluate", "script": "() => 42"}),
        ToolCall(id="scroll", name="BrowserScroll", arguments={"delta_y": 200}),
        ToolCall(id="reload", name="BrowserReload", arguments={}),
        ToolCall(id="history", name="BrowserHistory", arguments={"direction": "back"}),
        ToolCall(id="switch", name="BrowserSwitchTab", arguments={"page_id": "page_example"}),
        ToolCall(id="wait", name="BrowserWait", arguments={"timeout_ms": 10}),
        ToolCall(id="close", name="BrowserCloseTab", arguments={"page_id": "page_example"}),
    ]

    results = {
        call.name: json.loads((await tools[call.name].call(call.arguments, context, call)).content)
        for call in calls
    }

    assert results["BrowserClick"]["type"] == "browser_click"
    assert results["BrowserClick"]["last_action"]["node_id"] == "pa_link"
    assert results["BrowserType"]["type"] == "browser_type"
    assert results["BrowserType"]["last_action"]["text"] == "hello"
    assert results["BrowserScreenshot"]["type"] == "browser_screenshot"
    assert results["BrowserScreenshot"]["image_data"] == "aW1hZ2U="
    assert results["BrowserReadConsole"]["entries"][0]["text"] == "ready"
    assert results["BrowserScript"]["result"] == 42
    assert results["BrowserScroll"]["type"] == "browser_scroll"
    assert results["BrowserReload"]["type"] == "browser_reload"
    assert results["BrowserHistory"]["direction"] == -1
    assert results["BrowserSwitchTab"]["active_tab_id"] == "page_example"
    assert results["BrowserCloseTab"]["closed_page_id"] == "page_example"


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
        session["results"] = [
            {
                "index": 1,
                "title": "Example Domain",
                "url": "https://example.com/",
                "snippet": "Example",
            }
        ]
        return {
            "type": "browser_search",
            "query": query,
            "search_url": self.search_url(query),
            "results": session["results"][:max_results],
        }

    async def open(
        self,
        *,
        conversation_id: str,
        url=None,
        result_index=None,
        search_id=None,
        tool_call_id=None,
    ):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session["results"][int(result_index) - 1]["url"]
        session["opened"] = target
        return {
            "type": "browser_open",
            "url": target,
            "final_url": target,
            "title": "Example Domain",
            "page_id": "page_example",
            "window_id": "page_example",
        }

    async def list_tabs(self, *, conversation_id: str, max_tabs: int):
        session = self.sessions.setdefault(conversation_id, {})
        target = session.get("opened")
        tabs = []
        if target:
            tabs.append(
                {
                    "index": 1,
                    "page_id": "page_example",
                    "window_id": "page_example",
                    "url": target,
                    "final_url": target,
                    "domain": "example.com",
                    "title": "Example Domain",
                    "summary": "Example Domain",
                    "source_search_id": None,
                    "is_last_open": True,
                    "is_current_page": True,
                }
            )
        return {
            "type": "browser_tabs",
            "tab_count": len(tabs),
            "max_tabs": max_tabs,
            "current_url": target,
            "last_open_page_id": "page_example" if target else None,
            "last_open_window_id": "page_example" if target else None,
            "tabs": tabs[:max_tabs],
        }

    async def extract_content(
        self,
        *,
        conversation_id: str,
        url=None,
        page_id=None,
        max_chars: int,
        include_links: bool,
    ):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session.get("opened") or "https://example.com/"
        session["opened"] = target
        return {
            "type": "browser_extract_content",
            "url": target,
            "title": "Example Domain",
            "page_id": page_id or "page_example",
            "window_id": page_id or "page_example",
            "content": "Example Domain\nThis domain is for use in illustrative examples."[
                :max_chars
            ],
            "links": [{"url": "https://www.iana.org/domains/example", "text": "More information"}]
            if include_links
            else [],
            "truncated": False,
        }

    async def get_html(self, *, conversation_id: str, url=None, page_id=None, max_chars: int):
        session = self.sessions.setdefault(conversation_id, {})
        target = url or session.get("opened") or "https://example.com/"
        session["opened"] = target
        html = "<html><body><h1>Example Domain</h1></body></html>"
        return {
            "type": "browser_get_html",
            "url": target,
            "title": "Example Domain",
            "page_id": page_id or "page_example",
            "window_id": page_id or "page_example",
            "html": html[:max_chars],
            "truncated": False,
        }

    async def view_snapshot(self, *, browser_id: str, width: int, height: int):
        session = self.sessions.setdefault(browser_id, {})
        target = session.get("opened") or "https://example.com/"
        return {
            "type": "browser_view",
            "browser_id": browser_id,
            "url": target,
            "title": "Example Domain",
            "css_fidelity": "original",
            "element_map": [
                {
                    "node_id": "pa_link",
                    "role": "link",
                    "tag": "a",
                    "text": "More information",
                    "href": "https://www.iana.org/domains/example",
                    "selector": "html > body > a:nth-of-type(1)",
                }
            ],
        }

    async def view_act(
        self,
        *,
        browser_id: str,
        node_id: str,
        action: str,
        width: int,
        height: int,
        value=None,
        key=None,
    ):
        view = await self.view_snapshot(browser_id=browser_id, width=width, height=height)
        view["last_action"] = {"node_id": node_id, "action": action, "value": value, "key": key}
        return view

    async def click(
        self,
        *,
        conversation_id: str,
        page_id=None,
        node_id=None,
        x=None,
        y=None,
        width: int = 1024,
        height: int = 720,
        button: str = "left",
        click_count: int = 1,
        modifiers=None,
        wait_after_ms: int = 250,
    ):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_click",
                "page_id": page_id or "page_example",
                "window_id": page_id or "page_example",
                "runtime": "chrome_cdp",
                "render_mode": "pixel",
                "active_tab_id": page_id or "page_example",
                "navigated": False,
                "last_action": {
                    "action": "click",
                    "node_id": node_id,
                    "x": x,
                    "y": y,
                    "button": button,
                    "click_count": click_count,
                    "modifiers": modifiers or [],
                },
            }
        )
        return view

    async def type_input(
        self,
        *,
        conversation_id: str,
        page_id=None,
        node_id=None,
        mode: str = "type",
        text=None,
        key=None,
        clear: bool = False,
        delay_ms: int = 0,
        submit: bool = False,
        width: int = 1024,
        height: int = 720,
    ):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_type",
                "page_id": page_id or "page_example",
                "window_id": page_id or "page_example",
                "runtime": "chrome_cdp",
                "render_mode": "pixel",
                "active_tab_id": page_id or "page_example",
                "navigated": False,
                "last_action": {
                    "action": mode,
                    "node_id": node_id,
                    "text": text,
                    "key": key,
                    "clear": clear,
                    "submit": submit,
                },
            }
        )
        return view

    async def screenshot(
        self,
        *,
        conversation_id: str,
        page_id=None,
        width: int = 1024,
        height: int = 720,
        full_page: bool = False,
        image_format: str = "png",
        quality=None,
    ):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_screenshot",
                "page_id": page_id or "page_example",
                "window_id": page_id or "page_example",
                "runtime": "chrome_cdp",
                "render_mode": "pixel",
                "active_tab_id": page_id or "page_example",
                "navigated": False,
                "image_data": "aW1hZ2U=",
                "image_mime_type": "image/png",
                "can_capture": True,
                "viewport_width": width,
                "viewport_height": height,
                "full_page": full_page,
            }
        )
        return view

    async def close_tab(self, *, conversation_id: str, page_id=None, max_tabs: int = 20):
        return {
            "type": "browser_close_tab",
            "closed_page_id": page_id or "page_example",
            "closed_window_id": page_id or "page_example",
            "closed": True,
            "tab_count": 0,
            "tabs": [],
            "max_tabs": max_tabs,
        }

    async def read_console(
        self,
        *,
        conversation_id: str,
        page_id=None,
        levels=None,
        since_id=None,
        limit: int = 100,
        clear: bool = False,
    ):
        return {
            "type": "browser_console",
            "page_id": page_id or "page_example",
            "window_id": page_id or "page_example",
            "url": "https://example.com/",
            "title": "Example Domain",
            "runtime": "chrome_cdp",
            "render_mode": "pixel",
            "active_tab_id": page_id or "page_example",
            "navigated": False,
            "entries": [{"id": 1, "level": "log", "text": "ready", "source": "console"}][:limit],
            "next_since_id": 1,
            "cleared": clear,
        }

    async def script(
        self,
        *,
        conversation_id: str,
        page_id=None,
        mode: str = "evaluate",
        script=None,
        args=None,
        cdp_method=None,
        cdp_params=None,
        timeout_ms: int = 5000,
    ):
        return {
            "type": "browser_script",
            "page_id": page_id or "page_example",
            "window_id": page_id or "page_example",
            "url": "https://example.com/",
            "title": "Example Domain",
            "runtime": "chrome_cdp",
            "render_mode": "pixel",
            "active_tab_id": page_id or "page_example",
            "navigated": False,
            "mode": mode,
            "cdp_method": cdp_method,
            "result": 42,
            "result_text": "42",
            "truncated": False,
        }

    async def scroll(self, *, conversation_id: str, page_id=None, delta_x=0, delta_y=600, width: int = 1024, height: int = 720):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update({"type": "browser_scroll", "page_id": page_id or "page_example", "window_id": page_id or "page_example"})
        return view

    async def reload(self, *, conversation_id: str, page_id=None, width: int = 1024, height: int = 720):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update({"type": "browser_reload", "page_id": page_id or "page_example", "window_id": page_id or "page_example"})
        return view

    async def history(self, *, conversation_id: str, page_id=None, direction: int = -1, width: int = 1024, height: int = 720):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_history",
                "page_id": page_id or "page_example",
                "window_id": page_id or "page_example",
                "direction": direction,
            }
        )
        return view

    async def switch_tab(self, *, conversation_id: str, page_id: str, max_tabs: int = 20):
        data = await self.list_tabs(conversation_id=conversation_id, max_tabs=max_tabs)
        data.update({"type": "browser_switch_tab", "page_id": page_id, "window_id": page_id, "active_tab_id": page_id})
        return data

    async def wait(self, *, conversation_id: str, page_id=None, timeout_ms: int = 1000, state=None, width: int = 1024, height: int = 720):
        view = await self.view_snapshot(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_wait",
                "page_id": page_id or "page_example",
                "window_id": page_id or "page_example",
                "timeout_ms": timeout_ms,
                "state": state,
            }
        )
        return view


class LongNoisyContentWorker(FakeBrowserWorker):
    async def extract_content(
        self,
        *,
        conversation_id: str,
        url=None,
        page_id=None,
        max_chars: int,
        include_links: bool,
    ):
        article = "\n\n".join(
            f"Paragraph {index}. Enterprise AI systems need reliable data, governance, "
            "evaluation, and careful operational rollout."
            for index in range(90)
        )
        links = [
            {
                "url": f"https://www.forbes.com/vetted/category-{index}/",
                "text": f"Category {index}",
            }
            for index in range(40)
        ]
        return {
            "type": "browser_extract_content",
            "url": "https://example.com/noisy",
            "title": "Noisy Article",
            "page_id": page_id or "page_noisy",
            "window_id": page_id or "page_noisy",
            "content": article[:max_chars],
            "links": links if include_links else [],
            "truncated": len(article) > max_chars,
        }


class EmptyContentWorker(FakeBrowserWorker):
    async def extract_content(
        self,
        *,
        conversation_id: str,
        url=None,
        page_id=None,
        max_chars: int,
        include_links: bool,
    ):
        return {
            "type": "browser_extract_content",
            "url": "https://example.com/empty",
            "title": "",
            "page_id": page_id or "page_empty",
            "window_id": page_id or "page_empty",
            "content": "",
            "extraction_method": "dom_text_failed",
            "links": [],
            "buttons": [],
            "truncated": False,
        }


class FakeBrowser:
    def __init__(self, context=None):
        self.context = context
        self.closed = False

    def is_connected(self):
        return not self.closed

    async def new_context(self):
        return self.context or FakeContext()

    async def close(self):
        self.closed = True
        return None


class FakeConnection:
    def __init__(self):
        self.stopped = False

    async def stop_async(self):
        self.stopped = True


class FakeImpl:
    def __init__(self, connection):
        self._connection = connection


class FakeCdpBrowser(FakeBrowser):
    def __init__(self):
        super().__init__()
        self.connection = FakeConnection()
        self._impl_obj = FakeImpl(self.connection)


class FakeContext:
    def __init__(self, page=None, page_factory=None):
        self.page = page
        self.page_factory = page_factory
        self.closed = False
        self.pages: list[FakePage] = []

    async def new_page(self):
        page = self.page_factory() if self.page_factory else self.page or FakePage()
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True
        return None


class TargetAlreadyLoadedContext(FakeContext):
    def __init__(self, page=None):
        super().__init__(page=page or FakePage())
        self.pages = [self.page]
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        raise RuntimeError(
            "BrowserContext.new_page: Protocol error (Target.createTarget): TargetAlreadyLoaded"
        )


class FakeStylesheetResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/css; charset=utf-8"}


class FakeStylesheetClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def get(self, _href: str):
        self.calls += 1
        return FakeStylesheetResponse(self.text)


class FakePage:
    def __init__(self):
        self.closed = False
        self.url = "about:blank"

    def is_closed(self):
        return self.closed

    def set_default_timeout(self, _timeout_ms):
        return None

    async def close(self):
        self.closed = True
        return None

    async def title(self):
        return ""


class ScriptedPage(FakePage):
    def __init__(self, *, fail_on_goto: bool = False):
        super().__init__()
        self.fail_on_goto = fail_on_goto
        self.goto_history: list[str] = []
        self.viewport_size: dict[str, int] | None = None
        self.goto_wait_until: str | None = None

    async def goto(self, url, wait_until=None, timeout=None):
        if self.fail_on_goto:
            raise RuntimeError("navigation timed out")
        self.goto_wait_until = wait_until
        self.url = url
        self.goto_history.append(url)
        return None

    async def set_viewport_size(self, viewport):
        self.viewport_size = viewport
        return None

    async def wait_for_timeout(self, _timeout_ms):
        return None

    async def wait_for_load_state(self, state, timeout=None):
        return None

    async def evaluate(self, _script, arg=None):
        if isinstance(arg, dict) and "maxResults" in arg:
            if "first+query" in self.url:
                return [
                    {
                        "title": "Source A",
                        "url": "https://source-a.test/article",
                        "snippet": "First source",
                    }
                ]
            return [
                {
                    "title": "Source B",
                    "url": "https://source-b.test/article",
                    "snippet": "Second source",
                }
            ]
        return f"Content from {self.url}"

    async def title(self):
        if "source-a.test" in self.url:
            return "Source A"
        if "source-b.test" in self.url:
            return "Source B"
        return "Search"

    async def content(self):
        return f"<html><body>{self.url}</body></html>"

    async def screenshot(self, **_kwargs):
        return b"browser-image"


class StyleReadyPage(ScriptedPage):
    def __init__(self):
        super().__init__()
        self.wait_load_states: list[str] = []
        self.style_ready_checks = 0

    async def wait_for_load_state(self, state, timeout=None):
        self.wait_load_states.append(state)
        return None

    async def content(self):
        return '<html><head><link rel="stylesheet" href="/app.css"></head><body><main>Styled</main></body></html>'

    async def evaluate(self, script, arg=None):
        script_text = str(script)
        if "personagentStyleReadyProbe" in script_text:
            self.style_ready_checks += 1
            return {
                "style_ready": True,
                "stylesheet_count": 1,
                "stylesheet_loaded_count": 1,
                "fonts_ready": True,
            }
        if "navigator.userAgent" in script_text:
            return "LightPanda/1.0"
        if "data-pa-node-id" in script_text and "mapped" in script_text:
            return []
        if "scroll_x" in script_text and "scroll_y" in script_text:
            return {"scroll_x": 0, "scroll_y": 0}
        return await super().evaluate(script, arg)


class StyleFailurePage(StyleReadyPage):
    async def evaluate(self, script, arg=None):
        script_text = str(script)
        if "personagentStyleReadyProbe" in script_text:
            self.style_ready_checks += 1
            return {
                "style_ready": False,
                "stylesheet_count": 1,
                "stylesheet_loaded_count": 0,
                "fonts_ready": True,
            }
        if "personagent-css-fidelity" in script_text:
            return '<!doctype html><html><head><meta name="personagent-css-fidelity" content="computed"></head><body style="display:block">Computed</body></html>'
        return await super().evaluate(script, arg)


class StaleNodeActionPage(ScriptedPage):
    def __init__(self):
        super().__init__()
        self.action_arg: dict[str, object] | None = None
        self.element_map_calls = 0

    async def evaluate(self, script, arg=None):
        if isinstance(arg, dict) and "nodeId" in arg:
            self.action_arg = arg
            return {
                "ok": True,
                "node_id": arg["nodeId"],
                "action": arg["action"],
                "url": self.url,
                "selector": arg.get("selector"),
                "tag": "A",
                "bounds": {"x": 930, "y": 24, "width": 76, "height": 34},
            }
        script_text = str(script)
        if "data-pa-node-id" in script_text and "mapped" in script_text:
            self.element_map_calls += 1
            return []
        if "navigator.userAgent" in script_text:
            return "Chrome"
        return await super().evaluate(script, arg)


class PopupScrollPage(ScriptedPage):
    def __init__(self):
        super().__init__()
        self.popup_evaluations = 0
        self.scroll_evaluations = 0
        self.scrolled = False

    async def evaluate(self, script, arg=None):
        if isinstance(arg, dict) and "maxSteps" in arg:
            self.scroll_evaluations += 1
            self.scrolled = True
            return {
                "steps": 4,
                "scroll_y": 3200,
                "scroll_height": 4000,
                "viewport_height": 800,
                "at_bottom": True,
            }
        if "clicked_count" in str(script) and "clicked_labels" in str(script):
            self.popup_evaluations += 1
            if self.popup_evaluations == 1:
                return {"clicked_count": 1, "clicked_labels": ["Accept all"]}
            return {"clicked_count": 0, "clicked_labels": []}
        if "selected_tag" in str(script) and "querySelectorAll" in str(script):
            suffix = "after incremental scroll." if self.scrolled else "before scroll."
            return {
                "content": f"Loaded article body {suffix}",
                "selected_tag": "article",
                "score": 2000,
            }
        return await super().evaluate(script, arg)


class PartialTimeoutPage(ScriptedPage):
    async def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        self.goto_history.append(url)
        raise RuntimeError("Page.goto: Timeout 30000ms exceeded.")
