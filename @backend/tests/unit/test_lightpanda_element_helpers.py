"""Unit tests for personagent.infrastructure.browser.element_helpers (Slice 12)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from personagent.infrastructure.browser.cdp.element_helpers import ElementHelpers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker._element_map_cache = {}
    worker.timeout_ms = 30_000
    worker._evaluate_page = AsyncMock(return_value=None)
    return worker


def _make_helpers() -> tuple[ElementHelpers, MagicMock]:
    worker = _make_worker()
    return ElementHelpers(worker), worker


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# element_selector
# ---------------------------------------------------------------------------

class TestElementSelector:
    def test_found(self) -> None:
        helpers, worker = _make_helpers()
        worker._element_map_cache = {
            "b1": [{"node_id": "n1", "selector": "div.foo"}],
        }
        assert helpers.element_selector("b1", "n1") == "div.foo"

    def test_not_found(self) -> None:
        helpers, worker = _make_helpers()
        worker._element_map_cache = {"b1": []}
        assert helpers.element_selector("b1", "n1") == ""

    def test_missing_browser_id(self) -> None:
        helpers, _ = _make_helpers()
        assert helpers.element_selector("missing", "n1") == ""


# ---------------------------------------------------------------------------
# element_target
# ---------------------------------------------------------------------------

class TestElementTarget:
    def test_found(self) -> None:
        helpers, worker = _make_helpers()
        item = {"node_id": "n1", "selector": "div.foo", "text": "hello"}
        worker._element_map_cache = {"b1": [item]}
        assert helpers.element_target("b1", "n1") is item

    def test_empty_node_id(self) -> None:
        helpers, _ = _make_helpers()
        assert helpers.element_target("b1", "") == {}

    def test_not_found(self) -> None:
        helpers, worker = _make_helpers()
        worker._element_map_cache = {"b1": [{"node_id": "n2"}]}
        assert helpers.element_target("b1", "n1") == {}


# ---------------------------------------------------------------------------
# browser_action_target_payload
# ---------------------------------------------------------------------------

class TestBrowserActionTargetPayload:
    def test_with_target(self) -> None:
        target = {
            "node_id": "n1",
            "text": "Click me",
            "role": "button",
            "tag": "button",
            "selector": "#btn",
            "href": "",
            "bounds": {"x": 10, "y": 20},
        }
        payload = ElementHelpers.browser_action_target_payload(target)
        assert payload["node_id"] == "n1"
        assert payload["text"] == "Click me"
        assert payload["bounds"] == {"x": 10, "y": 20}

    def test_empty_target_and_no_fallback(self) -> None:
        assert ElementHelpers.browser_action_target_payload({}) == {}

    def test_fallback_node_id(self) -> None:
        payload = ElementHelpers.browser_action_target_payload(
            {}, fallback_node_id="fallback",
        )
        assert payload["node_id"] == "fallback"


# ---------------------------------------------------------------------------
# page_frames
# ---------------------------------------------------------------------------

class TestPageFrames:
    def test_callable_frames(self) -> None:
        helpers, _ = _make_helpers()
        frame1, frame2 = MagicMock(), MagicMock()
        page = MagicMock()
        page.frames = MagicMock(return_value=[frame1, frame2])
        result = _run(helpers.page_frames(page))
        assert result == [frame1, frame2]

    def test_list_frames(self) -> None:
        helpers, _ = _make_helpers()
        frame1 = MagicMock()
        page = MagicMock()
        page.frames = [frame1]
        result = _run(helpers.page_frames(page))
        assert result == [frame1]

    def test_no_frames_returns_page(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        result = _run(helpers.page_frames(page))
        assert result == [page]


# ---------------------------------------------------------------------------
# main_frame
# ---------------------------------------------------------------------------

class TestMainFrame:
    def test_callable_main_frame(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock()
        page = MagicMock()
        page.main_frame = MagicMock(return_value=frame)
        assert helpers.main_frame(page) is frame

    def test_attribute_main_frame(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock()
        page = MagicMock()
        page.main_frame = frame
        # When main_frame is a MagicMock (not a plain value), callable returns True
        # so it gets called. Let's use a non-callable.
        page.main_frame = "sentinel"
        result = helpers.main_frame(page)
        assert result == "sentinel"

    def test_no_main_frame(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        assert helpers.main_frame(page) is page


# ---------------------------------------------------------------------------
# frame_id
# ---------------------------------------------------------------------------

class TestFrameId:
    def test_deterministic(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.name = "myframe"
        id1 = helpers.frame_id(frame, 0)
        id2 = helpers.frame_id(frame, 0)
        assert id1 == id2
        assert id1.startswith("frame_")

    def test_different_index(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.name = "myframe"
        assert helpers.frame_id(frame, 0) != helpers.frame_id(frame, 1)


# ---------------------------------------------------------------------------
# frame_viewport_offset
# ---------------------------------------------------------------------------

class TestFrameViewportOffset:
    def test_no_frame_element(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock(spec=[])
        assert _run(helpers.frame_viewport_offset(frame)) == (0.0, 0.0)

    def test_with_bounding_box(self) -> None:
        helpers, _ = _make_helpers()
        frame = MagicMock()
        element = MagicMock()
        element.bounding_box = MagicMock(return_value={"x": 10.5, "y": 20.3})
        frame.frame_element = MagicMock(return_value=element)
        result = _run(helpers.frame_viewport_offset(frame))
        assert result == (10.5, 20.3)


# ---------------------------------------------------------------------------
# upload_files
# ---------------------------------------------------------------------------

class TestUploadFiles:
    def test_no_selector(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        result = _run(helpers.upload_files(page, "", ["file.txt"]))
        assert result == {"ok": False, "reason": "selector_not_found"}

    def test_no_files(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        result = _run(helpers.upload_files(page, "#input", []))
        assert result == {"ok": False, "reason": "files_required"}

    def test_no_locator(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        result = _run(helpers.upload_files(page, "#input", ["file.txt"]))
        assert result == {"ok": False, "reason": "locator_unavailable"}


# ---------------------------------------------------------------------------
# drag_between_elements
# ---------------------------------------------------------------------------

class TestDragBetweenElements:
    def test_no_selector(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        result = _run(helpers.drag_between_elements(
            page, "", target_selector="#target", x=None, y=None,
        ))
        assert result == {"ok": False, "reason": "selector_not_found"}

    def test_no_mouse(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=["locator"])
        result = _run(helpers.drag_between_elements(
            page, "#src", target_selector="#target", x=None, y=None,
        ))
        assert result == {"ok": False, "reason": "mouse_unavailable"}


# ---------------------------------------------------------------------------
# set_page_viewport
# ---------------------------------------------------------------------------

class TestSetPageViewport:
    def test_sets_viewport(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.set_viewport_size = MagicMock(return_value=None)
        _run(helpers.set_page_viewport(page, 1920, 1080))
        page.set_viewport_size.assert_called_once_with({"width": 1920, "height": 1080})

    def test_no_set_viewport_size(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        _run(helpers.set_page_viewport(page, 1920, 1080))


# ---------------------------------------------------------------------------
# safe_user_agent
# ---------------------------------------------------------------------------

class TestSafeUserAgent:
    def test_returns_agent(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(return_value="  Mozilla/5.0  ")
        result = _run(helpers.safe_user_agent(MagicMock()))
        assert result == "Mozilla/5.0"

    def test_returns_empty_on_failure(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(side_effect=Exception("fail"))
        result = _run(helpers.safe_user_agent(MagicMock()))
        assert result == ""


# ---------------------------------------------------------------------------
# safe_html
# ---------------------------------------------------------------------------

class TestSafeHtml:
    def test_returns_html(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock()
        page.content = MagicMock(return_value="<html></html>")
        result = _run(helpers.safe_html(page))
        assert result == "<html></html>"

    def test_no_content_attr(self) -> None:
        helpers, _ = _make_helpers()
        page = MagicMock(spec=[])
        result = _run(helpers.safe_html(page))
        assert result == ""


# ---------------------------------------------------------------------------
# safe_scroll_state
# ---------------------------------------------------------------------------

class TestSafeScrollState:
    def test_returns_state(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(return_value={"scroll_x": 100, "scroll_y": 200})
        result = _run(helpers.safe_scroll_state(MagicMock()))
        assert result == {"scroll_x": 100, "scroll_y": 200}

    def test_returns_zero_on_failure(self) -> None:
        helpers, worker = _make_helpers()
        worker._evaluate_page = AsyncMock(side_effect=Exception("fail"))
        result = _run(helpers.safe_scroll_state(MagicMock()))
        assert result == {"scroll_x": 0, "scroll_y": 0}


# ---------------------------------------------------------------------------
# Backward-compat delegations
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_element_selector_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker.element_helpers.element_selector("b1", "n1") == ""

    def test_worker_element_target_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker.element_helpers.element_target("b1", "") == {}

    def test_worker_browser_action_target_payload_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        assert worker.element_helpers.browser_action_target_payload({}) == {}

    def test_worker_main_frame_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = MagicMock(spec=[])
        assert worker.element_helpers.main_frame(page) is page

    def test_worker_frame_id_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        frame = MagicMock()
        frame.url = "https://example.com"
        frame.name = "test"
        result = worker.element_helpers.frame_id(frame, 0)
        assert result.startswith("frame_")
