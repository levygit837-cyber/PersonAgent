"""Anthropic history block handling for Kimi Code adapter."""

from __future__ import annotations

import json
from typing import Any


def anthropic_history_blocks(
    blocks: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize a dict of index→block into sorted history blocks."""
    history: list[dict[str, Any]] = []
    for _, block in sorted(blocks.items()):
        normalized = _normalize_anthropic_history_block(block)
        if normalized is not None:
            history.append(normalized)
    return history


def _normalize_anthropic_history_block(
    block: dict[str, Any],
) -> dict[str, Any] | None:
    block_type = block.get("type")
    if block_type == "text":
        text = str(block.get("text") or "")
        return {"type": "text", "text": text} if text else None

    if block_type == "thinking":
        thinking = str(block.get("thinking") or "")
        if not thinking:
            return None
        normalized: dict[str, Any] = {"type": "thinking", "thinking": thinking}
        signature = block.get("signature")
        if isinstance(signature, str) and signature:
            normalized["signature"] = signature
        return normalized

    if block_type == "tool_use":
        name = str(block.get("name") or "")
        tool_id = str(block.get("id") or "")
        if not name or not tool_id:
            return None
        return {
            "type": "tool_use",
            "id": tool_id,
            "name": name,
            "input": _anthropic_tool_input(block),
        }

    return None


def attach_anthropic_history_blocks(
    tool_calls: list[dict[str, Any]],
    history_blocks: list[dict[str, Any]],
) -> None:
    if not tool_calls or not history_blocks:
        return
    extra = tool_calls[0].get("extra_content")
    next_extra = dict(extra) if isinstance(extra, dict) else {}
    anthropic = next_extra.get("anthropic")
    next_anthropic = dict(anthropic) if isinstance(anthropic, dict) else {}
    next_anthropic["content_blocks"] = history_blocks
    next_extra["anthropic"] = next_anthropic
    tool_calls[0]["extra_content"] = next_extra


def anthropic_history_blocks_from_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    for tool_call in tool_calls:
        extra = tool_call.get("extra_content")
        if not isinstance(extra, dict):
            continue
        anthropic = extra.get("anthropic")
        if not isinstance(anthropic, dict):
            continue
        raw_blocks = anthropic.get("content_blocks")
        if not isinstance(raw_blocks, list):
            continue
        blocks = [
            dict(block)
            for block in raw_blocks
            if isinstance(block, dict) and block.get("type")
        ]
        if blocks:
            return _remap_anthropic_tool_ids(blocks, tool_calls)
    return None


def _remap_anthropic_tool_ids(
    blocks: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    remap: dict[str, str] = {}
    tool_by_id: dict[str, dict[str, Any]] = {}
    for tool_call in tool_calls:
        current_id = str(tool_call.get("id") or "")
        if not current_id:
            continue
        tool_by_id[current_id] = tool_call
        remap[current_id] = current_id
        extra = tool_call.get("extra_content")
        if isinstance(extra, dict):
            original_id = extra.get("original_tool_call_id")
            if isinstance(original_id, str) and original_id:
                remap[original_id] = current_id
                tool_by_id[original_id] = tool_call

    remapped: list[dict[str, Any]] = []
    for block in blocks:
        next_block = dict(block)
        if next_block.get("type") == "tool_use":
            old_id = str(next_block.get("id") or "")
            new_id = remap.get(old_id)
            if new_id:
                next_block["id"] = new_id
                tool_call = tool_by_id.get(old_id) or tool_by_id.get(new_id)
                if tool_call:
                    function = tool_call.get("function") or {}
                    if function.get("name"):
                        next_block["name"] = str(function["name"])
                    next_block["input"] = parse_tool_arguments(
                        function.get("arguments")
                    )
        remapped.append(next_block)
    return remapped


def tool_call_from_anthropic_block(block: dict[str, Any]) -> dict[str, Any]:
    raw_input = _anthropic_tool_input(block)
    arguments = (
        raw_input
        if isinstance(raw_input, str)
        else json.dumps(raw_input or {}, ensure_ascii=False)
    )
    return {
        "id": str(block.get("id") or ""),
        "type": "function",
        "function": {
            "name": str(block.get("name") or ""),
            "arguments": arguments,
        },
    }


def _anthropic_tool_input(block: dict[str, Any]) -> Any:
    raw_input = block.get("input")
    partial = str(block.get("_partial_json") or "")
    if partial:
        try:
            return json.loads(partial)
        except json.JSONDecodeError:
            return partial
    return raw_input if raw_input is not None else {}


def parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
            return parsed if isinstance(parsed, dict) else {"_raw_arguments": parsed}
        except json.JSONDecodeError:
            return {"_raw_arguments": arguments}
    return {"_raw_arguments": arguments}
