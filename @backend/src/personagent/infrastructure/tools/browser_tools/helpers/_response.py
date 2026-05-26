"""Response preparation helpers for browser tools."""

from __future__ import annotations

import json
from typing import Any

from personagent.domain.tools import (
    ToolCall,
    ToolExecutionStatus,
    ToolProgress,
    ToolResult,
    ToolUseContext,
)


def _prepare_browser_control_response(
    data: dict[str, Any],
    *,
    keep_image: bool = False,
    element_limit: int = 60,
) -> dict[str, Any]:
    result = dict(data)
    elements = _summarize_element_map(result.pop("element_map", []))
    result["element_count"] = len(elements)
    result["elements"] = elements[:element_limit]
    result.pop("browser_snapshot", None)
    result.pop("frame_tree", None)
    if keep_image:
        if result.get("image_data"):
            result.pop("html", None)
            result.pop("document_html", None)
        return result
    result.pop("image_data", None)
    result.pop("image_mime_type", None)
    result.pop("html", None)
    result.pop("document_html", None)
    return result


async def _progress(
    context: ToolUseContext,
    call: ToolCall,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    await context.emit_progress(
        ToolProgress(
            tool_call_id=call.id,
            tool_name=call.name,
            status=ToolExecutionStatus.RUNNING,
            message=message,
            data=data or {},
        )
    )


def _json_result(call: ToolCall, tool_name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=tool_name,
        content=json.dumps(data, ensure_ascii=False),
        status=ToolExecutionStatus.COMPLETED,
        data=data,
    )


def _summarize_element_map(raw_map: Any) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    if not isinstance(raw_map, list):
        return elements
    for item in raw_map:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id:
            continue
        elements.append(
            {
                "node_id": node_id,
                "tab_id": str(item.get("tab_id") or ""),
                "frame_id": str(item.get("frame_id") or "main"),
                "frame_url": str(item.get("frame_url") or ""),
                "role": str(item.get("role") or ""),
                "tag": str(item.get("tag") or ""),
                "text": " ".join(str(item.get("text") or "").split())[:180],
                "href": str(item.get("href") or ""),
                "selector": str(item.get("selector") or ""),
                "selector_chain": item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [],
                "shadow_path": item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else [],
                "interactable": bool(item.get("interactable")),
                "stable_key": str(item.get("stable_key") or ""),
                "computed_summary": item.get("computed_summary") if isinstance(item.get("computed_summary"), dict) else {},
                "form_action": str(item.get("form_action") or ""),
                "input_type": str(item.get("input_type") or ""),
                "bounds": item.get("bounds") if isinstance(item.get("bounds"), dict) else {},
            }
        )
        if len(elements) >= 120:
            break
    return elements
