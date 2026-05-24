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
  recordValue,
  BROWSER_TOOL_HYDRATE_NAMES,
  BROWSER_TOOL_NAVIGATION_VIEW_NAMES,
  BROWSER_TOOL_PASSIVE_VIEW_NAMES,
} from "./helpers";


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

export function browserTabsFromBlocks(blocks: ToolBlockUi[], conversationId?: string | null): BrowserTab[] {
  const tabs: BrowserTab[] = [];
  const seen = new Set<string>();
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    if (!["BrowserOpen", "BrowserListTabs", "BrowserCloseTab", "BrowserSwitchTab"].includes(block.name)) continue;
    const blockTabs = browserTabsFromToolBlock(block, conversationId);
    for (const tab of blockTabs) {
      if (seen.has(tab.id)) continue;
      seen.add(tab.id);
      tabs.push(tab);
    }
    if (tabs.length >= 50) return tabs;
  }
  return tabs;
}

export function browserTabsFromToolBlock(block: ToolBlockUi, conversationId?: string | null): BrowserTab[] {
  const data = block.data ?? {};
  const rawTabs = recordArray(data.tabs);
  const browserId =
    browserStringValue(data.browser_id) ||
    browserStringValue(data.active_browser_id) ||
    conversationId ||
    "";
  const activeTabId =
    browserStringValue(data.active_tab_id) ||
    browserStringValue(data.last_open_page_id) ||
    browserStringValue(data.page_id) ||
    browserStringValue(data.window_id) ||
    "";
  const sourceTabs =
    rawTabs.length > 0
      ? rawTabs
      : block.name === "BrowserOpen"
        ? [
            {
              ...data,
              page_id: browserStringValue(data.page_id) || browserStringValue(data.window_id) || activeTabId || browserId,
              tab_id: browserStringValue(data.page_id) || browserStringValue(data.window_id) || activeTabId || browserId,
              url: browserStringValue(data.final_url) || browserStringValue(data.url),
              title: browserStringValue(data.title),
              active: true,
              is_active: true,
            },
          ]
        : [];
  return sourceTabs
    .map((item, index) => browserTabFromToolTab(item, { browserId, activeTabId, index, sourceToolName: block.name }))
    .filter((tab): tab is BrowserTab => Boolean(tab));
}

export function browserTabFromToolTab(
  item: Record<string, unknown>,
  {
    browserId,
    activeTabId,
    index,
    sourceToolName,
  }: {
    browserId: string;
    activeTabId: string;
    index: number;
    sourceToolName: string;
  },
): BrowserTab | undefined {
  const pageId =
    browserStringValue(item.page_id) ||
    browserStringValue(item.window_id) ||
    browserStringValue(item.tab_id) ||
    browserStringValue(item.id) ||
    browserId;
  const resolvedBrowserId = browserStringValue(item.browser_id) || browserId || pageId;
  const url = browserStringValue(item.final_url) || browserStringValue(item.url) || "";
  if (!pageId && !url) return undefined;
  const title = browserStringValue(item.title) || browserStringValue(item.summary) || browserDomainLabel(url) || `Browser ${index + 1}`;
  const isActive =
    Boolean(item.active) ||
    Boolean(item.is_active) ||
    Boolean(item.is_current_page) ||
    Boolean(item.is_last_open) ||
    (activeTabId ? pageId === activeTabId : index === 0);
  const candidateView = browserViewFromTabRecord(item, resolvedBrowserId, pageId, url, title, isActive);
  const view = sourceToolName === "BrowserOpen" && browserViewIsPlaceholder(candidateView) ? undefined : candidateView;
  return {
    id: browserPagePanelTabId(resolvedBrowserId, pageId || url),
    title,
    subtitle: url,
    closeable: true,
    browser: {
      ...createEmptyBrowserState(resolvedBrowserId),
      pageId,
      currentUrl: url,
      draftUrl: url,
      history: browserStringArray(item.history),
      historyIndex: browserStringArray(item.history).length ? browserStringArray(item.history).length - 1 : url ? 0 : -1,
      loading: sourceToolName === "BrowserOpen" && Boolean(url) && !view,
      view,
    },
  };
}

export function browserViewFromTabRecord(
  item: Record<string, unknown>,
  browserId: string,
  pageId: string,
  url: string,
  title: string,
  active: boolean,
): SessionBrowserView | undefined {
  if (!url) return undefined;
  const dataView = browserViewFromToolEvent({
    id: `browser-tab:${pageId || url}`,
    toolName: "BrowserOpen",
    status: "completed",
    effect: "highlight",
    browserId,
    pageId,
    url,
    elements: [],
    data: item,
  });
  if (dataView) return { ...dataView, active_tab_id: pageId || dataView.active_tab_id };
  return {
    type: "browser_view",
    browser_id: browserId,
    url,
    title,
    html: "",
    document_html: "",
    render_mode: "html_mirror",
    render_cache_status: "hit",
    runtime: browserStringValue(item.runtime) || "lightpanda",
    tabs: [
      {
        tab_id: pageId || browserId,
        id: pageId || browserId,
        url,
        title,
        runtime: browserStringValue(item.runtime) || "lightpanda",
        active,
        is_active: active,
        history: browserStringArray(item.history),
        state: recordValue(item.state),
      },
    ],
    active_tab_id: active ? pageId || browserId : undefined,
    element_map: [],
    annotations: [],
    timeline_events: [],
    user_agent: "",
    image_data: "",
    image_mime_type: "",
    screenshot_method: "",
    viewport_width: 1024,
    viewport_height: 720,
    can_capture: false,
  };
}

export function browserDomainLabel(url: string) {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function browserStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

export function browserToolEventFromBlock(block: ToolBlockUi): BrowserVisualEvent | undefined {
  const effect = browserToolEffect(block);
  if (!effect) return undefined;
  const data = block.data ?? {};
  const lastAction = recordValue(data.last_action);
  const result = recordValue(lastAction.result);
  const elements = browserToolElements(data);
  const nodeId =
    browserStringValue(lastAction.node_id) ??
    browserStringValue(data.node_id) ??
    browserStringValue(data.target_node_id);
  const mappedTarget =
    normalizeBrowserElementMetadata(lastAction.target, nodeId || "") ??
    (nodeId ? elements.find((element) => element.node_id === nodeId) : undefined);
  const resultTarget = normalizeBrowserElementMetadata(
    { ...result, node_id: nodeId || result.node_id || "browser_result" },
    nodeId || "browser_result",
  );
  const target =
    mappedTarget && resultTarget?.bounds
      ? {
          ...mappedTarget,
          bounds: resultTarget.bounds,
          tag: resultTarget.tag || mappedTarget.tag,
          selector: resultTarget.selector || mappedTarget.selector,
        }
      : mappedTarget ?? resultTarget;
  const x = numericValue(lastAction.x ?? data.x);
  const y = numericValue(lastAction.y ?? data.y);
  return {
    id: `${block.id}:${block.status}:${browserStringValue(data.type) || block.name}`,
    toolName: block.name,
    status: block.status,
    effect,
    browserId: browserStringValue(data.browser_id) ?? browserStringValue(data.active_browser_id),
    pageId: browserStringValue(data.page_id) ?? browserStringValue(data.active_tab_id),
    windowId: browserStringValue(data.window_id),
    url: browserStringValue(data.final_url) ?? browserStringValue(data.url),
    nodeId,
    target,
    elements,
    coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
    startedAt: browserTimestampValue(data.started_at ?? data.created_at),
    completedAt: block.status === "completed" ? browserTimestampValue(data.completed_at ?? data.finished_at) : undefined,
    data,
  };
}

export function browserToolEffect(block: ToolBlockUi): BrowserVisualEffect | undefined {
  if (!block.name.startsWith("Browser")) return undefined;
  if (block.name === "BrowserListTabs" || block.name === "BrowserCloseTab" || block.name === "BrowserWait") {
    return undefined;
  }
  if (block.name === "BrowserGetElementMap") return "map";
  if (block.name === "BrowserClick") return "click";
  if (block.name === "BrowserType") return "type";
  if (block.name === "BrowserScroll" || block.name === "BrowserHistory") return "scroll";
  if (
    block.name === "BrowserScreenshot" ||
    block.name === "BrowserExtractContent" ||
    block.name === "BrowserReadContentChunk" ||
    block.name === "BrowserGetHtml"
  ) return "extract";
  if (block.name === "BrowserAct") {
    const data = block.data ?? {};
    const action = String(recordValue(data.last_action).action ?? data.action ?? "").toLowerCase();
    if (/click|submit|hover/.test(action)) return "click";
    if (/type|fill|press|select/.test(action)) return "type";
    if (/scroll/.test(action)) return "scroll";
    if (/screenshot|text|html/.test(action)) return "extract";
    return "highlight";
  }
  return "highlight";
}

export function browserVisualEventsFromRecords(value: unknown): BrowserVisualEvent[] {
  return recordArray(value)
    .map<BrowserVisualEvent | undefined>((item, index) => {
      const toolName = browserStringValue(item.toolName) || browserStringValue(item.tool_name) || "BrowserAction";
      const effect =
        browserVisualEffectValue(item.effect) ||
        browserEffectFromToolAction(toolName, browserStringValue(recordValue(item).action));
      if (!effect) return undefined;
      const target = normalizeBrowserElementMetadata(recordValue(item.target), browserStringValue(recordValue(item.target).node_id) || "");
      const x = numericValue(item.x ?? recordValue(item.coordinates).x);
      const y = numericValue(item.y ?? recordValue(item.coordinates).y);
      return {
        id: browserStringValue(item.id) || `browser-view-visual-${index}`,
        toolName,
        status: browserToolStatusValue(item.status),
        effect,
        browserId: browserStringValue(item.browserId) || browserStringValue(item.browser_id),
        pageId: browserStringValue(item.pageId) || browserStringValue(item.page_id),
        windowId: browserStringValue(item.windowId) || browserStringValue(item.window_id),
        url: browserStringValue(item.url),
        nodeId: browserStringValue(item.nodeId) || browserStringValue(item.node_id),
        target,
        elements: browserToolElements({ element_map: item.elements ?? item.element_map }),
        coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
        startedAt: browserTimestampValue(item.startedAt ?? item.started_at),
        completedAt: browserTimestampValue(item.completedAt ?? item.completed_at),
        data: recordValue(item),
      };
    })
    .filter((event): event is BrowserVisualEvent => Boolean(event));
}

export function browserVisualEventFromProposal(proposal: Record<string, unknown>, browser: BrowserState): BrowserVisualEvent {
  const args = recordValue(proposal.arguments);
  const targetRecord = recordValue(proposal.target);
  const nodeId = browserStringValue(targetRecord.node_id) || browserStringValue(args.node_id) || browserStringValue(args.target_node_id);
  const toolName = browserStringValue(proposal.tool_name) || browserStringValue(args.tool_name) || "BrowserAction";
  const action = browserStringValue(args.action) || browserStringValue(proposal.action);
  const x = numericValue(args.x ?? targetRecord.x ?? recordValue(targetRecord.coordinates).x);
  const y = numericValue(args.y ?? targetRecord.y ?? recordValue(targetRecord.coordinates).y);
  return {
    id: browserStringValue(proposal.proposal_id) || browserStringValue(proposal.approval_id) || `${toolName}:${nodeId || browser.currentUrl}`,
    toolName,
    status: "permission_required",
    effect: browserEffectFromToolAction(toolName, action) || "highlight",
    browserId: browserStringValue(proposal.browser_id) || browser.browserId,
    pageId: browserStringValue(proposal.page_id) || browser.view?.active_tab_id,
    url: browserStringValue(proposal.url) || browser.currentUrl,
    nodeId,
    target: normalizeBrowserElementMetadata(targetRecord, nodeId || "proposal_target"),
    elements: [],
    coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
    startedAt: browserTimestampValue(proposal.created_at),
    data: proposal,
  };
}

export function browserEffectFromToolAction(toolName: string, action?: string): BrowserVisualEffect | undefined {
  const syntheticBlock: ToolBlockUi = {
    id: toolName,
    name: toolName,
    status: "running",
    title: toolName,
    message: "",
    content: "",
    data: { action },
    isCollapsed: true,
  };
  return browserToolEffect(syntheticBlock);
}

export function browserToolElements(data: Record<string, unknown>) {
  const rawElements = recordArray(data.elements).length ? recordArray(data.elements) : recordArray(data.element_map);
  return rawElements
    .map((item, index) => normalizeBrowserElementMetadata(item, browserStringValue(item.node_id) || `browser_tool_${index}`))
    .filter((item): item is BrowserElementMetadata => Boolean(item));
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

export function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
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

export function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    : [];
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

export function normalizeBrowserElementMetadata(value: unknown, fallbackNodeId: string): BrowserElementMetadata | undefined {
  if (!value || typeof value !== "object") return undefined;
  const source = value as Record<string, unknown>;
  const nodeId = typeof source.node_id === "string" && source.node_id ? source.node_id : fallbackNodeId;
  if (!nodeId) return undefined;
  const boundsValue = source.bounds as Record<string, unknown> | undefined;
  const boundsX = numericValue(boundsValue?.x);
  const boundsY = numericValue(boundsValue?.y);
  const boundsWidth = numericValue(boundsValue?.width);
  const boundsHeight = numericValue(boundsValue?.height);
  const bounds =
    boundsX !== undefined &&
    boundsY !== undefined &&
    boundsWidth !== undefined &&
    boundsHeight !== undefined
      ? {
          x: boundsX,
          y: boundsY,
          width: boundsWidth,
          height: boundsHeight,
        }
      : undefined;
  return {
    node_id: nodeId,
    tab_id: typeof source.tab_id === "string" ? source.tab_id : undefined,
    frame_id: typeof source.frame_id === "string" ? source.frame_id : undefined,
    frame_url: typeof source.frame_url === "string" ? source.frame_url : undefined,
    role: typeof source.role === "string" ? source.role : undefined,
    tag: typeof source.tag === "string" ? source.tag : undefined,
    text: typeof source.text === "string" ? source.text : undefined,
    selector: typeof source.selector === "string" ? source.selector : undefined,
    selector_chain: Array.isArray(source.selector_chain) ? source.selector_chain.filter((item): item is string => typeof item === "string") : undefined,
    shadow_path: Array.isArray(source.shadow_path) ? source.shadow_path.filter((item): item is string => typeof item === "string") : undefined,
    stable_key: typeof source.stable_key === "string" ? source.stable_key : undefined,
    interactable: typeof source.interactable === "boolean" ? source.interactable : undefined,
    computed_summary: source.computed_summary && typeof source.computed_summary === "object" && !Array.isArray(source.computed_summary)
      ? (source.computed_summary as Record<string, unknown>)
      : undefined,
    href: typeof source.href === "string" ? source.href : undefined,
    name: typeof source.name === "string" ? source.name : undefined,
    input_type: typeof source.input_type === "string" ? source.input_type : undefined,
    form_method: typeof source.form_method === "string" ? source.form_method : undefined,
    form_action: typeof source.form_action === "string" ? source.form_action : undefined,
    bounds,
    visible: typeof source.visible === "boolean" ? source.visible : undefined,
    color: typeof source.color === "string" ? source.color : undefined,
    background: typeof source.background === "string" ? source.background : undefined,
    font: typeof source.font === "string" ? source.font : undefined,
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


export function browserCssLabel(value?: string) {
  if (value === "pixel") return "Pixel render";
  if (value === "original_embedded") return "Original + Embedded CSS";
  if (value === "embedded") return "Embedded CSS";
  if (value === "computed") return "Computed CSS";
  if (value === "fallback_html") return "Fallback HTML";
  return "Original CSS";
}

export function browserCssBadgeClass(value?: string) {
  if (value === "fallback_html") return "border-warning/40 bg-warning/10 text-warning";
  if (value === "original_embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "computed") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "pixel") return "border-success/35 bg-success/10 text-success";
  return "border-glass-border/35 bg-card/70 text-muted-foreground";
}

export function selectedElementLabel(element: SessionBrowserElement | undefined, nodeId: string) {
  if (!element) return nodeId;
  const role = element.role || element.tag || "element";
  const text = element.text ? ` · ${element.text.slice(0, 90)}` : "";
  return `${role}${text}`;
}
