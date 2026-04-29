"""Lightweight state-change events for desktop cache invalidation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/events", tags=["events"])

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


def publish_state_change(resource: str, scope: dict[str, Any] | None = None, version: str | None = None) -> None:
    """Publish a best-effort state-change notification to connected desktops."""

    event = {
        "event": "state.changed",
        "resource": resource,
        "scope": {key: value for key, value in (scope or {}).items() if value is not None},
        "version": version or uuid4().hex,
        "changed_at": datetime.now(UTC).isoformat(),
    }
    dead: list[asyncio.Queue[dict[str, Any]]] = []
    for queue in tuple(_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(queue)
    for queue in dead:
        _subscribers.discard(queue)


@router.get("/state")
async def stream_state_events(request: Request) -> StreamingResponse:
    """Stream state changes that let the desktop invalidate only stale caches."""

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        _subscribers.add(queue)
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"event: state.changed\ndata: {payload}\n\n"
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
