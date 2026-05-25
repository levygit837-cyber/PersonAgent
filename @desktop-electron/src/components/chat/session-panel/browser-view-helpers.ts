import type {
  SessionBrowserAnnotation,
  SessionBrowserElement,
  SessionBrowserTimelineEvent,
  SessionBrowserView,
} from "../../../api/client";
import {
  type BrowserState,
  type BrowserToolEvent,
  type BrowserElementMetadata,
  browserStringValue,
  isMeaningfulBrowserUrl,
  normalizeBrowserElementMetadata,
  normalizeComparableUrl,
  numericValue,
  recordArray,
  recordValue,
  BROWSER_TOOL_HYDRATE_NAMES,
  BROWSER_TOOL_NAVIGATION_VIEW_NAMES,
  BROWSER_TOOL_PASSIVE_VIEW_NAMES,
} from "./helpers";

function browserToolEventIsPassive(visual: BrowserToolEvent) {
  return BROWSER_TOOL_PASSIVE_VIEW_NAMES.has(visual.toolName);
}

function browserToolElements(data: Record<string, unknown>) {
  const rawElements = recordArray(data.elements).length ? recordArray(data.elements) : recordArray(data.element_map);
  return rawElements
    .map((item, index) => normalizeBrowserElementMetadata(item, browserStringValue(item.node_id) || `browser_tool_${index}`))
    .filter((item): item is BrowserElementMetadata => Boolean(item));
}

export function browserHasMeaningfulPage(browser: BrowserState | undefined) {
  return Boolean(isMeaningfulBrowserUrl(browser?.currentUrl) || isMeaningfulBrowserUrl(browser?.view?.url));
}

export function browserToolShouldHydrateView(visual: BrowserToolEvent) {
  return BROWSER_TOOL_HYDRATE_NAMES.has(visual.toolName);
}

export function browserToolShouldSyncDisplayedPage(visual: BrowserToolEvent, browser?: BrowserState) {
  if (browserToolEventIsPassive(visual)) return false;
  if (BROWSER_TOOL_NAVIGATION_VIEW_NAMES.has(visual.toolName)) return true;
  if (visual.toolName === "BrowserScreenshot" || visual.toolName === "BrowserScroll") {
    return Boolean(browserViewFromToolEvent(visual));
  }
  if (visual.toolName === "BrowserClick" || visual.toolName === "BrowserType" || visual.toolName === "BrowserAct") {
    return (
      Boolean(visual.data.navigated) ||
      Boolean(browserViewFromToolEvent(visual)) ||
      browserToolHasCachedRender(visual) ||
      browserToolNeedsInitialView(visual, browser) ||
      (visual.status === "completed" && browserToolUrlChanged(visual, browser))
    );
  }
  return false;
}

export function browserToolShouldFetchRenderedView(visual: BrowserToolEvent, browser?: BrowserState) {
  if (browserToolEventIsPassive(visual)) return false;
  if (BROWSER_TOOL_NAVIGATION_VIEW_NAMES.has(visual.toolName)) return true;
  if (visual.toolName === "BrowserClick" || visual.toolName === "BrowserType" || visual.toolName === "BrowserAct") {
    return (
      Boolean(visual.data.navigated) ||
      browserToolHasCachedRender(visual) ||
      browserToolNeedsInitialView(visual, browser) ||
      (visual.status === "completed" && browserToolUrlChanged(visual, browser))
    );
  }
  return false;
}

export function browserToolShouldPreserveCurrentView(visual: BrowserToolEvent) {
  return (
    visual.toolName === "BrowserClick" ||
    visual.toolName === "BrowserType" ||
    visual.toolName === "BrowserAct"
  ) && (Boolean(visual.target) || Boolean(visual.nodeId) || visual.elements.length > 0);
}

export function browserViewFromToolEvent(visual: BrowserToolEvent): SessionBrowserView | undefined {
  const data = visual.data;
  const elements = browserToolElements(data);
  const documentHtml = browserStringValue(data.document_html) || browserStringValue(data.html) || "";
  const hasRenderableView = Boolean(
    (browserStringValue(data.url) || visual.url) &&
      (browserStringValue(data.image_data) || documentHtml),
  );
  if (!hasRenderableView) return undefined;
  return {
    ...data,
    type: "browser_view",
    browser_id: browserStringValue(data.browser_id) || browserStringValue(data.active_browser_id) || visual.browserId || "",
    url: browserStringValue(data.final_url) || browserStringValue(data.url) || visual.url || "",
    title: browserStringValue(data.title) || "",
    html: browserStringValue(data.html) || documentHtml,
    document_html: documentHtml,
    render_mode: browserRenderModeValue(data.render_mode) || "html_mirror",
    css_fidelity: browserStringValue(data.css_fidelity) || "pixel",
    render_cache_key: browserStringValue(data.render_cache_key),
    render_cache_status: browserStringValue(data.render_cache_status),
    style_ready: typeof data.style_ready === "boolean" ? data.style_ready : undefined,
    stylesheet_count: numericValue(data.stylesheet_count),
    stylesheet_loaded_count: numericValue(data.stylesheet_loaded_count),
    stylesheet_cached_count: numericValue(data.stylesheet_cached_count),
    visual_events: recordArray(data.visual_events),
    element_map: elements,
    annotations: Array.isArray(data.annotations) ? (data.annotations as SessionBrowserAnnotation[]) : [],
    timeline_events: Array.isArray(data.timeline_events) ? (data.timeline_events as SessionBrowserTimelineEvent[]) : [],
    user_agent: browserStringValue(data.user_agent) || "",
    image_data: browserStringValue(data.image_data) || "",
    image_mime_type: browserStringValue(data.image_mime_type) || "",
    screenshot_method: browserStringValue(data.screenshot_method) || "",
    screenshot_error: browserStringValue(data.screenshot_error) || "",
    viewport_width: numericValue(data.viewport_width) || 1024,
    viewport_height: numericValue(data.viewport_height) || 720,
    scroll_x: numericValue(data.scroll_x) || 0,
    scroll_y: numericValue(data.scroll_y) || 0,
    can_capture: typeof data.can_capture === "boolean" ? data.can_capture : Boolean(browserStringValue(data.image_data)),
  };
}

export function browserSnapshotViewFromToolEvent(visual: BrowserToolEvent): SessionBrowserView | undefined {
  const elements = browserToolElements(visual.data);
  const url = browserMeaningfulToolUrl(visual);
  if (!url || !elements.some((element) => element.bounds)) return undefined;
  return {
    ...visual.data,
    type: "browser_view",
    browser_id: browserStringValue(visual.data.browser_id) || browserStringValue(visual.data.active_browser_id) || visual.browserId || "",
    url,
    title: browserStringValue(visual.data.title) || "",
    html: "",
    document_html: "",
    render_mode: "screenshot",
    css_fidelity: browserStringValue(visual.data.css_fidelity) || "pixel",
    element_map: elements,
    annotations: [],
    timeline_events: [],
    user_agent: "",
    image_data: "",
    image_mime_type: "",
    screenshot_method: "",
    screenshot_error: "",
    viewport_width: numericValue(visual.data.viewport_width) || 1024,
    viewport_height: numericValue(visual.data.viewport_height) || 720,
    scroll_x: numericValue(visual.data.scroll_x) || 0,
    scroll_y: numericValue(visual.data.scroll_y) || 0,
    can_capture: false,
  };
}

export function browserToolEventUrl(visual: BrowserToolEvent) {
  return browserStringValue(visual.data.final_url) || browserStringValue(visual.data.url) || visual.url || "";
}

export function browserMeaningfulToolUrl(visual: BrowserToolEvent) {
  const url = browserToolEventUrl(visual);
  return isMeaningfulBrowserUrl(url) ? url : "";
}

export function browserToolUrlChanged(visual: BrowserToolEvent, browser?: BrowserState) {
  const url = browserMeaningfulToolUrl(visual);
  if (!url || !browser?.currentUrl) return Boolean(url && !browser?.currentUrl);
  return normalizeComparableUrl(url) !== normalizeComparableUrl(browser.currentUrl);
}

export function browserToolHasCachedRender(visual: BrowserToolEvent) {
  return Boolean(browserStringValue(visual.data.render_cache_key) || browserStringValue(visual.data.render_cache_status));
}

export function browserToolNeedsInitialView(visual: BrowserToolEvent, browser?: BrowserState) {
  return visual.status === "completed" && Boolean(browserMeaningfulToolUrl(visual)) && !browser?.view;
}

export function browserRenderModeValue(value: unknown): SessionBrowserView["render_mode"] {
  const mode = browserStringValue(value);
  if (mode === "html_mirror" || mode === "computed_html" || mode === "pixel" || mode === "screenshot") return mode;
  return "screenshot";
}
