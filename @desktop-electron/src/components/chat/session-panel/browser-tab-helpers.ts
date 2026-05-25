import type {
  SessionBrowserView,
} from "../../../api/client";
import type { ToolBlockUi } from "../../../types/chat";
import {
  type BrowserTab,
  browserPagePanelTabId,
  browserStringValue,
  browserViewIsPlaceholder,
  createEmptyBrowserState,
  recordArray,
  recordValue,
} from "./helpers";
import { browserViewFromToolEvent } from "./browser-view-helpers";

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
