"""Unit tests for CdpClient extracted from lightpanda.py."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from personagent.infrastructure.browser.cdp_client import CdpClient
from personagent.infrastructure.browser.models import BrowserUnavailableError

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Records sent frames and replays scripted responses."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[str] = []
        self._responses: list[dict[str, Any]] = list(responses or [])
        self._recv_index = 0

    def queue(self, payload: dict[str, Any]) -> None:
        self._responses.append(payload)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        if self._recv_index >= len(self._responses):
            raise RuntimeError("No more scripted responses")
        payload = self._responses[self._recv_index]
        self._recv_index += 1
        return json.dumps(payload)


class _BlockingWebSocket:
    """WebSocket that blocks recv() until manually unblocked."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        return await self._queue.get()

    def push(self, payload: dict[str, Any]) -> None:
        self._queue.put_nowait(json.dumps(payload))


# ---------------------------------------------------------------------------
# Tests: send()
# ---------------------------------------------------------------------------


class TestCdpClientSend:
    """Tests for CdpClient.send."""

    @pytest.mark.asyncio
    async def test_send_round_trips_and_returns_result(self) -> None:
        ws = _FakeWebSocket([{"id": 1, "result": {"targetId": "T1"}}])
        client = CdpClient(ws)

        result = await client.send("Target.createTarget", {"url": "about:blank"})

        assert result == {"targetId": "T1"}
        sent = json.loads(ws.sent[0])
        assert sent == {"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank"}}

    @pytest.mark.asyncio
    async def test_send_without_params_omits_params_key(self) -> None:
        ws = _FakeWebSocket([{"id": 1, "result": {}}])
        client = CdpClient(ws)

        await client.send("Page.enable")

        sent = json.loads(ws.sent[0])
        assert "params" not in sent

    @pytest.mark.asyncio
    async def test_send_with_session_id(self) -> None:
        ws = _FakeWebSocket([{"id": 1, "result": {"frameId": "F1"}}])
        client = CdpClient(ws)

        result = await client.send("Page.navigate", {"url": "https://example.com"}, session_id="S1")

        assert result == {"frameId": "F1"}
        sent = json.loads(ws.sent[0])
        assert sent["sessionId"] == "S1"

    @pytest.mark.asyncio
    async def test_send_error_raises_browser_unavailable(self) -> None:
        ws = _FakeWebSocket([
            {"id": 1, "error": {"code": -32000, "message": "Target not found"}},
        ])
        client = CdpClient(ws)

        with pytest.raises(BrowserUnavailableError, match="Target.closeTarget failed"):
            await client.send("Target.closeTarget", {"targetId": "T1"})

    @pytest.mark.asyncio
    async def test_send_returns_empty_dict_when_result_is_not_dict(self) -> None:
        ws = _FakeWebSocket([{"id": 1, "result": None}])
        client = CdpClient(ws)

        result = await client.send("Page.enable")

        assert result == {}

    @pytest.mark.asyncio
    async def test_send_returns_empty_dict_when_result_missing(self) -> None:
        ws = _FakeWebSocket([{"id": 1}])
        client = CdpClient(ws)

        result = await client.send("Page.enable")

        assert result == {}

    @pytest.mark.asyncio
    async def test_send_skips_non_matching_ids_and_buffers_them(self) -> None:
        """A reply with a non-matching id is buffered; the matching one is returned."""
        ws = _FakeWebSocket([
            {"id": 999, "result": {"stale": True}},
            {"id": 1, "result": {"fresh": True}},
        ])
        client = CdpClient(ws)

        result = await client.send("Method.A")

        assert result == {"fresh": True}
        assert len(client._events) == 1
        assert client._events[0] == {"id": 999, "result": {"stale": True}}

    @pytest.mark.asyncio
    async def test_send_buffers_events_while_waiting_for_reply(self) -> None:
        ws = _FakeWebSocket([
            {"method": "Page.loadEventFired", "params": {}, "sessionId": "S1"},
            {"id": 1, "result": {"frameId": "F1"}},
        ])
        client = CdpClient(ws)

        result = await client.send("Page.navigate", {"url": "https://example.com"})

        assert result == {"frameId": "F1"}
        assert len(client._events) == 1
        assert client._events[0]["method"] == "Page.loadEventFired"

    @pytest.mark.asyncio
    async def test_send_increments_message_ids(self) -> None:
        ws = _FakeWebSocket([
            {"id": 1, "result": {}},
            {"id": 2, "result": {"data": "ok"}},
        ])
        client = CdpClient(ws)

        await client.send("Method.First")
        await client.send("Method.Second")

        sent1 = json.loads(ws.sent[0])
        sent2 = json.loads(ws.sent[1])
        assert sent1["id"] == 1
        assert sent2["id"] == 2


# ---------------------------------------------------------------------------
# Tests: wait_for_event()
# ---------------------------------------------------------------------------


class TestCdpClientWaitForEvent:
    """Tests for CdpClient.wait_for_event."""

    @pytest.mark.asyncio
    async def test_wait_for_event_returns_matching_event(self) -> None:
        ws = _FakeWebSocket([
            {"method": "Page.domContentEventFired", "params": {}, "sessionId": "S1"},
        ])
        client = CdpClient(ws)

        event = await client.wait_for_event("Page.domContentEventFired", session_id="S1", timeout=5.0)

        assert event["method"] == "Page.domContentEventFired"

    @pytest.mark.asyncio
    async def test_wait_for_event_ignores_non_matching_events(self) -> None:
        ws = _FakeWebSocket([
            {"method": "Network.requestWillBeSent", "params": {}, "sessionId": "S1"},
            {"method": "Page.domContentEventFired", "params": {}, "sessionId": "S1"},
        ])
        client = CdpClient(ws)

        event = await client.wait_for_event("Page.domContentEventFired", session_id="S1", timeout=5.0)

        assert event["method"] == "Page.domContentEventFired"
        assert len(client._events) == 1
        assert client._events[0]["method"] == "Network.requestWillBeSent"

    @pytest.mark.asyncio
    async def test_wait_for_event_ignores_wrong_session_id(self) -> None:
        ws = _FakeWebSocket([
            {"method": "Page.domContentEventFired", "params": {}, "sessionId": "OTHER"},
            {"method": "Page.domContentEventFired", "params": {}, "sessionId": "S1"},
        ])
        client = CdpClient(ws)

        event = await client.wait_for_event("Page.domContentEventFired", session_id="S1", timeout=5.0)

        assert event["sessionId"] == "S1"
        assert len(client._events) == 1
        assert client._events[0]["sessionId"] == "OTHER"

    @pytest.mark.asyncio
    async def test_wait_for_event_finds_buffered_event(self) -> None:
        ws = _FakeWebSocket()
        client = CdpClient(ws)
        client._events.append(
            {"method": "Page.loadEventFired", "params": {}, "sessionId": "S1"},
        )

        event = await client.wait_for_event("Page.loadEventFired", session_id="S1", timeout=5.0)

        assert event["method"] == "Page.loadEventFired"
        assert len(client._events) == 0

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout_raises(self) -> None:
        ws = _BlockingWebSocket()
        client = CdpClient(ws)

        with pytest.raises(TimeoutError):
            await client.wait_for_event("Page.domContentEventFired", session_id="S1", timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_for_event_deadline_expired_raises_custom_message(self) -> None:
        """When remaining time is already <= 0, the custom message is raised."""
        ws = _FakeWebSocket()
        client = CdpClient(ws)

        with pytest.raises(TimeoutError, match="Timed out waiting for CDP event"):
            await client.wait_for_event("Page.domContentEventFired", session_id="S1", timeout=0.0)


# ---------------------------------------------------------------------------
# Tests: _is_matching_event (static method)
# ---------------------------------------------------------------------------


class TestCdpClientIsMatchingEvent:
    """Tests for the static _is_matching_event helper."""

    def test_matching_event_returns_true(self) -> None:
        payload = {"method": "Page.loadEventFired", "sessionId": "S1"}
        assert CdpClient._is_matching_event(payload, "Page.loadEventFired", "S1") is True

    def test_wrong_method_returns_false(self) -> None:
        payload = {"method": "Network.requestWillBeSent", "sessionId": "S1"}
        assert CdpClient._is_matching_event(payload, "Page.loadEventFired", "S1") is False

    def test_wrong_session_id_returns_false(self) -> None:
        payload = {"method": "Page.loadEventFired", "sessionId": "OTHER"}
        assert CdpClient._is_matching_event(payload, "Page.loadEventFired", "S1") is False

    def test_missing_method_returns_false(self) -> None:
        payload: dict[str, Any] = {"sessionId": "S1"}
        assert CdpClient._is_matching_event(payload, "Page.loadEventFired", "S1") is False

    def test_missing_session_id_returns_false(self) -> None:
        payload: dict[str, Any] = {"method": "Page.loadEventFired"}
        assert CdpClient._is_matching_event(payload, "Page.loadEventFired", "S1") is False


# ---------------------------------------------------------------------------
# Tests: backward-compat alias
# ---------------------------------------------------------------------------


class TestBackwardCompatAlias:
    """Ensure _RawCdpClient alias still works in lightpanda.py."""

    def test_raw_cdp_client_alias_resolves_to_cdp_client(self) -> None:
        from personagent.infrastructure.browser.lightpanda import _RawCdpClient

        assert _RawCdpClient is CdpClient
