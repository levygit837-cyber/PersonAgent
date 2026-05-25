import { useEffect, useMemo, useRef, useState } from "react";
import {
  getSessionBrowserView,
} from "../../../../api/client";
import type { ComposerAnnotation } from "../../../../stores/chat-store";
import type { ToolBlockUi } from "../../../../types/chat";
import {
  browserToolEventAppliesToBrowser,
  browserToolEventIsAction,
  browserToolEventIsPassive,
  browserVisualEventsFromBlocks,
} from "../helpers/browser-helpers";
import { browserTabsFromBlocks } from "../helpers/browser-tab-helpers";
import {
  browserHasMeaningfulPage,
  browserMeaningfulToolUrl,
  browserSnapshotViewFromToolEvent,
  browserToolEventUrl,
  browserToolShouldFetchRenderedView,
  browserToolShouldHydrateView,
  browserToolShouldPreserveCurrentView,
  browserToolShouldSyncDisplayedPage,
  browserToolUrlChanged,
  browserViewFromToolEvent,
} from "../helpers/browser-view-helpers";
import {
  type BrowserState,
  type BrowserTab,
  type BrowserToolEvent,
  browserPanelTabId,
  browserPreferredSyncedView,
  browserStringValue,
  browserTabsRepresentSamePage,
  createEmptyBrowserState,
  isBrowserTab,
  normalizeComparableUrl,
  numericValue,
  summaryTab,
  BROWSER_TOOL_VIEW_SETTLE_MS,
} from "../helpers/helpers";
import { createTabState } from "./tab-state";
import { createBrowserNavigation } from "./browser-navigation";
import { createBrowserAnnotation } from "./browser-annotation";
import { useBrowserCooperation } from "./use-browser-cooperation";

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

  const tabState = useMemo(() => createTabState({
    tabs,
    setTabs,
    activeTabId,
    setActiveTabId,
    loadingDetailId,
    setLoadingDetailId,
    browserRequestIdsRef,
    conversationId,
    baseUrl,
    workspaceRoot,
  }), [tabs, activeTabId, loadingDetailId, conversationId, baseUrl, workspaceRoot]);
  const {
    closeTab,
    openBrowserPlaceholder,
    openDetailTab,
    openProjectDetail,
    updateBrowserTab,
    browserForTab,
    startBrowserRequest,
    applyBrowserView,
    setBrowserError,
  } = tabState;

  const browserNav = useMemo(() => createBrowserNavigation({
    browserForTab,
    startBrowserRequest,
    applyBrowserView,
    setBrowserError,
    baseUrl,
    conversationId,
  }), [browserForTab, startBrowserRequest, applyBrowserView, setBrowserError, baseUrl, conversationId]);
  const {
    loadBrowserView,
    navigateBrowser,
    moveBrowserHistory,
    refreshBrowser,
    clickBrowser,
    keyBrowser,
    scrollBrowser,
  } = browserNav;

  const browserAnnot = useMemo(() => createBrowserAnnotation({
    browserForTab,
    updateBrowserTab,
    startBrowserRequest,
    applyBrowserView,
    setBrowserError,
    baseUrl,
    conversationId,
    addComposerAnnotation,
  }), [browserForTab, updateBrowserTab, startBrowserRequest, applyBrowserView, setBrowserError, baseUrl, conversationId, addComposerAnnotation]);
  const {
    setBrowserMode,
    selectBrowserElement,
    updateAnnotationDraft,
    addBrowserTextSelection,
    saveBrowserAnnotation,
    activateBrowserElement,
  } = browserAnnot;

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

  const cooperation = useBrowserCooperation({
    browserForTab,
    updateBrowserTab,
    setBrowserError,
    cooperationSocketsRef,
    activeTab,
    baseUrl,
    conversationId,
    visible,
    approvePendingTool,
    rejectPendingTool,
  });
  const {
    applyBrowserCooperationPatch,
    setBrowserCooperationMode,
    decideBrowserProposal,
    recordBrowserEvents,
  } = cooperation;

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
