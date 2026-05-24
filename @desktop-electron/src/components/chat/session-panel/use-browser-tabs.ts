import { useEffect, useMemo, useRef, useState } from "react";
import {
  actSessionBrowser,
  clickSessionBrowser,
  connectSessionBrowserCooperation,
  createSessionBrowserAnnotation,
  getSessionBrowserView,
  getSessionProjectDetail,
  ingestSessionBrowserEvents,
  keySessionBrowser,
  moveSessionBrowserHistory,
  navigateSessionBrowser,
  reloadSessionBrowser,
  scrollSessionBrowser,
  setSessionBrowserCooperation,
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserCooperationWsEvent,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../../api/client";
import type { ComposerAnnotation } from "../../../stores/chat-store";
import type { ProjectItem, ToolBlockUi } from "../../../types/chat";
import type { SessionDetailView } from "../session-detail-window";
import {
  browserAnnotationToComposerAnnotation,
  browserHasMeaningfulPage,
  browserMeaningfulToolUrl,
  browserSnapshotViewFromToolEvent,
  browserTabsFromBlocks,
  browserTextSelectionToComposerAnnotation,
  browserToolEventAppliesToBrowser,
  browserToolEventIsAction,
  browserToolEventIsPassive,
  browserToolEventUrl,
  browserToolShouldFetchRenderedView,
  browserToolShouldHydrateView,
  browserToolShouldPreserveCurrentView,
  browserToolShouldSyncDisplayedPage,
  browserToolUrlChanged,
  browserViewFromToolEvent,
  browserVisualEventsFromBlocks,
  localBrowserAnnotation,
  normalizeBrowserUrl,
  numericValue,
} from "./browser-helpers";
import {
  type BrowserElementMetadata,
  type BrowserState,
  type BrowserTab,
  type BrowserTextSelectionMetadata,
  type BrowserToolEvent,
  type BrowserVisualEvent,
  browserCooperationFromView,
  browserPanelTabId,
  browserPreferredSyncedView,
  browserStringValue,
  browserTabsRepresentSamePage,
  createEmptyBrowserState,
  isBrowserTab,
  isMeaningfulBrowserUrl,
  normalizeComparableUrl,
  readBrowserRenderCache,
  recordValue,
  rememberBrowserRenderView,
  summaryTab,
  BROWSER_TOOL_VIEW_SETTLE_MS,
} from "./helpers";

export function useBrowserTabs(args: {
  browserToolBlocks: ToolBlockUi[];
  isStreaming: boolean;
  conversationId: string | undefined;
  baseUrl: string;
  workspaceRoot: string | undefined;
  visible: boolean;
  addComposerAnnotation: (annotation: ComposerAnnotation) => void;
  approvePendingTool: () => Promise<void>;
  rejectPendingTool: () => Promise<void>;
}) {
  const {
    browserToolBlocks,
    conversationId,
    baseUrl,
    workspaceRoot,
    visible,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
  } = args;

  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([summaryTab]);
  const [activeTabId, setActiveTabId] = useState(summaryTab.id);
  const browserRequestIdsRef = useRef<Record<string, number>>({});
  const browserWorkspacePersistKeysRef = useRef<Record<string, string>>({});
  const cooperationSocketsRef = useRef<Record<string, WebSocket>>({});
  const tabsRef = useRef<BrowserTab[]>(tabs);
  const browserToolTabOpenRef = useRef("");
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? summaryTab;
  const browserVisualEvents = useMemo(() => browserVisualEventsFromBlocks(browserToolBlocks), [browserToolBlocks]);
  const browserToolEvent = browserVisualEvents[0];
  const browserToolTabs = useMemo(() => browserTabsFromBlocks(browserToolBlocks, conversationId), [browserToolBlocks, conversationId]);
  const appliedBrowserToolViewRef = useRef("");

  useEffect(() => {
    tabsRef.current = tabs;
  }, [tabs]);

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

  const openBrowserForToolEvent = (visual: BrowserToolEvent) => {
    const browserId =
      visual.browserId ||
      browserStringValue(visual.data.browser_id) ||
      browserStringValue(visual.data.active_browser_id) ||
      conversationId ||
      `browser:${Date.now()}`;
    const tabId = browserPanelTabId(browserId);
    const url = browserMeaningfulToolUrl(visual);
    const view = browserViewFromToolEvent(visual);
    const snapshotView = view ?? browserSnapshotViewFromToolEvent(visual);
    const browserTabs = tabsRef.current.filter(isBrowserTab);
    const existing = browserTabs.find((tab) => {
      if (!isBrowserTab(tab)) return false;
      return tab.id === tabId || tab.browser?.browserId === browserId || browserToolEventAppliesToBrowser(visual, tab.browser ?? createEmptyBrowserState(tab.id));
    });
    const fallback =
      existing ??
      (browserToolEventIsPassive(visual)
        ? browserTabs.find((tab) => tab.id === activeTabId && browserHasMeaningfulPage(tab.browser)) ??
          browserTabs.find((tab) => browserHasMeaningfulPage(tab.browser)) ??
          browserTabs.find((tab) => tab.id === activeTabId)
        : undefined);
    if (fallback) {
      const existingBrowser = fallback.browser ?? createEmptyBrowserState(fallback.id);
      if (!browserToolEventIsPassive(visual) || url || snapshotView || browserHasMeaningfulPage(existingBrowser)) {
        setActiveTabId(fallback.id);
      }
      const shouldSyncPage = browserToolShouldSyncDisplayedPage(visual, existingBrowser);
      if (shouldSyncPage && (url || view)) {
        updateBrowserTab(fallback.id, (browser) => ({
          ...browser,
          currentUrl: url || view?.url || browser.currentUrl,
          draftUrl: url || view?.url || browser.draftUrl,
          loading: browserToolShouldFetchRenderedView(visual, browser) && !view,
          error: undefined,
          view: view ?? (browserToolShouldPreserveCurrentView(visual) ? browser.view : browserToolUrlChanged(visual, browser) ? undefined : browser.view),
        }));
      } else if (!existingBrowser.view && snapshotView) {
        updateBrowserTab(fallback.id, (browser) => ({
          ...browser,
          currentUrl: url || snapshotView.url || browser.currentUrl,
          draftUrl: url || snapshotView.url || browser.draftUrl,
          view: snapshotView,
        }));
      }
      return;
    }
    const shouldFetchView = browserToolShouldFetchRenderedView(visual);
    if (browserToolEventIsPassive(visual) && !snapshotView) return;
    if (!view && !snapshotView && !shouldFetchView && !browserToolEventIsAction(visual)) return;
    const browser = {
      ...createEmptyBrowserState(browserId),
      currentUrl: url || snapshotView?.url || "",
      draftUrl: url || snapshotView?.url || "",
      loading: shouldFetchView && !view,
      view: browserToolShouldSyncDisplayedPage(visual) ? view : snapshotView,
    };
    setTabs((current) => [
      ...current,
      {
        id: tabId,
        title: "Browser",
        closeable: true,
        browser,
      },
    ]);
    setActiveTabId(tabId);
  };

  useEffect(() => {
    if (!browserToolEvent || !browserToolShouldHydrateView(browserToolEvent)) return;
    const key = `${browserToolEvent.id}:${browserToolEvent.status}:${browserToolEvent.browserId || ""}:${browserToolEvent.pageId || ""}:${browserToolEventUrl(browserToolEvent)}`;
    if (browserToolTabOpenRef.current === key) return;
    browserToolTabOpenRef.current = key;
    openBrowserForToolEvent(browserToolEvent);
  }, [browserToolEvent, conversationId]);

  useEffect(() => {
    if (!browserToolTabs.length) return;
    let nextActiveTabId = "";
    setTabs((current) => {
      const currentMatches = new Map<string, BrowserTab>();
      let next = current.map((tab) => {
        const synced = browserToolTabs.find((browserTab) => browserTabsRepresentSamePage(tab, browserTab));
        if (!synced) return tab;
        currentMatches.set(synced.id, tab);
        const browser = tab.browser ?? createEmptyBrowserState(synced.browser?.browserId || tab.id);
        const syncedView = synced.browser?.view;
        return {
          ...tab,
          title: synced.title || tab.title,
          subtitle: synced.subtitle ?? tab.subtitle,
          browser: {
            ...browser,
            ...synced.browser,
            mode: browser.mode,
            elementMetadata: browser.elementMetadata,
            annotationDraft: browser.annotationDraft,
            requestId: browser.requestId,
            loading: browser.loading && !synced.browser?.view ? browser.loading : Boolean(synced.browser?.loading),
            error: synced.browser?.error,
            view: browserPreferredSyncedView(browser.view, syncedView),
          },
        };
      });
      const additions = browserToolTabs.filter((browserTab) => {
        if (currentMatches.has(browserTab.id)) return false;
        return !next.some((tab) => browserTabsRepresentSamePage(tab, browserTab));
      });
      if (additions.length) next = [...next, ...additions];
      const activeSynced = browserToolTabs.find((tab) => tab.browser?.view?.active_tab_id && tab.browser.view.active_tab_id === tab.browser.pageId);
      const preferredActive = activeSynced ?? browserToolTabs[0];
      nextActiveTabId = next.find((tab) => preferredActive && browserTabsRepresentSamePage(tab, preferredActive))?.id || preferredActive?.id || "";
      return next;
    });
    if (nextActiveTabId) setActiveTabId(nextActiveTabId);
  }, [browserToolTabs]);

  useEffect(() => {
    if (!browserToolEvent || browserToolEvent.status !== "completed") return;
    const browserTabs = tabsRef.current.filter(isBrowserTab);
    const matchingTab = browserTabs.find((tab) => {
      if (!isBrowserTab(tab)) return false;
      return browserToolEventAppliesToBrowser(browserToolEvent, tab.browser ?? createEmptyBrowserState(tab.id));
    }) ?? browserTabs.find((tab) => tab.id === activeTabId) ?? (browserTabs.length === 1 ? browserTabs[0] : undefined);
    if (!matchingTab) return;
    const view = browserViewFromToolEvent(browserToolEvent);
    const shouldSyncPage = browserToolShouldSyncDisplayedPage(browserToolEvent, matchingTab.browser);
    const shouldFetchView = browserToolShouldFetchRenderedView(browserToolEvent, matchingTab.browser);
    if (!shouldSyncPage && !shouldFetchView) return;
    const applyKey = [
      browserToolEvent.id,
      browserMeaningfulToolUrl(browserToolEvent) || "",
      browserStringValue(browserToolEvent.data.title) || "",
      browserStringValue(browserToolEvent.data.active_tab_id) || browserToolEvent.pageId || "",
      browserToolEvent.data.image_data ? String(browserToolEvent.data.image_data).length : "",
    ].join(":");
    if (appliedBrowserToolViewRef.current === applyKey) return;
    appliedBrowserToolViewRef.current = applyKey;
    const hydratedBrowserId =
      browserStringValue(browserToolEvent.data.browser_id) ||
      browserStringValue(browserToolEvent.data.active_browser_id) ||
      browserToolEvent.browserId ||
      matchingTab.browser?.browserId ||
      matchingTab.id;
    const hydratedUrl = browserMeaningfulToolUrl(browserToolEvent) || view?.url || "";
    const viewportWidth = numericValue(browserToolEvent.data.viewport_width) || view?.viewport_width || matchingTab.browser?.view?.viewport_width || 1024;
    const viewportHeight = numericValue(browserToolEvent.data.viewport_height) || view?.viewport_height || matchingTab.browser?.view?.viewport_height || 720;
    const timer = window.setTimeout(() => {
      if (view && shouldSyncPage) {
        applyBrowserView(
          matchingTab.id,
          { ...view, render_cache_status: view.render_cache_status || "hit" },
          { addHistory: browserToolEvent.effect !== "map" },
        );
      }
      if (!shouldFetchView || !baseUrl || !hydratedBrowserId || !hydratedUrl || hydratedUrl === "about:blank") return;
      void getSessionBrowserView(
        baseUrl,
        hydratedBrowserId,
        {
          width: viewportWidth,
          height: viewportHeight,
          cache_mode: browserToolEvent.toolName === "BrowserOpen" ? "prefer_live" : "prefer_cached",
          wait_for_styles: browserToolEvent.toolName === "BrowserOpen",
        },
        conversationId,
      )
        .then((nextView) => {
          if (hydratedUrl && normalizeComparableUrl(nextView.url || "") !== normalizeComparableUrl(hydratedUrl)) return;
          applyBrowserView(matchingTab.id, { ...nextView, render_cache_status: "hit" }, { addHistory: false });
        })
        .catch(() => undefined)
        .finally(() => {
          updateBrowserTab(matchingTab.id, (browser) => (browser.loading ? { ...browser, loading: false } : browser));
        });
    }, BROWSER_TOOL_VIEW_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [activeTabId, baseUrl, browserToolEvent, conversationId, tabs.length]);

  useEffect(() => {
    if (!baseUrl || !conversationId) return;
    tabs.forEach((tab) => {
      if (!isBrowserTab(tab) || !tab.browser?.view || !tab.browser.currentUrl) return;
      const browser = tab.browser;
      const view = browser.view;
      if (!view) return;
      const persistKey = [
        conversationId,
        browser.browserId,
        browser.currentUrl,
        view.active_tab_id || "",
        view.title || "",
        view.viewport_width || 1024,
        view.viewport_height || 720,
      ].join(":");
      if (browserWorkspacePersistKeysRef.current[tab.id] === persistKey) return;
      if (view.render_cache_status === "hit" || view.render_cache_status === "stored") return;
      browserWorkspacePersistKeysRef.current[tab.id] = persistKey;
      void getSessionBrowserView(
        baseUrl,
        browser.browserId,
        {
          width: view.viewport_width || 1024,
          height: view.viewport_height || 720,
        },
        conversationId,
      )
        .then((nextView) => applyBrowserView(tab.id, nextView))
        .catch(() => {
          delete browserWorkspacePersistKeysRef.current[tab.id];
        });
    });
  }, [baseUrl, conversationId, tabs]);

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

  const setBrowserMode = (tabId: string, mode: BrowserState["mode"]) => {
    updateBrowserTab(tabId, (browser) => ({
      ...browser,
      mode,
      selectedNodeId: mode === "browse" ? undefined : browser.selectedNodeId,
      annotationDraft: mode === "annotate" ? browser.annotationDraft : "",
    }));
  };

  const selectBrowserElement = (tabId: string, nodeId: string, element?: BrowserElementMetadata) => {
    updateBrowserTab(tabId, (browser) => ({
      ...browser,
      selectedNodeId: nodeId || undefined,
      elementMetadata: element?.node_id
        ? { ...browser.elementMetadata, [element.node_id]: element }
        : browser.elementMetadata,
      error: undefined,
    }));
  };

  const updateAnnotationDraft = (tabId: string, value: string) => {
    updateBrowserTab(tabId, (browser) => ({ ...browser, annotationDraft: value }));
  };

  const addBrowserTextSelection = (tabId: string, selection: BrowserTextSelectionMetadata) => {
    const browser = browserForTab(tabId);
    if (!browser || !selection.text.trim()) return;
    addComposerAnnotation(
      browserTextSelectionToComposerAnnotation({
        selection,
        fallbackUrl: browser.currentUrl,
        fallbackTitle: browser.view?.title,
      }),
    );
  };

  const saveBrowserAnnotation = async (tabId: string) => {
    const browser = browserForTab(tabId);
    if (!browser?.selectedNodeId || !browser.annotationDraft.trim()) return;
    const element =
      browser.view?.element_map?.find((item) => item.node_id === browser.selectedNodeId) ??
      browser.elementMetadata[browser.selectedNodeId];
    if (!baseUrl || !conversationId) {
      const annotation = localBrowserAnnotation({
        browserId: browser.browserId,
        nodeId: browser.selectedNodeId,
        body: browser.annotationDraft.trim(),
        quote: element?.text,
        url: browser.currentUrl,
        title: browser.view?.title,
      });
      updateBrowserTab(tabId, (current) => ({
        ...current,
        annotationDraft: "",
        selectedNodeId: undefined,
        view: current.view
          ? { ...current.view, annotations: [...(current.view.annotations ?? []), annotation] }
          : current.view,
      }));
      addComposerAnnotation(
        browserAnnotationToComposerAnnotation({
          annotation,
          element,
          fallbackUrl: browser.currentUrl,
          fallbackTitle: browser.view?.title,
        }),
      );
      return;
    }
    try {
      const result = await createSessionBrowserAnnotation(baseUrl, conversationId, browser.browserId, {
        node_id: browser.selectedNodeId,
        body: browser.annotationDraft.trim(),
        quote: element?.text,
        url: browser.currentUrl,
        title: browser.view?.title,
        selector: element?.selector,
        frame_id: element?.frame_id,
        selector_chain: element?.selector_chain,
        shadow_path: element?.shadow_path,
        tab_id: element?.tab_id ?? browser.view?.active_tab_id,
      });
      updateBrowserTab(tabId, (current) => ({
        ...current,
        annotationDraft: "",
        selectedNodeId: undefined,
        view: current.view
          ? { ...current.view, annotations: result.annotations, timeline_events: result.timeline_events }
          : current.view,
      }));
      addComposerAnnotation(
        browserAnnotationToComposerAnnotation({
          annotation: result.annotation,
          element,
          fallbackUrl: browser.currentUrl,
          fallbackTitle: browser.view?.title,
        }),
      );
    } catch (error) {
      setBrowserError(tabId, error);
    }
  };

  const activateBrowserElement = async (
    tabId: string,
    nodeId: string,
    viewport: SessionBrowserViewport,
    action: "click" | "submit" = "click",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await actSessionBrowser(
        baseUrl,
        browser.browserId,
        { ...viewport, node_id: nodeId, action, source: "user" },
        conversationId,
      );
      applyBrowserView(tabId, view, { addHistory: true }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const applyBrowserCooperationPatch = (
    tabId: string,
    cooperation: SessionBrowserView["cooperation"],
  ) => {
    if (!cooperation) return;
    updateBrowserTab(tabId, (current) => {
      const view = current.view;
      if (!view) return current;
      const currentCooperation = browserCooperationFromView(view);
      const nextCooperation = { ...currentCooperation, ...cooperation };
      return {
        ...current,
        view: {
          ...view,
          cooperation: nextCooperation,
          workspace_state: view.workspace_state
            ? { ...view.workspace_state, cooperation: nextCooperation }
            : { cooperation: nextCooperation },
          browser_snapshot: view.browser_snapshot
            ? { ...view.browser_snapshot, cooperation: nextCooperation }
            : view.browser_snapshot,
        },
      };
    });
  };

  const applyBrowserCooperationWsEvent = (tabId: string, event: SessionBrowserCooperationWsEvent) => {
    if (event.type === "error") return;
    const message = event as SessionBrowserCooperationWsEvent & Record<string, unknown>;
    const statePatch = recordValue(message.state_patch);
    const stateCooperation = statePatch.cooperation;
    const cooperationPatch =
      stateCooperation && typeof stateCooperation === "object" && !Array.isArray(stateCooperation)
        ? (stateCooperation as SessionBrowserView["cooperation"])
        : "cooperation" in event
          ? event.cooperation
          : undefined;
    const debugPatch =
      event.type === "snapshot" || event.type === "timeline.patch" || event.type === "event_batch.accepted"
        ? {
            ...(cooperationPatch ?? {}),
            ...(Array.isArray(message.raw_events) ? { raw_events: message.raw_events } : {}),
            ...(Array.isArray(message.useful_timeline) ? { useful_timeline: message.useful_timeline } : {}),
            ...(Array.isArray(message.recent_user_events) ? { recent_user_events: message.recent_user_events } : {}),
            ...(Array.isArray(message.recent_agent_events) ? { recent_agent_events: message.recent_agent_events } : {}),
            ...(Array.isArray(message.pending_action_proposals)
              ? { pending_action_proposals: message.pending_action_proposals }
              : {}),
            ...(message.page_state ? { page_state: message.page_state } : {}),
          }
        : cooperationPatch;
    applyBrowserCooperationPatch(tabId, debugPatch as SessionBrowserView["cooperation"]);
  };

  useEffect(() => {
    return () => {
      Object.values(cooperationSocketsRef.current).forEach((socket) => socket.close());
      cooperationSocketsRef.current = {};
    };
  }, []);

  useEffect(() => {
    const browser = activeTab.browser;
    const enabled = Boolean(browserCooperationFromView(browser?.view)?.enabled);
    if (!visible || !baseUrl || !conversationId || !browser || !enabled) return;
    const socketKey = browser.browserId;
    const existing = cooperationSocketsRef.current[socketKey];
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;
    const socket = connectSessionBrowserCooperation(baseUrl, conversationId, browser.browserId, {
      onMessage: (event) => applyBrowserCooperationWsEvent(activeTab.id, event),
      onClose: () => {
        if (cooperationSocketsRef.current[socketKey] === socket) delete cooperationSocketsRef.current[socketKey];
      },
    });
    cooperationSocketsRef.current[socketKey] = socket;
    const pingInterval = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping" }));
      }
    }, 2000);
    return () => {
      window.clearInterval(pingInterval);
      if (cooperationSocketsRef.current[socketKey] === socket) delete cooperationSocketsRef.current[socketKey];
      socket.close();
    };
  }, [
    activeTab.id,
    activeTab.browser?.browserId,
    baseUrl,
    browserCooperationFromView(activeTab.browser?.view)?.enabled,
    conversationId,
    visible,
  ]);

  const setBrowserCooperationMode = async (
    tabId: string,
    mode: SessionBrowserCooperationMode | "off",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !conversationId) return;
    const enabled = mode !== "off";
    const nextMode = enabled ? mode : browserCooperationFromView(browser.view)?.mode ?? "observe_only";
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "mode.set", enabled, mode: nextMode }));
      return;
    }
    try {
      const result = await setSessionBrowserCooperation(baseUrl, conversationId, browser.browserId, {
        enabled,
        mode: nextMode,
      });
      applyBrowserCooperationPatch(tabId, result.cooperation);
    } catch (error) {
      setBrowserError(tabId, error);
    }
  };

  const decideBrowserProposal = async (
    tabId: string,
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser) return;
    const proposalId = String(proposal.proposal_id ?? proposal.id ?? "");
    if (!proposalId) return;
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: `proposal.${decision}`, proposal_id: proposalId }));
    }
    if (decision === "approve") {
      await approvePendingTool();
    } else if (decision === "deny") {
      await rejectPendingTool();
    }
  };

  const recordBrowserEvents = async (tabId: string, events: SessionBrowserCooperationEvent[]) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !conversationId || !events.length) return;
    if (!browserCooperationFromView(browser.view)?.enabled) return;
    const socket = cooperationSocketsRef.current[browser.browserId];
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "event_batch", events }));
      return;
    }
    try {
      const result = await ingestSessionBrowserEvents(baseUrl, conversationId, browser.browserId, events);
      applyBrowserCooperationPatch(tabId, result.state_patch.cooperation);
    } catch {
      // Event ingestion is best-effort; normal browsing should not be interrupted.
    }
  };

  return {
    tabs,
    activeTabId,
    activeTab,
    loadingDetailId,
    browserVisualEvents,
    browserToolEvent,
    browserToolTabs,
    setActiveTabId,
    closeTab,
    openBrowserPlaceholder,
    openDetailTab,
    openProjectDetail,
    updateBrowserTab,
    browserForTab,
    loadBrowserView,
    navigateBrowser,
    moveBrowserHistory,
    refreshBrowser,
    clickBrowser,
    keyBrowser,
    scrollBrowser,
    setBrowserMode,
    selectBrowserElement,
    updateAnnotationDraft,
    addBrowserTextSelection,
    saveBrowserAnnotation,
    activateBrowserElement,
    applyBrowserCooperationPatch,
    setBrowserCooperationMode,
    decideBrowserProposal,
    recordBrowserEvents,
    setBrowserError,
    applyBrowserView,
  };
}
