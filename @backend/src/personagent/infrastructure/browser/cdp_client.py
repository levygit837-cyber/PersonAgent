"""Tiny sequential CDP client for LightPanda-native domain calls."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from personagent.infrastructure.browser.models import BrowserUnavailableError


class CdpClient:
    """Tiny sequential CDP client for LightPanda-native domain calls."""

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket
        self._next_id = 0
        self._events: list[dict[str, Any]] = []

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        await self._websocket.send(json.dumps(message))
        while True:
            payload = json.loads(await self._websocket.recv())
            if payload.get("id") == message_id:
                if "error" in payload:
                    error = payload["error"]
                    raise BrowserUnavailableError(f"LightPanda CDP {method} failed: {error}")
                result = payload.get("result")
                return result if isinstance(result, dict) else {}
            self._events.append(payload)

    async def wait_for_event(
        self,
        method: str,
        *,
        session_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for index, event in enumerate(self._events):
                if self._is_matching_event(event, method, session_id):
                    return self._events.pop(index)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for CDP event {method}.")
            payload = json.loads(await asyncio.wait_for(self._websocket.recv(), timeout=remaining))
            if self._is_matching_event(payload, method, session_id):
                return payload
            self._events.append(payload)

    @staticmethod
    def _is_matching_event(payload: dict[str, Any], method: str, session_id: str) -> bool:
        return payload.get("method") == method and payload.get("sessionId") == session_id
