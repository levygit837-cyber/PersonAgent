"""Element lookup, frame traversal, and page-level helpers.

Extracted from ``lightpanda.py`` (Slice 12).  The ``ElementHelpers``
helper owns:

* Element lookup from element-map cache (selector, target, payload)
* Frame traversal (page_frames, main_frame, frame_id, viewport offset)
* Action context resolution (which frame owns an element)
* File upload & drag-and-drop primitives
* Page-level helpers (viewport, user-agent, HTML, scroll state)
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker


class ElementHelpers:
    """Element / frame / page-level helpers for the browser worker."""

    __slots__ = ("_w",)

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # ------------------------------------------------------------------
    # Element lookup from cache
    # ------------------------------------------------------------------

    def element_selector(self, browser_id: str, node_id: str) -> str:
        for item in self._w._element_map_cache.get(browser_id, []):
            if str(item.get("node_id") or "") == node_id:
                return str(item.get("selector") or "")
        return ""

    def element_target(
        self, browser_id: str, node_id: str
    ) -> dict[str, Any]:
        if not node_id:
            return {}
        for item in self._w._element_map_cache.get(browser_id, []):
            if str(item.get("node_id") or "") == node_id:
                return item
        return {}

    @staticmethod
    def browser_action_target_payload(
        target: Mapping[str, Any],
        *,
        fallback_node_id: str = "",
    ) -> dict[str, Any]:
        if not target and not fallback_node_id:
            return {}
        bounds = (
            target.get("bounds")
            if isinstance(target.get("bounds"), Mapping)
            else {}
        )
        return {
            "node_id": str(target.get("node_id") or fallback_node_id),
            "text": str(target.get("text") or ""),
            "role": str(target.get("role") or ""),
            "tag": str(target.get("tag") or ""),
            "selector": str(target.get("selector") or ""),
            "href": str(target.get("href") or ""),
            "bounds": dict(bounds),
        }

    # ------------------------------------------------------------------
    # Frame traversal
    # ------------------------------------------------------------------

    async def action_context_for_element(
        self, page: Any, target: dict[str, Any]
    ) -> Any:
        frame_id = str(target.get("frame_id") or "main")
        if frame_id == "main":
            return page
        frames = await self.page_frames(page)
        for index, frame in enumerate(frames):
            if self.frame_id(frame, index) == frame_id:
                return frame
        return page

    async def page_frames(self, page: Any) -> list[Any]:
        frames_attr = getattr(page, "frames", None)
        if callable(frames_attr):
            with suppress(Exception):
                value = frames_attr()
                if inspect.isawaitable(value):
                    value = await value
                if isinstance(value, list):
                    return value
        if isinstance(frames_attr, list):
            return frames_attr
        return [page]

    def main_frame(self, page: Any) -> Any:
        main_frame = getattr(page, "main_frame", None)
        if callable(main_frame):
            with suppress(Exception):
                return main_frame()
        if main_frame is not None:
            return main_frame
        return page

    def frame_id(self, frame: Any, index: int) -> str:
        frame_url = str(getattr(frame, "url", "") or "")
        frame_name = ""
        name = getattr(frame, "name", None)
        with suppress(Exception):
            frame_name = str(name() if callable(name) else name or "")
        digest = hashlib.sha1(
            f"{index}|{frame_name}|{frame_url}".encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()[:12]
        return f"frame_{digest}"

    async def frame_viewport_offset(
        self, frame: Any
    ) -> tuple[float, float]:
        frame_element = getattr(frame, "frame_element", None)
        if not callable(frame_element):
            return (0.0, 0.0)
        with suppress(Exception):
            element = frame_element()
            if inspect.isawaitable(element):
                element = await element
            bounding_box = getattr(element, "bounding_box", None)
            if not callable(bounding_box):
                return (0.0, 0.0)
            box = bounding_box()
            if inspect.isawaitable(box):
                box = await box
            if isinstance(box, Mapping):
                return (
                    float(box.get("x") or 0.0),
                    float(box.get("y") or 0.0),
                )
        return (0.0, 0.0)

    # ------------------------------------------------------------------
    # File upload & drag-and-drop
    # ------------------------------------------------------------------

    async def upload_files(
        self, page: Any, selector: str, files: list[str]
    ) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "selector_not_found"}
        paths = [
            str(Path(path).expanduser())
            for path in files
            if str(path or "").strip()
        ]
        if not paths:
            return {"ok": False, "reason": "files_required"}
        locator = getattr(page, "locator", None)
        if not callable(locator):
            return {"ok": False, "reason": "locator_unavailable"}
        try:
            file_input = locator(selector).first
            if callable(file_input):
                file_input = file_input()
            set_input_files = getattr(file_input, "set_input_files", None)
            if not callable(set_input_files):
                return {"ok": False, "reason": "file_upload_unavailable"}
            result = set_input_files(paths)
            if inspect.isawaitable(result):
                await result
            return {"ok": True, "action": "upload", "file_count": len(paths)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    async def drag_between_elements(
        self,
        page: Any,
        selector: str,
        *,
        target_selector: str,
        x: float | None,
        y: float | None,
    ) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "selector_not_found"}
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return {"ok": False, "reason": "mouse_unavailable"}
        payload = await self._w._browser_runtime.evaluate_page(
            page,
            """
            ({ selector, targetSelector, x, y }) => {
              const rectFor = (nextSelector) => {
                if (!nextSelector) return null;
                const el = document.querySelector(nextSelector);
                if (!el) return null;
                el.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = el.getBoundingClientRect();
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
              };
              return {
                source: rectFor(selector),
                target: rectFor(targetSelector) || (
                  Number.isFinite(Number(x)) && Number.isFinite(Number(y))
                    ? { x: Number(x), y: Number(y) }
                    : null
                )
              };
            }
            """,
            {
                "selector": selector,
                "targetSelector": target_selector,
                "x": x,
                "y": y,
            },
        )
        if not isinstance(payload, Mapping):
            return {"ok": False, "reason": "bounds_unavailable"}
        source = payload.get("source")
        target = payload.get("target")
        if not isinstance(source, Mapping) or not isinstance(
            target, Mapping
        ):
            return {"ok": False, "reason": "drag_points_unavailable"}
        move = getattr(mouse, "move", None)
        down = getattr(mouse, "down", None)
        up = getattr(mouse, "up", None)
        if not (callable(move) and callable(down) and callable(up)):
            return {"ok": False, "reason": "drag_unavailable"}
        await move(float(source["x"]), float(source["y"]))
        await down()
        await move(float(target["x"]), float(target["y"]), steps=12)
        await up()
        return {"ok": True, "action": "drop"}

    # ------------------------------------------------------------------
    # Page-level helpers
    # ------------------------------------------------------------------

    async def set_page_viewport(
        self, page: Any, width: int, height: int
    ) -> None:
        operation = getattr(page, "set_viewport_size", None)
        if not callable(operation):
            return
        with suppress(Exception):
            result = operation({"width": int(width), "height": int(height)})
            if inspect.isawaitable(result):
                await result

    async def safe_user_agent(self, page: Any) -> str:
        with suppress(Exception):
            value = await self._w._browser_runtime.evaluate_page(
                page, "() => navigator.userAgent || ''"
            )
            if isinstance(value, str):
                return value.strip()
        return ""

    async def safe_html(self, page: Any) -> str:
        operation = getattr(page, "content", None)
        if not callable(operation):
            return ""
        with suppress(Exception):
            value = operation()
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(
                    value,
                    timeout=min(
                        max(self._w.timeout_ms / 1000, 1.0), 5.0
                    ),
                )
            if isinstance(value, str):
                return value[:2_000_000]
        return ""

    async def safe_scroll_state(self, page: Any) -> dict[str, int]:
        with suppress(Exception):
            value = await self._w._browser_runtime.evaluate_page(
                page,
                """() => ({
                  scroll_x: Math.round(window.scrollX || document.documentElement.scrollLeft || 0),
                  scroll_y: Math.round(window.scrollY || document.documentElement.scrollTop || 0)
                })""",
            )
            if isinstance(value, Mapping):
                return {
                    "scroll_x": int(value.get("scroll_x") or 0),
                    "scroll_y": int(value.get("scroll_y") or 0),
                }
        return {"scroll_x": 0, "scroll_y": 0}
