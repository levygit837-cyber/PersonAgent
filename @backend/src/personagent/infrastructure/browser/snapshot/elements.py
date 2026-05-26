"""Element-map and frame-tree helpers for browser snapshots."""

from __future__ import annotations

import inspect
from contextlib import suppress
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def browser_element_map(worker: Any, page: Any) -> list[dict[str, Any]]:
    from personagent.infrastructure.browser.snapshot.scripts import (
        _BROWSER_ELEMENT_MAP_SCRIPT,
    )

    mapped: list[dict[str, Any]] = []
    with suppress(Exception):
        value = await worker._evaluate_page(
            page,
            _BROWSER_ELEMENT_MAP_SCRIPT,
            {"frameId": "main", "frameUrl": str(getattr(page, "url", "") or "")},
        )
        if isinstance(value, list):
            mapped.extend(
                item
                for item in value
                if isinstance(item, dict) and isinstance(item.get("node_id"), str)
            )
    mapped.extend(await browser_iframe_element_map(worker, page))
    return mapped[:500]


async def browser_iframe_element_map(worker: Any, page: Any) -> list[dict[str, Any]]:
    from personagent.infrastructure.browser.snapshot.scripts import (
        _BROWSER_ELEMENT_MAP_SCRIPT,
    )

    frames = await worker.element_helpers.page_frames(page)
    if len(frames) <= 1:
        return []
    main_frame = worker.element_helpers.main_frame(page)
    mapped: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if frame is main_frame:
            continue
        frame_id = worker.element_helpers.frame_id(frame, index)
        offset = await worker.element_helpers.frame_viewport_offset(frame)
        with suppress(Exception):
            evaluate = getattr(frame, "evaluate", None)
            if not callable(evaluate):
                continue
            value = evaluate(
                _BROWSER_ELEMENT_MAP_SCRIPT,
                {
                    "frameId": frame_id,
                    "frameUrl": str(getattr(frame, "url", "") or ""),
                    "offsetX": offset[0],
                    "offsetY": offset[1],
                },
            )
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, list):
                mapped.extend(
                    item
                    for item in value
                    if isinstance(item, dict) and isinstance(item.get("node_id"), str)
                )
        if len(mapped) >= 280:
            break
    return mapped[:280]


def enrich_browser_element_map(
    raw_map: list[dict[str, Any]],
    *,
    browser_id: str,
    tab_id: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in raw_map:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        selector = str(item.get("selector") or "")
        role = str(item.get("role") or "")
        text = str(item.get("text") or "")
        frame_id = str(item.get("frame_id") or "main")
        stable_key = str(item.get("stable_key") or f"{tab_id}|{frame_id}|{selector}|{role}|{text[:80]}")
        next_item = dict(item)
        next_item["node_id"] = node_id
        next_item["tab_id"] = str(item.get("tab_id") or tab_id or browser_id)
        next_item["frame_id"] = frame_id
        next_item["selector_chain"] = item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [selector]
        next_item["shadow_path"] = item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else []
        next_item["stable_key"] = stable_key
        next_item["interactable"] = bool(
            item.get("interactable")
            or role in {"link", "button", "input", "textbox", "select", "form", "checkbox", "radio", "tab"}
        )
        if not isinstance(next_item.get("computed_summary"), dict):
            next_item["computed_summary"] = {}
        enriched.append(next_item)
        if len(enriched) >= 220:
            break
    return enriched


async def browser_frame_tree_snapshot(
    worker: Any,
    page: Any,
    *,
    current_url: str,
    title: str,
) -> list[dict[str, Any]]:
    frames = await worker.element_helpers.page_frames(page)
    if not frames:
        return [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
    main_frame = worker.element_helpers.main_frame(page)
    tree: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        frame_id = "main" if frame is main_frame or index == 0 else worker.element_helpers.frame_id(frame, index)
        parent_id = ""
        frame_url = str(getattr(frame, "url", "") or "")
        parent_frame = getattr(frame, "parent_frame", None)
        if callable(parent_frame):
            with suppress(Exception):
                parent = parent_frame()
                if parent is not None and parent is not main_frame:
                    parent_index = frames.index(parent) if parent in frames else 0
                    parent_id = worker.element_helpers.frame_id(parent, parent_index)
                elif parent is main_frame:
                    parent_id = "main"
        tree.append(
            {
                "frame_id": frame_id,
                "url": frame_url or (current_url if frame_id == "main" else ""),
                "title": title if frame_id == "main" else "",
                "parent_frame_id": parent_id,
            }
        )
    return tree or [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
