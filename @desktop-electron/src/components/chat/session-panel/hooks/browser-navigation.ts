import {
  clickSessionBrowser,
  getSessionBrowserView,
  keySessionBrowser,
  moveSessionBrowserHistory,
  navigateSessionBrowser,
  reloadSessionBrowser,
  scrollSessionBrowser,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../../../api/client";
import { normalizeBrowserUrl } from "../helpers/browser-helpers";
import { type BrowserState, readBrowserRenderCache } from "../helpers/helpers";

export interface NavigationDeps {
  browserForTab: (tabId: string) => BrowserState | undefined;
  startBrowserRequest: (tabId: string, options?: { showLoading?: boolean }) => number;
  applyBrowserView: (
    tabId: string,
    view: SessionBrowserView,
    options?: { addHistory?: boolean; historyIndex?: number },
    requestId?: number,
  ) => void;
  setBrowserError: (tabId: string, error: unknown, requestId?: number) => void;
  baseUrl: string;
  conversationId: string | undefined;
}

export interface NavigationApi {
  loadBrowserView: (tabId: string, viewport: SessionBrowserViewport) => Promise<void>;
  navigateBrowser: (tabId: string, rawUrl: string, viewport: SessionBrowserViewport) => Promise<void>;
  moveBrowserHistory: (tabId: string, direction: -1 | 1, viewport: SessionBrowserViewport) => Promise<void>;
  refreshBrowser: (tabId: string, viewport: SessionBrowserViewport) => Promise<void>;
  clickBrowser: (
    tabId: string,
    input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" },
  ) => Promise<void>;
  keyBrowser: (tabId: string, input: SessionBrowserViewport & { text?: string; key?: string }) => Promise<void>;
  scrollBrowser: (tabId: string, input: SessionBrowserViewport & { delta_x: number; delta_y: number }) => Promise<void>;
}

export function createBrowserNavigation(deps: NavigationDeps): NavigationApi {
  const { browserForTab, startBrowserRequest, applyBrowserView, setBrowserError, baseUrl, conversationId } = deps;

  const loadBrowserView = async (tabId: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const cached = browser.currentUrl
      ? readBrowserRenderCache(browser.browserId, browser.currentUrl, viewport, browser.view?.active_tab_id)
      : undefined;
    const requestId = startBrowserRequest(tabId, { showLoading: !cached });
    if (cached) applyBrowserView(tabId, cached, { historyIndex: browser.historyIndex }, requestId);
    try {
      const view = await getSessionBrowserView(
        baseUrl,
        browser.browserId,
        {
          ...viewport,
          cache_mode: cached ? "prefer_cached" : "prefer_live",
          wait_for_styles: !cached,
        },
        conversationId,
      );
      applyBrowserView(tabId, view, {}, requestId);
    } catch (error) {
      if (!cached) setBrowserError(tabId, error, requestId);
    }
  };

  const navigateBrowser = async (tabId: string, rawUrl: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    const normalized = normalizeBrowserUrl(rawUrl);
    if (!browser || !normalized || !baseUrl) return;
    const cached = readBrowserRenderCache(browser.browserId, normalized, viewport);
    const requestId = startBrowserRequest(tabId, { showLoading: !cached });
    if (cached) applyBrowserView(tabId, cached, { addHistory: true }, requestId);
    try {
      const view = await navigateSessionBrowser(
        baseUrl,
        browser.browserId,
        {
          url: normalized,
          ...viewport,
          cache_mode: cached ? "prefer_cached" : "prefer_live",
          wait_for_styles: false,
        },
        conversationId,
      );
      applyBrowserView(tabId, view, { addHistory: true }, requestId);
    } catch (error) {
      if (!cached) setBrowserError(tabId, error, requestId);
    }
  };

  const moveBrowserHistory = async (tabId: string, direction: -1 | 1, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const historyIndex = browser.historyIndex + direction;
    const targetUrl = browser.history[historyIndex];
    if (!targetUrl) return;
    const cached = readBrowserRenderCache(browser.browserId, targetUrl, viewport, browser.view?.active_tab_id);
    const requestId = startBrowserRequest(tabId, { showLoading: !cached });
    if (cached) applyBrowserView(tabId, cached, { historyIndex }, requestId);
    try {
      const view = await moveSessionBrowserHistory(
        baseUrl,
        browser.browserId,
        {
          direction,
          ...viewport,
          cache_mode: cached ? "prefer_cached" : "prefer_live",
          wait_for_styles: false,
        },
        conversationId,
      );
      applyBrowserView(tabId, view, { historyIndex }, requestId);
    } catch (error) {
      if (!cached) setBrowserError(tabId, error, requestId);
    }
  };

  const refreshBrowser = async (tabId: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !browser.currentUrl) return;
    const cached = readBrowserRenderCache(browser.browserId, browser.currentUrl, viewport, browser.view?.active_tab_id);
    const requestId = startBrowserRequest(tabId, { showLoading: !cached });
    if (cached) applyBrowserView(tabId, cached, { historyIndex: browser.historyIndex }, requestId);
    try {
      const view = await reloadSessionBrowser(
        baseUrl,
        browser.browserId,
        {
          ...viewport,
          cache_mode: cached ? "prefer_cached" : "prefer_live",
          wait_for_styles: false,
        },
        conversationId,
      );
      applyBrowserView(tabId, view, { historyIndex: browser.historyIndex }, requestId);
    } catch (error) {
      if (!cached) setBrowserError(tabId, error, requestId);
    }
  };

  const clickBrowser = async (
    tabId: string,
    input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" },
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await clickSessionBrowser(baseUrl, browser.browserId, input, conversationId);
      applyBrowserView(tabId, view, { addHistory: true }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const keyBrowser = async (tabId: string, input: SessionBrowserViewport & { text?: string; key?: string }) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await keySessionBrowser(baseUrl, browser.browserId, input, conversationId);
      applyBrowserView(tabId, view, { addHistory: true }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const scrollBrowser = async (
    tabId: string,
    input: SessionBrowserViewport & { delta_x: number; delta_y: number },
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    try {
      const view = await scrollSessionBrowser(baseUrl, browser.browserId, input, conversationId);
      applyBrowserView(tabId, view);
    } catch (error) {
      setBrowserError(tabId, error);
    }
  };

  return {
    loadBrowserView,
    navigateBrowser,
    moveBrowserHistory,
    refreshBrowser,
    clickBrowser,
    keyBrowser,
    scrollBrowser,
  };
}
