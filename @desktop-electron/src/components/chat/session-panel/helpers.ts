/**
 * Pure helper functions and constants for the SessionPanel.
 *
 * Extracted from `session-panel.tsx` (session_panel Slice 1).
 */

import type {
  SessionBrowserCooperationEvent,
  SessionBrowserElement,
  SessionBrowserView,
  SessionBrowserViewport,
} from "../../../api/client";
import type { ToolBlockStatus } from "../../../types/chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BrowserTab = {
  id: string;
  title: string;
  subtitle?: string;
  closeable: boolean;
  detail?: import("../session-detail-window").SessionDetailView;
  browser?: BrowserState;
};

export type BrowserState = {
  browserId: string;
  pageId?: string;
  currentUrl: string;
  draftUrl: string;
  history: string[];
  historyIndex: number;
  mode: "browse" | "annotate";
  selectedNodeId?: string;
  elementMetadata: Record<string, BrowserElementMetadata>;
  annotationDraft: string;
  loading: boolean;
  requestId: number;
  error?: string;
  view?: SessionBrowserView;
};

export type BrowserElementMetadata = SessionBrowserElement & {
  color?: string;
  background?: string;
  font?: string;
};

export type BrowserTextSelectionMetadata = {
  text: string;
  node_id?: string;
  selector?: string;
  role?: string;
  tag?: string;
  start_offset?: number;
  end_offset?: number;
  bounds?: { x: number; y: number; width: number; height: number };
};

export type BrowserTracingTab = "timeline" | "raw" | "state" | "agent" | "proposals";

export type BrowserVisualEffect = "map" | "click" | "type" | "scroll" | "extract" | "highlight";

export type BrowserVisualEvent = {
  id: string;
  toolName: string;
  status: ToolBlockStatus;
  effect: BrowserVisualEffect;
  browserId?: string;
  pageId?: string;
  windowId?: string;
  url?: string;
  nodeId?: string;
  target?: BrowserElementMetadata;
  elements: BrowserElementMetadata[];
  coordinates?: { x: number; y: number };
  startedAt?: number;
  completedAt?: number;
  data: Record<string, unknown>;
};

export type BrowserToolEvent = BrowserVisualEvent;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const summaryTab: BrowserTab = {
  id: "summary",
  title: "Summary",
  closeable: false,
};

export const SESSION_PANEL_STREAMING_REFETCH_MS = 1_500;
export const SESSION_PANEL_STALE_MS = 5 * 60_000;
export const BROWSER_LOADING_MESSAGES = [
  "Preparando o ambiente...",
  "Baixando HTML da pagina...",
  "Aplicando CSS original...",
  "Estilizando seu site...",
  "Mapeando elementos clicaveis...",
];
export const BROWSER_RENDER_CACHE_LIMIT = 32;
export const BROWSER_TOOL_VIEW_SETTLE_MS = 650;
export const BROWSER_TOOL_HYDRATE_NAMES = new Set([
  "BrowserOpen",
  "BrowserGetElementMap",
  "BrowserExtractContent",
  "BrowserReadContentChunk",
  "BrowserGetHtml",
  "BrowserClick",
  "BrowserType",
  "BrowserScreenshot",
  "BrowserScroll",
  "BrowserReload",
  "BrowserHistory",
  "BrowserSwitchTab",
  "BrowserWait",
  "BrowserAct",
]);
export const BROWSER_TOOL_PASSIVE_VIEW_NAMES = new Set([
  "BrowserGetElementMap",
  "BrowserExtractContent",
  "BrowserReadContentChunk",
  "BrowserGetHtml",
]);
export const BROWSER_TOOL_NAVIGATION_VIEW_NAMES = new Set([
  "BrowserOpen",
  "BrowserReload",
  "BrowserHistory",
  "BrowserSwitchTab",
]);

// ---------------------------------------------------------------------------
// Module-level render cache
// ---------------------------------------------------------------------------

export const browserRenderCache = new Map<string, SessionBrowserView>();
export const browserRenderCacheByUrl = new Map<string, string>();
export let composerAnnotationSequence = 0;
export function incrementComposerAnnotationSequence() {
  return ++composerAnnotationSequence;
}

// ---------------------------------------------------------------------------
// Small utility helpers (used by other helpers)
// ---------------------------------------------------------------------------

export function isMeaningfulBrowserUrl(url: string | undefined) {
  const normalized = url?.trim();
  return Boolean(normalized && normalized !== "about:blank");
}

export function normalizeComparableUrl(value: string) {
  return value.trim().replace(/\/+$/, "");
}

export function browserStringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return undefined;
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

// ---------------------------------------------------------------------------
// Pure helper functions
// ---------------------------------------------------------------------------

export function createEmptyBrowserState(browserId = `browser:${Date.now()}`): BrowserState {
  return {
    browserId,
    pageId: undefined,
    currentUrl: "",
    draftUrl: "",
    history: [],
    historyIndex: -1,
    mode: "browse",
    elementMetadata: {},
    annotationDraft: "",
    loading: false,
    requestId: 0,
  };
}

export function browserPanelTabId(browserId: string) {
  return browserId.startsWith("browser:") ? browserId : `browser:${browserId}`;
}

export function browserPagePanelTabId(browserId: string, pageId: string) {
  const normalizedBrowserId = browserId || "browser";
  const normalizedPageId = pageId || normalizedBrowserId;
  return `browser:${normalizedBrowserId}:${normalizedPageId}`;
}

export function isBrowserTab(tab: BrowserTab) {
  return Boolean(tab.browser) || tab.id.startsWith("browser:") || tab.title === "Browser";
}

export function browserTabsRepresentSamePage(left: BrowserTab, right: BrowserTab) {
  if (left.id === right.id) return true;
  const leftPageIds = browserTabPageIds(left);
  const rightPageIds = browserTabPageIds(right);
  if (leftPageIds.size && rightPageIds.size) {
    for (const pageId of leftPageIds) {
      if (rightPageIds.has(pageId)) return true;
    }
  }
  const leftUrl = browserTabComparableUrl(left);
  const rightUrl = browserTabComparableUrl(right);
  return Boolean(leftUrl && rightUrl && leftUrl === rightUrl);
}

export function browserTabPageIds(tab: BrowserTab) {
  const ids = new Set<string>();
  const browser = tab.browser;
  const viewRecord = recordValue(browser?.view);
  [
    browser?.pageId,
    browser?.view?.active_tab_id,
    viewRecord.page_id,
    viewRecord.window_id,
    viewRecord.tab_id,
  ].forEach((value) => {
    if (typeof value === "string" && value.trim()) ids.add(value.trim());
  });
  return ids;
}

export function browserTabComparableUrl(tab: BrowserTab) {
  const url = tab.browser?.currentUrl || tab.browser?.view?.url || tab.subtitle || "";
  return isMeaningfulBrowserUrl(url) ? normalizeComparableUrl(url) : "";
}

export function browserPreferredSyncedView(
  existingView: SessionBrowserView | undefined,
  syncedView: SessionBrowserView | undefined,
) {
  if (!syncedView) return existingView;
  if (!existingView) return syncedView;
  const existingUrl = browserViewComparableUrl(existingView);
  const syncedUrl = browserViewComparableUrl(syncedView);
  if (
    existingUrl &&
    syncedUrl &&
    existingUrl === syncedUrl &&
    browserViewIsPlaceholder(syncedView) &&
    !browserViewIsPlaceholder(existingView)
  ) {
    return existingView;
  }
  return syncedView;
}

export function browserViewComparableUrl(view: SessionBrowserView | undefined) {
  return view?.url && isMeaningfulBrowserUrl(view.url) ? normalizeComparableUrl(view.url) : "";
}

export function browserViewIsPlaceholder(view: SessionBrowserView | undefined) {
  if (!view) return true;
  return (
    !view.can_capture &&
    !String(view.image_data || "").trim() &&
    !String(view.preview_image_url || "").trim() &&
    !String(view.html || "").trim() &&
    !String(view.document_html || "").trim() &&
    !String(view.document_url || "").trim()
  );
}

export function browserCooperationFromView(view?: SessionBrowserView) {
  return view?.cooperation ?? view?.workspace_state?.cooperation ?? view?.browser_snapshot?.cooperation;
}

export function browserRenderCacheKey(
  browserId: string,
  url: string,
  viewport: Pick<SessionBrowserViewport, "width" | "height">,
  pageId = "",
) {
  const normalizedUrl = normalizeComparableUrl(url || "about:blank");
  return [browserId || "browser", pageId || normalizedUrl, normalizedUrl, Math.round(viewport.width), Math.round(viewport.height)].join(
    "::",
  );
}

export function browserRenderUrlCacheKey(browserId: string, url: string) {
  return [browserId || "browser", "url", normalizeComparableUrl(url || "about:blank")].join("::");
}

export function browserRenderCacheKeyFromView(browserId: string, view: SessionBrowserView) {
  const viewRecord = recordValue(view);
  return (
    browserStringValue(view.render_cache_key) ||
    browserRenderCacheKey(
      browserId || view.browser_id,
      view.url || "about:blank",
      {
        width: view.viewport_width || 1024,
        height: view.viewport_height || 720,
      },
      browserStringValue(view.active_tab_id) || browserStringValue(viewRecord.page_id) || "",
    )
  );
}

export function rememberBrowserRenderView(browserId: string, view: SessionBrowserView) {
  if (!view.url || view.url === "about:blank") return;
  const resolvedBrowserId = browserId || view.browser_id;
  const key = browserRenderCacheKeyFromView(resolvedBrowserId, view);
  const fallbackKey = browserRenderCacheKey(browserId || view.browser_id, view.url, {
    width: view.viewport_width || 1024,
    height: view.viewport_height || 720,
  });
  const cachedView = compactBrowserViewForMemory({
    ...view,
    render_cache_key: view.render_cache_key || key,
    render_cache_status: "stored",
  });
  for (const cacheKey of Array.from(new Set([key, fallbackKey]))) {
    browserRenderCache.delete(cacheKey);
    browserRenderCache.set(cacheKey, cachedView);
  }
  browserRenderCacheByUrl.set(browserRenderUrlCacheKey(resolvedBrowserId, view.url), key);
  while (browserRenderCache.size > BROWSER_RENDER_CACHE_LIMIT) {
    const oldest = browserRenderCache.keys().next().value;
    if (!oldest) break;
    browserRenderCache.delete(oldest);
    for (const [urlKey, cacheKey] of browserRenderCacheByUrl.entries()) {
      if (cacheKey === oldest) browserRenderCacheByUrl.delete(urlKey);
    }
  }
}

export function compactBrowserViewForMemory(view: SessionBrowserView): SessionBrowserView {
  const snapshot = view.browser_snapshot
    ? {
        ...view.browser_snapshot,
        html: "",
        document_html: "",
        image_data: "",
      }
    : view.browser_snapshot;
  return {
    ...view,
    html: "",
    document_html: "",
    image_data: "",
    browser_snapshot: snapshot,
  };
}

export function resolveBackendUrlPath(baseUrl: string, value?: string) {
  const raw = browserStringValue(value);
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw) || raw.startsWith("data:") || raw.startsWith("blob:")) return raw;
  const root = baseUrl.replace(/\/+$/, "");
  return raw.startsWith("/") ? `${root}${raw}` : `${root}/${raw}`;
}

export function readBrowserRenderCache(
  browserId: string,
  url: string,
  viewport: Pick<SessionBrowserViewport, "width" | "height">,
  pageId = "",
) {
  if (!url || url === "about:blank") return undefined;
  const key = browserRenderCacheKey(browserId, url, viewport, pageId);
  const urlKey = browserRenderUrlCacheKey(browserId, url);
  const urlAlias = browserRenderCacheByUrl.get(urlKey);
  const normalizedUrl = normalizeComparableUrl(url);
  const scannedKey =
    urlAlias ??
    Array.from(browserRenderCache.entries()).find(
      ([, value]) => value.browser_id === browserId && normalizeComparableUrl(value.url || "") === normalizedUrl,
    )?.[0];
  for (const candidateKey of Array.from(new Set([key, urlAlias, scannedKey])).filter(
    (candidateKey): candidateKey is string => Boolean(candidateKey),
  )) {
    const cached = browserRenderCache.get(candidateKey);
    if (!cached) continue;
    browserRenderCache.delete(candidateKey);
    browserRenderCache.set(candidateKey, cached);
    browserRenderCacheByUrl.set(urlKey, candidateKey);
    return { ...cached, render_cache_key: cached.render_cache_key || candidateKey, render_cache_status: "hit" };
  }
  return undefined;
}

export function isBrowserCooperationEvent(value: unknown): value is SessionBrowserCooperationEvent {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      typeof (value as { kind?: unknown }).kind === "string",
  );
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

export function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
}

export function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    : [];
}
