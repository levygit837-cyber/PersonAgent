import type { MouseEvent } from "react";
import type {
  SessionBrowserAnnotation,
  SessionBrowserElement,
  SessionBrowserTimelineEvent,
  SessionBrowserView,
  SessionBrowserViewport,
} from "../../../api/client";
import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { ToolBlockStatus, ToolBlockUi } from "../../../types/chat";
import {
  type BrowserElementMetadata,
  type BrowserState,
  type BrowserTab,
  type BrowserTextSelectionMetadata,
  type BrowserToolEvent,
  type BrowserVisualEffect,
  type BrowserVisualEvent,
  browserPagePanelTabId,
  browserStringValue,
  browserViewIsPlaceholder,
  createEmptyBrowserState,
  incrementComposerAnnotationSequence,
  isMeaningfulBrowserUrl,
  normalizeComparableUrl,
  numericValue,
  recordArray,
  recordValue,
  BROWSER_TOOL_HYDRATE_NAMES,
  BROWSER_TOOL_NAVIGATION_VIEW_NAMES,
  BROWSER_TOOL_PASSIVE_VIEW_NAMES,
} from "./helpers";
import { browserToolEventFromBlock } from "./browser-visual-events";


export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

export function labelize(value: string) {
  return value.replace(/_/g, " ");
}

export function normalizeBrowserUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

export function browserVisualEventsFromBlocks(blocks: ToolBlockUi[]): BrowserVisualEvent[] {
  const events: BrowserVisualEvent[] = [];
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const visual = browserToolEventFromBlock(blocks[index]);
    if (visual) events.push(visual);
    if (events.length >= 12) return events;
  }
  return events;
}

export function browserToolEventAppliesToBrowser(visual: BrowserToolEvent | undefined, browser: BrowserState) {
  if (!visual) return false;
  const viewRecord = recordValue(browser.view);
  const browserIds = new Set(
    [
      browser.browserId,
      browser.view?.browser_id,
      browser.view?.active_tab_id,
      viewRecord.page_id,
      viewRecord.window_id,
    ]
      .map((value) => (typeof value === "string" ? value.trim() : ""))
      .filter(Boolean),
  );
  const visualIds = [visual.browserId, visual.pageId, visual.windowId]
    .map((value) => (typeof value === "string" ? value.trim() : ""))
    .filter(Boolean);
  if (visualIds.length && visualIds.some((id) => browserIds.has(id))) return true;
  const visualUrl = isMeaningfulBrowserUrl(visual.url) ? visual.url : "";
  if (visualUrl && browser.currentUrl) {
    return normalizeComparableUrl(visualUrl) === normalizeComparableUrl(browser.currentUrl);
  }
  if (visualIds.length && browser.currentUrl) return true;
  if (!visualIds.length) return true;
  return false;
}

export function browserToolEventIsPassive(visual: BrowserToolEvent) {
  return BROWSER_TOOL_PASSIVE_VIEW_NAMES.has(visual.toolName);
}

export function browserToolEventIsAction(visual: BrowserToolEvent) {
  return visual.toolName === "BrowserClick" || visual.toolName === "BrowserType" || visual.toolName === "BrowserAct";
}


export function browserTimestampValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function browserVisualEffectValue(value: unknown): BrowserVisualEffect | undefined {
  if (value === "map" || value === "click" || value === "type" || value === "scroll" || value === "extract" || value === "highlight") {
    return value;
  }
  return undefined;
}

export function browserToolStatusValue(value: unknown): ToolBlockStatus {
  if (value === "queued" || value === "running" || value === "completed" || value === "error" || value === "permission_required") {
    return value;
  }
  return "running";
}



export function browserAnnotationCounts(annotations: SessionBrowserAnnotation[]) {
  return annotations.reduce<Record<string, number>>((counts, annotation) => {
    if (!annotation.node_id) return counts;
    counts[annotation.node_id] = (counts[annotation.node_id] || 0) + 1;
    return counts;
  }, {});
}

export function browserAnnotationEditorStyle(bounds?: BrowserElementMetadata["bounds"], view?: SessionBrowserView) {
  const width = 360;
  const height = 168;
  const viewportWidth = view?.viewport_width || 420;
  const viewportHeight = view?.viewport_height || 640;
  if (!bounds) {
    return { left: 12, bottom: 12, width: "min(360px, calc(100% - 24px))" };
  }
  const preferredTop =
    bounds.y + bounds.height + height + 14 <= viewportHeight ? bounds.y + bounds.height + 10 : bounds.y - height - 10;
  const left = Math.max(12, Math.min(bounds.x, Math.max(12, viewportWidth - width - 12)));
  const top = Math.max(12, Math.min(preferredTop, Math.max(12, viewportHeight - height - 12)));
  return {
    left,
    top,
    width: "min(360px, calc(100% - 24px))",
  };
}

export function localBrowserAnnotation({
  browserId,
  nodeId,
  body,
  quote,
  url,
  title,
}: {
  browserId: string;
  nodeId: string;
  body: string;
  quote?: string;
  url?: string;
  title?: string;
}): SessionBrowserAnnotation {
  return {
    id: `browser_ann_${Date.now()}`,
    browser_id: browserId,
    node_id: nodeId,
    body,
    quote,
    url,
    title,
    created_at: new Date().toISOString(),
  };
}

export function browserAnnotationToComposerAnnotation({
  annotation,
  element,
  fallbackUrl,
  fallbackTitle,
}: {
  annotation: SessionBrowserAnnotation;
  element?: SessionBrowserElement;
  fallbackUrl?: string;
  fallbackTitle?: string;
}): ComposerAnnotation {
  const url = annotation.url || fallbackUrl || "";
  const title = annotation.title || fallbackTitle || browserHostname(url) || "Browser";
  const quote = annotation.quote || element?.text || "";
  const role = element?.role || element?.tag || "element";
  const id = nextComposerAnnotationId();
  return {
    id,
    source: "browser",
    fileName: title,
    filePath: url,
    displayPath: browserAnnotationDisplayPath(url, title),
    startLine: 1,
    endLine: 1,
    text: annotation.body,
    selectedLines: [
      `URL: ${url || "(unknown)"}`,
      `Title: ${title || "(untitled)"}`,
      `Element: ${role} ${annotation.node_id}`,
      element?.selector ? `Selector: ${element.selector}` : "",
      quote ? `Visible text: ${quote}` : "",
    ].filter(Boolean).join("\n"),
    language: "browser",
    browserUrl: url,
    browserTitle: title,
    browserNodeId: annotation.node_id,
    browserSelector: element?.selector,
    browserRole: role,
    browserQuote: quote,
  };
}

export function browserTextSelectionToComposerAnnotation({
  selection,
  fallbackUrl,
  fallbackTitle,
}: {
  selection: BrowserTextSelectionMetadata;
  fallbackUrl?: string;
  fallbackTitle?: string;
}): ComposerAnnotation {
  const url = fallbackUrl || "";
  const title = fallbackTitle || browserHostname(url) || "Browser";
  const role = selection.role || selection.tag || "text";
  const id = nextComposerAnnotationId();
  return {
    id,
    source: "browser",
    fileName: title,
    filePath: url,
    displayPath: browserAnnotationDisplayPath(url, title),
    startLine: 1,
    endLine: 1,
    text: "Selected browser text",
    selectedLines: [
      `URL: ${url || "(unknown)"}`,
      `Title: ${title || "(untitled)"}`,
      `Element: ${role}${selection.node_id ? ` ${selection.node_id}` : ""}`,
      selection.selector ? `Selector: ${selection.selector}` : "",
      typeof selection.start_offset === "number" && typeof selection.end_offset === "number"
        ? `Text offsets: ${selection.start_offset}-${selection.end_offset}`
        : "",
      `Selected text: ${selection.text}`,
    ].filter(Boolean).join("\n"),
    language: "browser",
    browserUrl: url,
    browserTitle: title,
    browserNodeId: selection.node_id,
    browserSelector: selection.selector,
    browserRole: role,
    browserQuote: selection.text,
  };
}

export function normalizeBrowserTextSelection(value: unknown): BrowserTextSelectionMetadata | undefined {
  if (!value || typeof value !== "object") return undefined;
  const source = value as Record<string, unknown>;
  const text = typeof source.text === "string" ? source.text.trim() : "";
  if (!text) return undefined;
  const boundsValue = source.bounds as Record<string, unknown> | undefined;
  const bounds =
    boundsValue &&
    typeof boundsValue.x === "number" &&
    typeof boundsValue.y === "number" &&
    typeof boundsValue.width === "number" &&
    typeof boundsValue.height === "number"
      ? {
          x: boundsValue.x,
          y: boundsValue.y,
          width: boundsValue.width,
          height: boundsValue.height,
        }
      : undefined;
  return {
    text,
    node_id: typeof source.node_id === "string" ? source.node_id : undefined,
    selector: typeof source.selector === "string" ? source.selector : undefined,
    role: typeof source.role === "string" ? source.role : undefined,
    tag: typeof source.tag === "string" ? source.tag : undefined,
    start_offset: typeof source.start_offset === "number" ? source.start_offset : undefined,
    end_offset: typeof source.end_offset === "number" ? source.end_offset : undefined,
    bounds,
  };
}

export function nextComposerAnnotationId() {
  return Date.now() + incrementComposerAnnotationSequence();
}

export function browserAnnotationDisplayPath(url: string, title: string) {
  const host = browserHostname(url);
  if (host && title && title !== host) return `${title} · ${host}`;
  return host || title || "Browser";
}

export function browserHostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}


