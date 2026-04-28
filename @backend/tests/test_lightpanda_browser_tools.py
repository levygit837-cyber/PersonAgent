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

    async def goto(self, url, wait_until=None, timeout=None):
        if self.fail_on_goto:
            raise RuntimeError("navigation timed out")
        self.url = url
        self.goto_history.append(url)
        return None

    async def set_viewport_size(self, viewport):
        self.viewport_size = viewport
        return None

    async def wait_for_timeout(self, _timeout_ms):
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
