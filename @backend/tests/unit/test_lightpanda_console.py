"""Unit tests for personagent.infrastructure.browser.console (Slice 9)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.infrastructure.browser.cdp.console import BrowserConsole
from personagent.infrastructure.browser.models import BrowserConsoleEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker() -> MagicMock:
    worker = MagicMock()
    worker._console_cache = {}
    worker._console_sequence = 0
    worker._console_listener_keys = set()
    worker._cooperation_event_cache = {}
    worker._cooperation_listener_keys = set()
    worker._evaluate_page = AsyncMock(return_value=None)
    return worker


def _make_console() -> tuple[BrowserConsole, MagicMock]:
    worker = _make_worker()
    return BrowserConsole(worker), worker


# ---------------------------------------------------------------------------
# record_console_entry
# ---------------------------------------------------------------------------

class TestRecordConsoleEntry:
    def test_basic_record(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "conv1", "page1", level="log", text="hello", source="console",
        )
        assert worker._console_sequence == 1
        entries = worker._console_cache["conv1"]["page1"]
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, BrowserConsoleEntry)
        assert entry.entry_id == 1
        assert entry.page_id == "page1"
        assert entry.level == "log"
        assert entry.text == "hello"
        assert entry.source == "console"

    def test_level_normalized_to_lower(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "c", "p", level="WARNING", text="x", source="console",
        )
        assert worker._console_cache["c"]["p"][0].level == "warning"

    def test_empty_level_defaults_to_log(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "c", "p", level="", text="x", source="console",
        )
        assert worker._console_cache["c"]["p"][0].level == "log"

    def test_text_truncated_at_8000(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "c", "p", level="log", text="a" * 10_000, source="console",
        )
        assert len(worker._console_cache["c"]["p"][0].text) == 8_000

    def test_ring_buffer_limit_200(self) -> None:
        console, worker = _make_console()
        for i in range(250):
            console.record_console_entry(
                "c", "p", level="log", text=str(i), source="console",
            )
        assert len(worker._console_cache["c"]["p"]) == 200
        assert worker._console_cache["c"]["p"][0].text == "50"
        assert worker._console_cache["c"]["p"][-1].text == "249"

    def test_sequence_increments_across_calls(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "c", "p", level="log", text="a", source="console",
        )
        console.record_console_entry(
            "c", "p", level="log", text="b", source="console",
        )
        assert worker._console_sequence == 2
        entries = worker._console_cache["c"]["p"]
        assert entries[0].entry_id == 1
        assert entries[1].entry_id == 2

    def test_url_preserved(self) -> None:
        console, worker = _make_console()
        console.record_console_entry(
            "c", "p", level="log", text="x", source="console",
            url="https://example.com",
        )
        assert worker._console_cache["c"]["p"][0].url == "https://example.com"


# ---------------------------------------------------------------------------
# console_message_attr
# ---------------------------------------------------------------------------

class TestConsoleMessageAttr:
    def test_callable_attr(self) -> None:
        msg = MagicMock()
        msg.type = MagicMock(return_value="warn")
        assert BrowserConsole.console_message_attr(msg, "type") == "warn"

    def test_non_callable_attr(self) -> None:
        msg = MagicMock()
        msg.type = "info"
        assert BrowserConsole.console_message_attr(msg, "type") == "info"

    def test_missing_attr(self) -> None:
        msg = MagicMock(spec=[])
        assert BrowserConsole.console_message_attr(msg, "type") is None

    def test_callable_raises_returns_value(self) -> None:
        msg = MagicMock()
        bad_fn = MagicMock(side_effect=RuntimeError("boom"))
        msg.type = bad_fn
        # When callable raises, suppress catches it and returns the raw value
        result = BrowserConsole.console_message_attr(msg, "type")
        assert result is bad_fn


# ---------------------------------------------------------------------------
# attach_page_console_listeners
# ---------------------------------------------------------------------------

class TestAttachPageConsoleListeners:
    def test_attaches_console_and_pageerror(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        handlers: dict[str, Any] = {}

        def fake_on(event: str, handler: Any) -> None:
            handlers[event] = handler

        page.on = fake_on
        page.url = "https://example.com/test"

        console.attach_page_console_listeners("conv1", "page1", page)

        assert "console" in handlers
        assert "pageerror" in handlers

    def test_skips_when_no_on_method(self) -> None:
        console, worker = _make_console()
        page = MagicMock(spec=[])
        console.attach_page_console_listeners("conv1", "page1", page)
        assert worker._console_listener_keys == set()

    def test_idempotent_attach(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        call_count = 0

        def fake_on(event: str, handler: Any) -> None:
            nonlocal call_count
            call_count += 1

        page.on = fake_on

        console.attach_page_console_listeners("conv1", "page1", page)
        console.attach_page_console_listeners("conv1", "page1", page)
        assert call_count == 2  # only the first attach runs

    def test_console_handler_records_entry(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        handlers: dict[str, Any] = {}

        def fake_on(event: str, handler: Any) -> None:
            handlers[event] = handler

        page.on = fake_on

        console.attach_page_console_listeners("conv1", "page1", page)

        msg = MagicMock()
        msg.type = "warn"
        msg.text = "test warning"
        msg.location = {"url": "https://example.com"}

        handlers["console"](msg)

        entries = worker._console_cache["conv1"]["page1"]
        assert len(entries) == 1
        assert entries[0].level == "warn"
        assert entries[0].text == "test warning"

    def test_pageerror_handler_records_error(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        page.url = "https://example.com/err"
        handlers: dict[str, Any] = {}

        def fake_on(event: str, handler: Any) -> None:
            handlers[event] = handler

        page.on = fake_on

        console.attach_page_console_listeners("conv1", "page1", page)
        handlers["pageerror"](RuntimeError("js error"))

        entries = worker._console_cache["conv1"]["page1"]
        assert len(entries) == 1
        assert entries[0].level == "error"
        assert entries[0].source == "pageerror"
        assert "js error" in entries[0].text


# ---------------------------------------------------------------------------
# install_console_capture
# ---------------------------------------------------------------------------

class TestInstallConsoleCapture:
    @pytest.mark.asyncio
    async def test_calls_evaluate_page(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        await console.install_console_capture(page)
        worker._evaluate_page.assert_awaited_once()
        args = worker._evaluate_page.call_args
        assert args[0][0] is page

    @pytest.mark.asyncio
    async def test_suppresses_exceptions(self) -> None:
        console, worker = _make_console()
        worker._evaluate_page = AsyncMock(side_effect=RuntimeError("boom"))
        page = MagicMock()
        await console.install_console_capture(page)


# ---------------------------------------------------------------------------
# drain_page_console_entries
# ---------------------------------------------------------------------------

class TestDrainPageConsoleEntries:
    @pytest.mark.asyncio
    async def test_drain_records_entries(self) -> None:
        console, worker = _make_console()
        worker._evaluate_page = AsyncMock(
            side_effect=[
                None,  # install_console_capture
                [
                    {"level": "log", "text": "hello", "source": "console", "url": ""},
                    {"level": "error", "text": "boom", "source": "pageerror", "url": "https://x.com"},
                ],
            ]
        )
        page = MagicMock()
        await console.drain_page_console_entries(page, "conv1", "page1")
        entries = worker._console_cache["conv1"]["page1"]
        assert len(entries) == 2
        assert entries[0].text == "hello"
        assert entries[1].level == "error"

    @pytest.mark.asyncio
    async def test_drain_skips_non_list(self) -> None:
        console, worker = _make_console()
        worker._evaluate_page = AsyncMock(
            side_effect=[None, "not a list"]
        )
        page = MagicMock()
        await console.drain_page_console_entries(page, "conv1", "page1")
        assert "conv1" not in worker._console_cache

    @pytest.mark.asyncio
    async def test_drain_skips_non_mapping_entries(self) -> None:
        console, worker = _make_console()
        worker._evaluate_page = AsyncMock(
            side_effect=[None, ["bad", 123, {"level": "log", "text": "ok", "source": "c", "url": ""}]]
        )
        page = MagicMock()
        await console.drain_page_console_entries(page, "conv1", "page1")
        entries = worker._console_cache["conv1"]["page1"]
        assert len(entries) == 1
        assert entries[0].text == "ok"


# ---------------------------------------------------------------------------
# install_cooperation_capture
# ---------------------------------------------------------------------------

class TestInstallCooperationCapture:
    @pytest.mark.asyncio
    async def test_exposes_function_and_evaluates(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        page.expose_function = AsyncMock()
        worker._evaluate_page = AsyncMock()

        await console.install_cooperation_capture(page, "browser1", "page1")

        page.expose_function.assert_awaited_once()
        args = page.expose_function.call_args[0]
        assert args[0] == "__personagentBrowserEvent"
        assert ("browser1", "page1", id(page)) in worker._cooperation_listener_keys

    @pytest.mark.asyncio
    async def test_idempotent(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        page.expose_function = AsyncMock()
        worker._evaluate_page = AsyncMock()

        await console.install_cooperation_capture(page, "b", "p")
        await console.install_cooperation_capture(page, "b", "p")

        page.expose_function.assert_awaited_once()


# ---------------------------------------------------------------------------
# drain_cooperation_events
# ---------------------------------------------------------------------------

class TestDrainCooperationEvents:
    @pytest.mark.asyncio
    async def test_drain_merges_cached_and_drained(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        page.expose_function = AsyncMock()

        worker._cooperation_event_cache = {
            "b1": {"p1": [{"type": "cached_event"}]}
        }

        worker._evaluate_page = AsyncMock(
            side_effect=[
                None,  # install
                [{"type": "drained_event"}],  # drain
            ]
        )

        result = await console.drain_cooperation_events(page, "b1", "p1")
        assert len(result) == 2
        assert result[0]["type"] == "cached_event"
        assert result[1]["type"] == "drained_event"

    @pytest.mark.asyncio
    async def test_drain_limits_to_200(self) -> None:
        console, worker = _make_console()
        page = MagicMock()
        page.expose_function = AsyncMock()

        worker._cooperation_event_cache = {
            "b1": {"p1": [{"i": i} for i in range(250)]}
        }
        worker._evaluate_page = AsyncMock(
            side_effect=[None, []]
        )

        result = await console.drain_cooperation_events(page, "b1", "p1")
        assert len(result) == 200


# ---------------------------------------------------------------------------
# record_cooperation_event
# ---------------------------------------------------------------------------

class TestRecordCooperationEvent:
    def test_records_event(self) -> None:
        console, worker = _make_console()
        console.record_cooperation_event(
            "b1", "p1", {"type": "click", "x": 10}
        )
        cache = worker._cooperation_event_cache["b1"]["p1"]
        assert len(cache) == 1
        assert cache[0]["type"] == "click"
        assert cache[0]["source"] == "user"
        assert cache[0]["channel"] == "event"
        assert cache[0]["page_id"] == "p1"

    def test_ignores_non_mapping(self) -> None:
        console, worker = _make_console()
        console.record_cooperation_event("b1", "p1", "not a mapping")
        assert "b1" not in worker._cooperation_event_cache

    def test_ring_buffer_limit_500(self) -> None:
        console, worker = _make_console()
        for i in range(550):
            console.record_cooperation_event("b1", "p1", {"i": i})
        cache = worker._cooperation_event_cache["b1"]["p1"]
        assert len(cache) == 500

    def test_defaults_are_set(self) -> None:
        console, worker = _make_console()
        console.record_cooperation_event("b1", "p1", {"custom": "val"})
        ev = worker._cooperation_event_cache["b1"]["p1"][0]
        assert ev["source"] == "user"
        assert ev["channel"] == "event"
        assert ev["trace_role"] == "user"
        assert ev["tab_id"] == "p1"


# ---------------------------------------------------------------------------
# Backward-compat delegations on worker
# ---------------------------------------------------------------------------

class TestBackwardCompatDelegations:
    def test_worker_attach_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        page = MagicMock()
        handlers: dict[str, Any] = {}

        def fake_on(event: str, handler: Any) -> None:
            handlers[event] = handler

        page.on = fake_on
        worker.console.attach_page_console_listeners("conv1", "page1", page)
        assert "console" in handlers

    def test_worker_record_delegates(self) -> None:
        from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

        worker = LightPandaBrowserWorker(enabled=False)
        worker.console.record_console_entry(
            "c", "p", level="log", text="hi", source="console",
        )
        assert len(worker._console_cache["c"]["p"]) == 1

    def test_worker_console_message_attr_delegates(self) -> None:
        from personagent.infrastructure.browser.cdp.console import BrowserConsole

        msg = MagicMock()
        msg.type = "info"
        result = BrowserConsole.console_message_attr(msg, "type")
        assert result == "info"
