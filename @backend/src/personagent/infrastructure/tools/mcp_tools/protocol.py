"""MCP stdio protocol communication."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from personagent.infrastructure.tools.mcp_tools.config import McpServerConfig


async def _mcp_request(
    config: McpServerConfig,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if config.transport != "stdio":
        raise RuntimeError(f"Unsupported MCP transport for {config.name}: {config.transport}")
    if not config.command:
        raise RuntimeError(f"MCP server {config.name} has no command configured.")

    env = os.environ.copy()
    if config.env:
        env.update(config.env)
    process = await asyncio.create_subprocess_exec(
        config.command,
        *config.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        init = await _send_request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "PersonAgent", "version": "0.1.0"},
            },
            timeout_ms=config.timeout_ms,
        )
        if init.get("error"):
            raise RuntimeError(str(init["error"]))
        await _send_notification(process, "notifications/initialized", {})
        response = await _send_request(
            process,
            2,
            method,
            params,
            timeout_ms=config.timeout_ms,
        )
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        result = response.get("result")
        return result if isinstance(result, dict) else {"content": result}
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            process.kill()
            await process.wait()


async def _send_request(
    process: asyncio.subprocess.Process,
    request_id: int,
    method: str,
    params: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    await _write_json(
        process,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    return await asyncio.wait_for(_read_response(process, request_id), timeout=timeout_ms / 1000)


async def _send_notification(
    process: asyncio.subprocess.Process,
    method: str,
    params: dict[str, Any],
) -> None:
    await _write_json(process, {"jsonrpc": "2.0", "method": method, "params": params})


async def _write_json(process: asyncio.subprocess.Process, payload: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
    await process.stdin.drain()


async def _read_response(
    process: asyncio.subprocess.Process,
    request_id: int,
) -> dict[str, Any]:
    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "MCP server exited.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("id") == request_id:
            return payload
