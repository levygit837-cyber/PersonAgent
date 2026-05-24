"""Unit tests for BrowserSnapshot extracted from lightpanda.py (Slice 5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from personagent.infrastructure.browser.snapshot import BrowserSnapshot

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubPage:
    def __init__(
        self,
        url: str = "https://example.com",
        *,
        user_agent: str = "lightpanda/1.0",
        title: str = "Example",
        html: str = "<html><head></head><body></body></html>",
    ) -> None:
        self.url = url
        self._user_agent = user_agent
        self._title = title
        self._html = html
        self.viewport_size: dict[str, int] | None = None

    async def wait_for_timeout(self, ms: int) -> None:
        pass

    async def wait_for_load_state(self, state: str, *, timeout: int = 30_000) -> None:
        pass

    async def screenshot(self, **kwargs: Any) -> bytes:
        return b"\x89PNG_fake"

    async def evaluate(self, script: str, args: Any = None) -> Any:
        return None

    async def content(self) -> str:
        return self._html


class _StubOpenedPage:
    def __init__(self, page_id: str, url: str, title: str = "") -> None:
        self.page_id = page_id
        self.url = url
        self.final_url = url
        self.title = title
        self.extraction_count = 0


class _StubSession:
    def __init__(
        self, page: _StubPage | None = None, page_id: str = "p1"
    ) -> None:
        self.current_page_id = page_id
        self.last_open_page_id = page_id
        self.current_url = "https://example.com"
        self.page = page or _StubPage()
        self.pages: dict[str, _StubPage] = {page_id: self.page}
        self._touched = False
        self.updated_at = 100.0

    def touch(self) -> None:
        self._touched = True


class _StubArtifact:
    def __init__(self) -> None:
        self.artifact_id = "art-123"
        self.url = "https://artifacts.example.com/art-123"


class _StubWorker:
    """Minimal stub of LightPandaBrowserWorker for BrowserSnapshot tests."""

    def __init__(
        self,
        session: _StubSession | None = None,
        page: _StubPage | None = None,
    ) -> None:
        self._session = session or _StubSession(page=page)
        self._page = page or self._session.page
        self.timeout_ms = 5_000
        self.session_ttl_seconds = 600
        self.artifact_root = None
        self._element_map_cache: dict[str, list[Any]] = {}
        self._opened_pages_cache: dict[str, list[Any]] = {}
        self._sessions: dict[str, _StubSession] = {}
        self._current_url_cache: dict[str, str] = {}
        self._stylesheet_cache: dict[str, tuple[float, str]] = {}
        self._stylesheet_cache_ttl_seconds = 900.0
        self._max_stylesheet_cache_entries = 256
        from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache
        self._snapshot_cache = SnapshotCache(max_entries=16, ttl_seconds=180.0)
        self._stylesheet_disk_cache = StylesheetDiskCache.__new__(StylesheetDiskCache)
        self._stylesheet_disk_cache._cache_dir = None
        self._stylesheet_disk_cache._max_entries = 256

    async def _get_session(self, browser_id: str) -> _StubSession:
        return self._session

    def _preferred_session_page(self, session: Any) -> _StubPage:
        return self._page

    def _ensure_session_page_alias(
        self, browser_id: str, session: Any, *, page: Any = None
    ) -> str:
        return session.current_page_id or browser_id

    async def _set_page_viewport(self, page: Any, w: int, h: int) -> None:
        page.viewport_size = {"width": w, "height": h}

    async def _install_cooperation_capture(
        self, page: Any, browser_id: str, tab_id: str
    ) -> None:
        pass

    async def _wait_for_page_visual_ready(self, page: Any) -> dict[str, Any]:
        return {
            "style_ready": True,
            "stylesheet_count": 0,
            "stylesheet_loaded_count": 0,
            "fonts_ready": True,
        }

    async def _wait_for_page_load_complete(
        self, page: Any, *, timeout_ms: int = 5_000
    ) -> None:
        pass

    async def _safe_title(self, page: Any) -> str:
        return getattr(page, "_title", "")

    async def _safe_user_agent(self, page: Any) -> str:
        return getattr(page, "_user_agent", "")

    async def _safe_html(self, page: Any) -> str:
        return getattr(page, "_html", "")

    async def _safe_scroll_state(self, page: Any) -> dict[str, Any]:
        return {"scroll_x": 0, "scroll_y": 0}

    async def _evaluate_page(self, page: Any, script: str, args: Any = None) -> Any:
        return None

    async def _drain_cooperation_events(
        self, page: Any, browser_id: str, tab_id: str
    ) -> list[dict[str, Any]]:
        return []

    def _remember_current_url(self, browser_id: str, url: str) -> None:
        self._current_url_cache[browser_id] = url

    async def _html_or_empty_page(
        self, page: Any, *, fallback_url: str
    ) -> tuple[str, str]:
        html = getattr(page, "_html", "")
        return html, "stub"

    async def _page_frames(self, page: Any) -> list[Any]:
        return [page]

    def _main_frame(self, page: Any) -> Any:
        return page

    def _frame_id(self, frame: Any, index: int) -> str:
        return f"frame-{index}"

    async def _frame_viewport_offset(self, frame: Any) -> tuple[int, int]:
        return (0, 0)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    page: _StubPage | None = None,
    session: _StubSession | None = None,
) -> tuple[BrowserSnapshot, _StubWorker]:
    worker = _StubWorker(session=session, page=page)
    snapshot = BrowserSnapshot(worker)
    return snapshot, worker


# ---------------------------------------------------------------------------
# Tests — enrich_browser_element_map
# ---------------------------------------------------------------------------


class TestEnrichBrowserElementMap:
    def test_enriches_node_id_and_adds_stable_key(self):
        snap, _ = _make_snapshot()
        raw = [{"node_id": " n1 ", "selector": "div.foo", "role": "button", "text": "Go"}]
        result = snap.enrich_browser_element_map(raw, browser_id="b1", tab_id="t1")
        assert len(result) == 1
        item = result[0]
        assert item["node_id"] == "n1"
        assert item["tab_id"] == "t1"
        assert item["frame_id"] == "main"
        assert item["interactable"] is True
        assert "stable_key" in item

    def test_caps_at_220_elements(self):
        snap, _ = _make_snapshot()
        raw = [{"node_id": f"n{i}", "selector": f"div.e{i}", "role": "generic", "text": ""} for i in range(300)]
        result = snap.enrich_browser_element_map(raw, browser_id="b1", tab_id="t1")
        assert len(result) == 220

    def test_non_dict_items_are_skipped(self):
        snap, _ = _make_snapshot()
        raw = [42, None, {"node_id": "n1", "selector": "div"}]
        result = snap.enrich_browser_element_map(raw, browser_id="b1", tab_id="t1")
        assert len(result) == 1

    def test_interactable_roles(self):
        snap, _ = _make_snapshot()
        for role in ["link", "button", "input", "textbox", "select", "checkbox", "radio", "tab"]:
            raw = [{"node_id": "n1", "selector": "x", "role": role, "text": ""}]
            result = snap.enrich_browser_element_map(raw, browser_id="b1", tab_id="t1")
            assert result[0]["interactable"] is True, f"{role} should be interactable"

    def test_non_interactable_role(self):
        snap, _ = _make_snapshot()
        raw = [{"node_id": "n1", "selector": "x", "role": "generic", "text": ""}]
        result = snap.enrich_browser_element_map(raw, browser_id="b1", tab_id="t1")
        assert result[0]["interactable"] is False


# ---------------------------------------------------------------------------
# Tests — browser_tabs_snapshot
# ---------------------------------------------------------------------------


class TestBrowserTabsSnapshot:
    def test_returns_opened_pages_when_available(self):
        snap, worker = _make_snapshot()
        worker._opened_pages_cache["b1"] = [
            _StubOpenedPage("p1", "https://a.com", "Page A"),
            _StubOpenedPage("p2", "https://b.com", "Page B"),
        ]
        session = _StubSession(page_id="p1")
        tabs = snap.browser_tabs_snapshot("b1", session, current_url="https://a.com", title="Page A", runtime="chrome_cdp")
        assert len(tabs) == 2
        assert tabs[0]["tab_id"] == "p1"
        assert tabs[0]["active"] is True
        assert tabs[1]["tab_id"] == "p2"
        assert tabs[1]["active"] is False

    def test_returns_fallback_tab_when_no_opened_pages(self):
        snap, worker = _make_snapshot()
        session = _StubSession(page_id="default")
        tabs = snap.browser_tabs_snapshot("b1", session, current_url="https://x.com", title="X", runtime="lightpanda")
        assert len(tabs) == 1
        assert tabs[0]["tab_id"] == "default"
        assert tabs[0]["url"] == "https://x.com"
        assert tabs[0]["active"] is True


# ---------------------------------------------------------------------------
# Tests — stylesheet_hrefs (static)
# ---------------------------------------------------------------------------


class TestStylesheetHrefs:
    def test_extracts_stylesheet_links(self):
        html = '<html><head><link rel="stylesheet" href="/style.css"></head></html>'
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert hrefs == ["https://example.com/style.css"]

    def test_extracts_preload_as_style(self):
        html = '<html><head><link rel="preload" as="style" href="/app.css"></head></html>'
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert hrefs == ["https://example.com/app.css"]

    def test_extracts_css_extension(self):
        html = '<html><head><link href="/main.css" rel="prefetch"></head></html>'
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert hrefs == ["https://example.com/main.css"]

    def test_ignores_non_stylesheet_links(self):
        html = '<html><head><link rel="icon" href="/favicon.ico"></head></html>'
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert hrefs == []

    def test_respects_max_hrefs(self):
        html = """<html><head>
        <link rel="stylesheet" href="/a.css">
        <link rel="stylesheet" href="/b.css">
        <link rel="stylesheet" href="/c.css">
        </head></html>"""
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=2)
        assert len(hrefs) == 2

    def test_deduplicates(self):
        html = """<html><head>
        <link rel="stylesheet" href="/a.css">
        <link rel="stylesheet" href="/a.css">
        </head></html>"""
        hrefs = BrowserSnapshot.stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert len(hrefs) == 1


# ---------------------------------------------------------------------------
# Tests — html_attrs (static)
# ---------------------------------------------------------------------------


class TestHtmlAttrs:
    def test_parses_double_quoted_attrs(self):
        attrs = BrowserSnapshot.html_attrs('<link rel="stylesheet" href="/a.css">')
        assert attrs["rel"] == "stylesheet"
        assert attrs["href"] == "/a.css"

    def test_parses_single_quoted_attrs(self):
        attrs = BrowserSnapshot.html_attrs("<link rel='stylesheet' href='/b.css'>")
        assert attrs["rel"] == "stylesheet"
        assert attrs["href"] == "/b.css"


# ---------------------------------------------------------------------------
# Tests — rewrite_css_urls (static)
# ---------------------------------------------------------------------------


class TestRewriteCssUrls:
    def test_rewrites_relative_urls(self):
        css = "body { background: url(../images/bg.png); }"
        result = BrowserSnapshot.rewrite_css_urls(css, "https://example.com/assets/style.css")
        assert "https://example.com/images/bg.png" in result

    def test_preserves_absolute_urls(self):
        css = "body { background: url(https://cdn.example.com/bg.png); }"
        result = BrowserSnapshot.rewrite_css_urls(css, "https://example.com/assets/style.css")
        assert "https://cdn.example.com/bg.png" in result

    def test_preserves_data_urls(self):
        css = "body { background: url(data:image/png;base64,abc); }"
        result = BrowserSnapshot.rewrite_css_urls(css, "https://example.com/style.css")
        assert "data:image/png;base64,abc" in result


# ---------------------------------------------------------------------------
# Tests — css_fidelity (static)
# ---------------------------------------------------------------------------


class TestCssFidelity:
    def test_pixel_for_screenshot_mode(self):
        assert BrowserSnapshot.css_fidelity(html="<html>", render_mode="pixel") == "pixel"

    def test_computed_for_computed_html(self):
        assert BrowserSnapshot.css_fidelity(html="<html>", render_mode="computed_html") == "computed"

    def test_fallback_for_empty_html(self):
        assert BrowserSnapshot.css_fidelity(html="", render_mode="html_mirror") == "fallback_html"

    def test_embedded_when_count_positive(self):
        assert BrowserSnapshot.css_fidelity(html="<html>", render_mode="html_mirror", embedded_stylesheet_count=1) == "embedded"

    def test_original_when_stylesheet_link_present(self):
        html = '<html><head><link rel="stylesheet" href="/a.css"></head></html>'
        assert BrowserSnapshot.css_fidelity(html=html, render_mode="html_mirror") == "original"

    def test_fallback_when_no_styles(self):
        assert BrowserSnapshot.css_fidelity(html="<html><body>hi</body></html>", render_mode="html_mirror") == "fallback_html"


# ---------------------------------------------------------------------------
# Tests — browser_view_snapshot (full pipeline)
# ---------------------------------------------------------------------------


class TestBrowserViewSnapshot:
    @pytest.mark.asyncio
    async def test_returns_browser_view_dict(self):
        snap, worker = _make_snapshot()
        session = worker._session

        async def _mock_html_embed(html, url):
            return html, {"stylesheet_count": 0, "embedded_stylesheet_count": 0, "stylesheet_cached_count": 0}

        worker._html_with_embedded_stylesheet_fallbacks = _mock_html_embed

        with patch("personagent.infrastructure.browser.snapshot.store_text_artifact", return_value=_StubArtifact()), \
             patch("personagent.infrastructure.browser.snapshot.store_bytes_artifact", return_value=None):
            result = await snap.browser_view_snapshot(
                "b1", session, width=800, height=600
            )

        assert result["type"] == "browser_view"
        assert result["browser_id"] == "b1"
        assert result["url"] == "https://example.com"
        assert result["title"] == "Example"
        assert result["render_mode"] == "html_mirror"
        assert result["runtime"] == "lightpanda"
        assert "element_map" in result
        assert "tabs" in result
        assert "frame_tree" in result
        assert session._touched is True

    @pytest.mark.asyncio
    async def test_cached_mode_returns_cached_snapshot(self):
        snap, worker = _make_snapshot()
        session = worker._session

        from personagent.infrastructure.browser.cache import SnapshotCache
        cache_key = SnapshotCache.cache_key("b1", "https://example.com", "p1", 800, 600)
        cached_view = {"type": "browser_view", "cached": True, "url": "https://example.com"}
        worker._snapshot_cache.store(cache_key, cached_view)

        result = await snap.browser_view_snapshot(
            "b1", session, width=800, height=600, cache_mode="prefer_cached"
        )
        assert result.get("cached") is True


# ---------------------------------------------------------------------------
# Tests — panel_session_tabs
# ---------------------------------------------------------------------------


class TestPanelSessionTabs:
    @pytest.mark.asyncio
    async def test_returns_tabs_for_active_sessions(self):
        snap, worker = _make_snapshot()
        page = _StubPage(url="https://active.example.com", title="Active")
        session = _StubSession(page=page, page_id="pg1")
        session.current_url = "https://active.example.com"
        session.updated_at = 200.0
        worker._sessions["browser:conv1"] = session

        tabs = await snap.panel_session_tabs(max_tabs=5, exclude_conversation_id="other")
        assert len(tabs) == 1
        assert tabs[0]["url"] == "https://active.example.com"
        assert tabs[0]["browser_id"] == "browser:conv1"

    @pytest.mark.asyncio
    async def test_excludes_specified_conversation(self):
        snap, worker = _make_snapshot()
        page = _StubPage(url="https://excluded.example.com")
        session = _StubSession(page=page)
        session.current_url = "https://excluded.example.com"
        worker._sessions["browser:excluded"] = session

        tabs = await snap.panel_session_tabs(max_tabs=5, exclude_conversation_id="browser:excluded")
        assert len(tabs) == 0

    @pytest.mark.asyncio
    async def test_respects_max_tabs(self):
        snap, worker = _make_snapshot()
        for i in range(5):
            page = _StubPage(url=f"https://site{i}.com")
            session = _StubSession(page=page, page_id=f"pg{i}")
            session.current_url = f"https://site{i}.com"
            session.updated_at = float(i)
            worker._sessions[f"browser:conv{i}"] = session

        tabs = await snap.panel_session_tabs(max_tabs=2, exclude_conversation_id="other")
        assert len(tabs) == 2


# ---------------------------------------------------------------------------
# Tests — browser_frame_tree_snapshot
# ---------------------------------------------------------------------------


class TestBrowserFrameTreeSnapshot:
    @pytest.mark.asyncio
    async def test_returns_single_main_frame_by_default(self):
        snap, _ = _make_snapshot()
        page = _StubPage(url="https://example.com")
        tree = await snap.browser_frame_tree_snapshot(page, current_url="https://example.com", title="Example")
        assert len(tree) == 1
        assert tree[0]["frame_id"] == "main"
        assert tree[0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_returns_fallback_for_empty_frames(self):
        snap, worker = _make_snapshot()

        async def _empty_frames(page):
            return []

        worker._page_frames = _empty_frames
        page = _StubPage()
        tree = await snap.browser_frame_tree_snapshot(page, current_url="https://x.com", title="X")
        assert tree[0]["frame_id"] == "main"


# ---------------------------------------------------------------------------
# Tests — backward-compat delegations on worker
# ---------------------------------------------------------------------------


class TestBackwardCompatDelegations:
    def test_worker_stylesheet_hrefs_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        html = '<html><head><link rel="stylesheet" href="/a.css"></head></html>'
        result = LightPandaBrowserWorker._stylesheet_hrefs(html, "https://example.com", max_hrefs=10)
        assert result == ["https://example.com/a.css"]

    def test_worker_html_attrs_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        attrs = LightPandaBrowserWorker._html_attrs('<link rel="stylesheet" href="/a.css">')
        assert attrs["rel"] == "stylesheet"

    def test_worker_css_fidelity_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        result = LightPandaBrowserWorker._css_fidelity(html="<html>", render_mode="pixel")
        assert result == "pixel"

    def test_worker_rewrite_css_urls_delegates(self):
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker
        css = "body { background: url(../bg.png); }"
        result = LightPandaBrowserWorker._rewrite_css_urls(css, "https://example.com/assets/style.css")
        assert "https://example.com/bg.png" in result


# ---------------------------------------------------------------------------
# Tests — html_with_embedded_stylesheet_fallbacks
# ---------------------------------------------------------------------------


class TestHtmlWithEmbeddedStylesheetFallbacks:
    @pytest.mark.asyncio
    async def test_returns_unchanged_for_non_http(self):
        snap, _ = _make_snapshot()
        html = "<html><body>hi</body></html>"
        result_html, stats = await snap.html_with_embedded_stylesheet_fallbacks(html, "about:blank")
        assert result_html == html
        assert stats["stylesheet_count"] == 0

    @pytest.mark.asyncio
    async def test_returns_unchanged_when_no_links(self):
        snap, _ = _make_snapshot()
        html = "<html><body>hi</body></html>"
        result_html, stats = await snap.html_with_embedded_stylesheet_fallbacks(html, "https://example.com")
        assert result_html == html
        assert stats["stylesheet_count"] == 0
