import type { MouseEvent } from "react";
import type {
  SessionBrowserElement,
  SessionBrowserViewport,
  SessionBrowserView,
} from "../../../../api/client";
import { numericValue, recordValue } from "./helpers";

export const BROWSER_FORWARD_KEYS = new Set([
  "Enter",
  "Backspace",
  "Delete",
  "Escape",
  "Tab",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

export function isBrowserViewportControlTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, button, [contenteditable='true'], [data-browser-annotation-editor='true']",
    ),
  );
}

export function browserViewport(element: HTMLElement | null, view?: SessionBrowserView): SessionBrowserViewport {
  const rect = element?.getBoundingClientRect();
  const width = Math.round(rect?.width || view?.viewport_width || 1024);
  const height = Math.round(rect?.height || view?.viewport_height || 720);
  return {
    width: Math.min(Math.max(width, 320), 2400),
    height: Math.min(Math.max(height, 240), 1800),
  };
}

export function browserElementAtRenderedPoint(
  event: MouseEvent<HTMLElement>,
  image: HTMLElement,
  view: SessionBrowserView,
  elementMap: SessionBrowserElement[],
) {
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return undefined;
  const targetWidth = view.viewport_width || rect.width;
  const targetHeight = view.viewport_height || rect.height;
  const x = ((event.clientX - rect.left) / rect.width) * targetWidth;
  const y = ((event.clientY - rect.top) / rect.height) * targetHeight;
  return elementMap
    .filter((element) => {
      const bounds = element.bounds;
      if (!bounds || bounds.width <= 0 || bounds.height <= 0) return false;
      return x >= bounds.x && x <= bounds.x + bounds.width && y >= bounds.y && y <= bounds.y + bounds.height;
    })
    .sort((left, right) => {
      const leftBounds = left.bounds!;
      const rightBounds = right.bounds!;
      const leftArea = leftBounds.width * leftBounds.height;
      const rightArea = rightBounds.width * rightBounds.height;
      if (Boolean(left.interactable) !== Boolean(right.interactable)) return left.interactable ? -1 : 1;
      return leftArea - rightArea;
    })[0];
}

export function browserRenderedElementStyle(
  bounds: NonNullable<SessionBrowserElement["bounds"]>,
  image: HTMLElement | null,
  view: SessionBrowserView,
) {
  const rect = image?.getBoundingClientRect();
  const viewportWidth = view.viewport_width || rect?.width || 1;
  const viewportHeight = view.viewport_height || rect?.height || 1;
  const viewRecord = recordValue(view);
  const snapshotRecord = recordValue(view.browser_snapshot);
  const scrollX = numericValue(viewRecord.scroll_x ?? snapshotRecord.scroll_x) || 0;
  const scrollY = numericValue(viewRecord.scroll_y ?? snapshotRecord.scroll_y) || 0;
  const viewportBounds = {
    x: bounds.x - scrollX,
    y: bounds.y - scrollY,
    width: bounds.width,
    height: bounds.height,
  };
  const originalLooksVisible =
    bounds.x + bounds.width >= 0 &&
    bounds.y + bounds.height >= 0 &&
    bounds.x <= viewportWidth &&
    bounds.y <= viewportHeight;
  const scrolledLooksVisible =
    viewportBounds.x + viewportBounds.width >= 0 &&
    viewportBounds.y + viewportBounds.height >= 0 &&
    viewportBounds.x <= viewportWidth &&
    viewportBounds.y <= viewportHeight;
  const adjusted = scrolledLooksVisible || !originalLooksVisible ? viewportBounds : bounds;
  const scaleX = rect?.width ? rect.width / Math.max(1, viewportWidth) : 1;
  const scaleY = rect?.height ? rect.height / Math.max(1, viewportHeight) : 1;
  return {
    left: Math.round(adjusted.x * scaleX),
    top: Math.round(adjusted.y * scaleY),
    width: Math.round(adjusted.width * scaleX),
    height: Math.round(adjusted.height * scaleY),
  };
}

export function browserTraceBounds(target: Record<string, unknown>, elementMap: SessionBrowserElement[]) {
  const rawBounds = recordValue(target.bounds);
  const bounds = normalizeBounds(rawBounds);
  if (bounds) return bounds;
  const nodeId = String(target.node_id ?? "");
  if (!nodeId) return undefined;
  return elementMap.find((item) => item.node_id === nodeId)?.bounds;
}

export function normalizeBounds(value: Record<string, unknown>) {
  const x = numericValue(value.x);
  const y = numericValue(value.y);
  const width = numericValue(value.width);
  const height = numericValue(value.height);
  if (x === undefined || y === undefined || width === undefined || height === undefined) return undefined;
  return { x, y, width, height };
}
