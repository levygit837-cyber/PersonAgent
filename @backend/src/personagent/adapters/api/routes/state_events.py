"""Lightweight state-change events for desktop cache invalidation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/events", tags=["events"])

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
STATE_PROBE_INTERVAL_SECONDS = 25


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


def _state_event(resource: str, scope: dict[str, Any] | None = None, version: str | None = None) -> dict[str, Any]:
    return {
        "event": "state.changed",
        "resource": resource,
        "scope": {key: value for key, value in (scope or {}).items() if value is not None},
        "version": version or uuid4().hex,
        "changed_at": datetime.now(UTC).isoformat(),
    }


def _codex_auth_signature() -> str | None:
    try:
        from personagent.adapters.composition import get_container

        backend = get_container().get_llm_backend("codex")
        signature = getattr(backend, "auth_signature", None)
        if signature is None:
            return None
        return str(signature())
    except Exception as exc:
        return f"error:{type(exc).__name__}:{exc}"


def _git_signature(workspace_root: str | None) -> str | None:
    if not workspace_root:
        return None
    try:
        from personagent.adapters.api.routes import workspace

        cwd = workspace._resolve_workspace(workspace_root)  # noqa: SLF001
        if not workspace._is_git_repo(cwd):  # noqa: SLF001
            return f"not-repo:{Path(workspace_root).expanduser()}"
        commands = (
            ["rev-parse", "HEAD"],
            ["branch", "--show-current"],
            ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
            ["status", "--porcelain=v1", "-uno"],
        )
        parts: list[str] = []
        for args in commands:
            result = workspace._run_git_command(cwd, args)  # noqa: SLF001
            parts.append(f"{' '.join(args)}:{result.returncode}:{result.stdout.strip()}:{result.stderr.strip()}")
        return hashlib.sha256("\n".join(parts).encode("utf-8", errors="replace")).hexdigest()
    except Exception as exc:
        return f"error:{type(exc).__name__}:{exc}"


def _external_state_changes(
    request: Request,
    signatures: dict[str, str | None],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    workspace_root = request.query_params.get("workspace_root")

    git_signature = _git_signature(workspace_root)
    if git_signature is not None:
        previous = signatures.setdefault("git", git_signature)
        if git_signature != previous:
            signatures["git"] = git_signature
            scope = {"workspace_root": workspace_root}
            events.extend(
                [
                    _state_event("git-status", scope, git_signature),
                    _state_event("git-branches", scope, git_signature),
                    _state_event("git-recent-actions", scope, git_signature),
                    _state_event("git-pull-requests", scope, git_signature),
                ],
            )

    codex_signature = _codex_auth_signature()
    if codex_signature is not None:
        previous = signatures.setdefault("codex-auth", codex_signature)
        if codex_signature != previous:
            signatures["codex-auth"] = codex_signature
            scope = {"provider": "codex"}
            events.extend(
                [
                    _state_event("codex-auth", scope, codex_signature),
                    _state_event("models", scope, codex_signature),
                ],
            )

    return events


@router.get("/state")
async def stream_state_events(request: Request) -> StreamingResponse:
    """Stream state changes that let the desktop invalidate only stale caches."""

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        signatures: dict[str, str | None] = {}
        _subscribers.add(queue)
        try:
            yield ": connected\n\n"
            _external_state_changes(request, signatures)
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=STATE_PROBE_INTERVAL_SECONDS)
                except TimeoutError:
                    for event in _external_state_changes(request, signatures):
                        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                        yield f"event: state.changed\ndata: {payload}\n\n"
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"event: state.changed\ndata: {payload}\n\n"
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
