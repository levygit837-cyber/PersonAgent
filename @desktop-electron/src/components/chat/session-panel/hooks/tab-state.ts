import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { getSessionProjectDetail } from "../../../../api/client";
import type { SessionBrowserView } from "../../../../api/client";
import type { ProjectItem } from "../../../../types/chat";
import type { SessionDetailView } from "../../session-detail-window";
import { browserHasMeaningfulPage } from "../helpers/browser-view-helpers";
import {
  type BrowserState,
  type BrowserTab,
  createEmptyBrowserState,
  isBrowserTab,
  isMeaningfulBrowserUrl,
  rememberBrowserRenderView,
  summaryTab,
} from "../helpers/helpers";

export interface TabStateDeps {
  tabs: BrowserTab[];
  setTabs: Dispatch<SetStateAction<BrowserTab[]>>;
  activeTabId: string;
  setActiveTabId: Dispatch<SetStateAction<string>>;
  loadingDetailId: string | null;
  setLoadingDetailId: Dispatch<SetStateAction<string | null>>;
  browserRequestIdsRef: MutableRefObject<Record<string, number>>;
  conversationId: string | undefined;
  baseUrl: string;
  workspaceRoot: string | undefined;
}

export interface TabStateApi {
  closeTab: (tabId: string) => void;
  openBrowserPlaceholder: () => void;
  openDetailTab: (detail: SessionDetailView) => void;
  openProjectDetail: (item: ProjectItem) => Promise<void>;
  updateBrowserTab: (tabId: string, updater: (browser: BrowserState) => BrowserState) => void;
  browserForTab: (tabId: string) => BrowserState | undefined;
  startBrowserRequest: (tabId: string, options?: { showLoading?: boolean }) => number;
  applyBrowserView: (
    tabId: string,
    view: SessionBrowserView,
    options?: { addHistory?: boolean; historyIndex?: number },
    requestId?: number,
  ) => void;
  setBrowserError: (tabId: string, error: unknown, requestId?: number) => void;
}

export function createTabState(deps: TabStateDeps): TabStateApi {
  const {
    tabs,
    setTabs,
    activeTabId,
    setActiveTabId,
    setLoadingDetailId,
    browserRequestIdsRef,
    conversationId,
    baseUrl,
    workspaceRoot,
  } = deps;

  const openDetailTab = (detail: SessionDetailView) => {
    const tab: BrowserTab = {
      id: `${detail.type}:${detail.id}`,
      title: detail.title,
      subtitle: detail.subtitle,
      closeable: true,
      detail,
    };
    setTabs((current) => {
      if (current.some((item) => item.id === tab.id)) {
        return current.map((item) => (item.id === tab.id ? tab : item));
      }
      return [...current, tab];
    });
    setActiveTabId(tab.id);
  };

  const openProjectDetail = async (item: ProjectItem) => {
    if (!conversationId) return;
    const loadingKey = `${item.type}:${item.id}`;
    setLoadingDetailId(loadingKey);
    try {
      const detail = await getSessionProjectDetail(baseUrl, conversationId, {
        type: item.type,
        id: item.id,
        workspaceRoot,
      });
      openDetailTab({
        ...detail,
        title: detail.title || item.title,
        subtitle: item.subtitle,
      });
    } catch (error) {
      openDetailTab({
        type: item.type,
        id: item.id,
        title: item.title,
        subtitle: item.subtitle,
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLoadingDetailId(null);
    }
  };

  const closeTab = (tabId: string) => {
    setTabs((current) => current.filter((tab) => tab.id === summaryTab.id || tab.id !== tabId));
    if (activeTabId === tabId) setActiveTabId(summaryTab.id);
  };

  const openBrowserPlaceholder = () => {
    const id = conversationId ? `browser:${conversationId}` : `browser:${Date.now()}`;
    const browserId = conversationId || id;
    const existing = tabs.find((tab) => tab.browser?.browserId === browserId);
    if (existing) {
      setActiveTabId(existing.id);
      return;
    }
    setTabs((current) => [
      ...current,
      {
        id,
        title: "Browser",
        closeable: true,
        browser: createEmptyBrowserState(browserId),
      },
    ]);
    setActiveTabId(id);
  };

  const updateBrowserTab = (tabId: string, updater: (browser: BrowserState) => BrowserState) => {
    setTabs((current) =>
      current.map((tab) => {
        if (tab.id !== tabId || !isBrowserTab(tab)) return tab;
        return { ...tab, browser: updater(tab.browser ?? createEmptyBrowserState(tab.id)) };
      }),
    );
  };

  const browserForTab = (tabId: string) => tabs.find((tab) => tab.id === tabId)?.browser;

  const startBrowserRequest = (tabId: string, options: { showLoading?: boolean } = {}) => {
    const requestId = (browserRequestIdsRef.current[tabId] ?? 0) + 1;
    browserRequestIdsRef.current[tabId] = requestId;
    updateBrowserTab(tabId, (browser) => ({
      ...browser,
      requestId,
      loading: options.showLoading === false ? browser.loading : true,
      error: undefined,
    }));
    return requestId;
  };

  const applyBrowserView = (
    tabId: string,
    view: SessionBrowserView,
    options: { addHistory?: boolean; historyIndex?: number } = {},
    requestId?: number,
  ) => {
    rememberBrowserRenderView(browserForTab(tabId)?.browserId || view.browser_id || tabId, view);
    updateBrowserTab(tabId, (browser) => {
      if (requestId !== undefined && browserRequestIdsRef.current[tabId] !== requestId) return browser;
      if (!isMeaningfulBrowserUrl(view.url) && browserHasMeaningfulPage(browser)) {
        return {
          ...browser,
          requestId: requestId ?? browser.requestId,
          loading: false,
        };
      }
      const nextUrl = isMeaningfulBrowserUrl(view.url) ? view.url : browser.currentUrl;
      let history = browser.history;
      let historyIndex = browser.historyIndex;
      if (nextUrl && options.addHistory) {
        const baseHistory = browser.history.slice(0, browser.historyIndex + 1);
        history = baseHistory.at(-1) === nextUrl ? baseHistory : [...baseHistory, nextUrl];
        historyIndex = history.length - 1;
      } else if (nextUrl && options.historyIndex !== undefined) {
        historyIndex = Math.min(Math.max(options.historyIndex, 0), Math.max(browser.history.length - 1, 0));
      } else if (nextUrl && history.length === 0) {
        history = [nextUrl];
        historyIndex = 0;
      }
      return {
        ...browser,
        requestId: requestId ?? browser.requestId,
        currentUrl: nextUrl,
        draftUrl: nextUrl || browser.draftUrl,
        history,
        historyIndex,
        loading: false,
        error:
          view.can_capture || view.render_mode === "html_mirror" || view.render_mode === "computed_html" || view.render_mode === "pixel"
            ? undefined
            : view.screenshot_error || "Browser rendering is unavailable.",
        view,
      };
    });
  };

  const setBrowserError = (tabId: string, error: unknown, requestId?: number) => {
    updateBrowserTab(tabId, (browser) => {
      if (requestId !== undefined && browserRequestIdsRef.current[tabId] !== requestId) return browser;
      return {
        ...browser,
        requestId: requestId ?? browser.requestId,
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      };
    });
  };

  return {
    closeTab,
    openBrowserPlaceholder,
    openDetailTab,
    openProjectDetail,
    updateBrowserTab,
    browserForTab,
    startBrowserRequest,
    applyBrowserView,
    setBrowserError,
  };
}
