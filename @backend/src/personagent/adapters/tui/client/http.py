"""HTTP client and SSE stream parser for the TUI."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from .types import ChatRequestPayload, StreamChunk

FALLBACK_BASE_URLS = ["http://localhost:8000", "http://localhost:8001"]
_DEFAULT_TOKEN_PATH = Path("~/.cache/personagent/local_auth_token").expanduser()


def _read_token() -> str | None:
    """Read the local auth token from env or the default file path."""
    token = os.environ.get("PERSONAGENT_LOCAL_AUTH_TOKEN", "").strip()
    if token:
        return token
    try:
        return _DEFAULT_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _auth_headers() -> dict[str, str]:
    token = _read_token()
    if token:
        return {
            "Authorization": f"Bearer {token}",
            "X-PersonAgent-Client": "tui",
        }
    return {"X-PersonAgent-Client": "tui"}


async def resolve_backend_url(current: str | None = None) -> str:
    """Probe candidate URLs and return the first healthy backend."""
    candidates = list(
        dict.fromkeys([current, *FALLBACK_BASE_URLS])  # preserve order, remove dupes
    )
    async with httpx.AsyncClient(timeout=3.0) as client:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                response = await client.get(f"{candidate}/health")
                if response.is_success:
                    return candidate
            except Exception:
                continue
    raise RuntimeError("No PersonAgent backend answered on the configured ports.")


def _parse_sse_payloads(buffer: str) -> tuple[list[dict[str, Any]], str]:
    """Parse one or more SSE data blocks from a text buffer.

    Returns a tuple of (parsed payloads, leftover text).
    """
    payloads: list[dict[str, Any]] = []
    normalized = buffer.replace("\r\n", "\n")
    blocks = normalized.split("\n\n")
    rest = blocks.pop() if blocks else ""

    for block in blocks:
        data_lines = [
            line[5:].lstrip()
            for line in block.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data = "".join(data_lines).strip()
        if not data:
            continue
        if data == "[DONE]":
            payloads.append({"__done": True})
            continue
        try:
            payloads.append(json.loads(data))
        except json.JSONDecodeError:
            continue

    return payloads, rest


async def list_conversations(base_url: str) -> list[dict[str, Any]]:
    """Fetch the conversation list from the backend."""
    headers = _auth_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url}/conversations",
            headers=headers,
            params={"limit": 50, "offset": 0},
        )
        if not response.is_success:
            raise RuntimeError(
                f"Backend returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()


async def get_conversation(base_url: str, conversation_id: str) -> dict[str, Any]:
    """Fetch a single conversation by ID."""
    headers = _auth_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url}/conversations/{conversation_id}",
            headers=headers,
        )
        if not response.is_success:
            raise RuntimeError(
                f"Backend returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()


async def list_models(base_url: str, provider: str = "deepseek") -> dict[str, Any]:
    """Fetch available models from the backend."""
    headers = _auth_headers()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url}/chat/models",
            headers=headers,
            params={"provider": provider},
        )
        if not response.is_success:
            raise RuntimeError(
                f"Backend returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()


async def stream_chat_completion(
    base_url: str,
    payload: ChatRequestPayload,
    signal: asyncio.Event | None = None,
):
    """Stream chat completion chunks from the backend.

    Yields :class:`StreamChunk` objects until the stream ends or is aborted.
    """
    headers = _auth_headers()
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream"
    headers["Cache-Control"] = "no-cache"

    body = payload.model_dump(exclude_none=True)

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions/stream",
            headers=headers,
            json=body,
        ) as response:
            if not response.is_success:
                text = await response.aread()
                raise RuntimeError(
                    f"Backend returned {response.status_code}: {text.decode()[:200]}"
                )

            buffer = ""
            async for raw_bytes in response.aiter_bytes():
                if signal and signal.is_set():
                    return
                buffer += raw_bytes.decode("utf-8", errors="replace")
                payloads, buffer = _parse_sse_payloads(buffer)
                for payload_dict in payloads:
                    if payload_dict.get("__done"):
                        return
                    yield StreamChunk.model_validate(payload_dict)

            payloads, _ = _parse_sse_payloads(f"{buffer}\n\n")
            for payload_dict in payloads:
                if payload_dict.get("__done"):
                    return
                yield StreamChunk.model_validate(payload_dict)
