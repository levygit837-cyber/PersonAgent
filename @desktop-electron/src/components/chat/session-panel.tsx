import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode, type WheelEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ExternalLink,
  FilePenLine,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Globe2,
  ListChecks,
  MessageSquarePlus,
  MousePointerClick,
  RefreshCw,
  Loader2,
  PanelRightClose,
  Plus,
  Upload,
  X,
} from "lucide-react";
import {
  actSessionBrowser,
  clickSessionBrowser,
  createSessionBrowserAnnotation,
  getSessionBrowserView,
  getSessionPanel,
  getSessionProjectDetail,
  keySessionBrowser,
  navigateSessionBrowser,
  scrollSessionBrowser,
  type SessionBrowserAnnotation,
  type SessionBrowserElement,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../api/client";
import { cn } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore, type ComposerAnnotation } from "../../stores/chat-store";
import type {
  ChangedFile,
  ProjectItem,
  SessionPanelSnapshot,
  SessionSource,
  SessionUsage,
  SessionUsageMetric,
} from "../../types/chat";
import { emptySessionUsage } from "../../types/chat";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import type { SessionDetailView } from "./session-detail-window";

type BrowserTab = {
  id: string;
  title: string;
  subtitle?: string;
  closeable: boolean;
  detail?: SessionDetailView;
  browser?: BrowserState;
};

type BrowserState = {
  browserId: string;
  currentUrl: string;
  draftUrl: string;
  history: string[];
  historyIndex: number;
  mode: "browse" | "annotate" | "action";
  selectedNodeId?: string;
  elementMetadata: Record<string, BrowserElementMetadata>;
  annotationDraft: string;
  loading: boolean;
  requestId: number;
  error?: string;
  view?: SessionBrowserView;
};

type BrowserElementMetadata = SessionBrowserElement & {
  color?: string;
  background?: string;
  font?: string;
};

type BrowserTextSelectionMetadata = {
  text: string;
  node_id?: string;
  selector?: string;
  role?: string;
  tag?: string;
  start_offset?: number;
  end_offset?: number;
  bounds?: { x: number; y: number; width: number; height: number };
};

const summaryTab: BrowserTab = {
  id: "summary",
  title: "Summary",
  closeable: false,
};

export const SESSION_PANEL_CACHE_STORAGE_KEY = "personagent_session_panel_cache_v1";
const SESSION_PANEL_BACKGROUND_REFETCH_MS = 15_000;
const SESSION_PANEL_VISIBLE_REFETCH_MS = 5_000;
const SESSION_PANEL_STREAMING_REFETCH_MS = 1_500;
const SESSION_PANEL_CACHE_LIMIT = 24;
const SESSION_PANEL_CACHE_TEXT_LIMIT = 12_000;
const BROWSER_LOADING_MESSAGES = [
  "Preparando o ambiente...",
  "Baixando HTML da pagina...",
  "Aplicando CSS original...",
  "Estilizando seu site...",
  "Mapeando elementos clicaveis...",
];

function createEmptyBrowserState(browserId = `browser:${Date.now()}`): BrowserState {
  return {
    browserId,
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

function isBrowserTab(tab: BrowserTab) {
  return Boolean(tab.browser) || tab.id.startsWith("browser:") || tab.title === "Browser";
}

type SessionPanelCacheEntry = {
  cachedAt: number;
  snapshot: SessionPanelSnapshot;
};

type SessionPanelCacheStore = Record<string, SessionPanelCacheEntry>;

function readSessionPanelCache(
  baseUrl?: string,
  conversationId?: string,
  workspaceRoot?: string | null,
): SessionPanelCacheEntry | undefined {
  if (!baseUrl || !conversationId || typeof window === "undefined") return undefined;
  const store = readSessionPanelCacheStore();
  const entry = store[sessionPanelCacheKey(baseUrl, conversationId, workspaceRoot)];
  if (!entry || !isSessionPanelSnapshot(entry.snapshot)) return undefined;
  return entry;
}

function persistSessionPanelCache(
  baseUrl: string,
  conversationId: string | undefined,
  workspaceRoot: string | null | undefined,
  snapshot: SessionPanelSnapshot,
) {
  if (!baseUrl || !conversationId || typeof window === "undefined") return;
  if (snapshot.conversation_id !== conversationId) return;

  const store = readSessionPanelCacheStore();
  store[sessionPanelCacheKey(baseUrl, conversationId, workspaceRoot)] = {
    cachedAt: Date.now(),
    snapshot: compactSessionPanelSnapshotForCache(snapshot),
  };
  const prunedEntries = Object.entries(store)
    .sort(([, left], [, right]) => right.cachedAt - left.cachedAt)
    .slice(0, SESSION_PANEL_CACHE_LIMIT);

  try {
    window.localStorage.setItem(SESSION_PANEL_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(prunedEntries)));
  } catch {
    // Cache writes are best-effort. The panel can still fetch the live snapshot.
  }
}

function readSessionPanelCacheStore(): SessionPanelCacheStore {
  try {
    const raw = window.localStorage.getItem(SESSION_PANEL_CACHE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const store: SessionPanelCacheStore = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const entry = value as Partial<SessionPanelCacheEntry>;
      if (typeof entry.cachedAt !== "number" || !isSessionPanelSnapshot(entry.snapshot)) continue;
      store[key] = { cachedAt: entry.cachedAt, snapshot: entry.snapshot };
    }
    return store;
  } catch {
    return {};
  }
}

function sessionPanelCacheKey(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  return JSON.stringify([baseUrl.trim(), conversationId, workspaceRoot?.trim() || ""]);
}

function compactSessionPanelSnapshotForCache(snapshot: SessionPanelSnapshot): SessionPanelSnapshot {
  return {
    ...snapshot,
    changed_files: snapshot.changed_files.map((file) => ({
      ...file,
      diff: truncateCacheText(file.diff),
      content: truncateCacheText(file.content),
    })),
  };
}

function truncateCacheText(value?: string) {
  if (!value || value.length <= SESSION_PANEL_CACHE_TEXT_LIMIT) return value;
  return `${value.slice(0, SESSION_PANEL_CACHE_TEXT_LIMIT)}\n...`;
}

function isSessionPanelSnapshot(value: unknown): value is SessionPanelSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const snapshot = value as Partial<SessionPanelSnapshot>;
  return (
    typeof snapshot.conversation_id === "string" &&
    typeof snapshot.title === "string" &&
    typeof snapshot.updated_at === "string" &&
    Array.isArray(snapshot.changed_files) &&
    Array.isArray(snapshot.sources) &&
    Boolean(snapshot.usage) &&
    Boolean(snapshot.project)
  );
}

export function SessionPanel({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);
  const conversationId = useChatStore((state) => state.conversationId);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const liveUsage = useChatStore((state) => state.liveSessionUsage);
  const addComposerAnnotation = useChatStore((state) => state.addComposerAnnotation);
  const queryClient = useQueryClient();
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([summaryTab]);
  const [activeTabId, setActiveTabId] = useState(summaryTab.id);
  const browserRequestIdsRef = useRef<Record<string, number>>({});
  const cachedPanel = useMemo(
    () => readSessionPanelCache(baseUrl, conversationId, workspaceRoot),
    [baseUrl, conversationId, workspaceRoot],
  );

  const panel = useQuery({
    queryKey: ["session-panel", baseUrl, conversationId, workspaceRoot],
    queryFn: () => getSessionPanel(baseUrl, conversationId!, workspaceRoot),
    enabled: Boolean(visible && baseUrl && conversationId),
    initialData: () => cachedPanel?.snapshot,
    initialDataUpdatedAt: () => cachedPanel?.cachedAt,
    refetchInterval: isStreaming
      ? SESSION_PANEL_STREAMING_REFETCH_MS
      : visible
        ? SESSION_PANEL_VISIBLE_REFETCH_MS
        : SESSION_PANEL_BACKGROUND_REFETCH_MS,
    refetchIntervalInBackground: true,
    staleTime: 0,
  });

  useEffect(() => {
    const handler = () => {
      void queryClient.invalidateQueries({ queryKey: ["session-panel"] });
    };
    window.addEventListener("personagent:session-panel-changed", handler);
    window.addEventListener("personagent:conversations-changed", handler);
    return () => {
      window.removeEventListener("personagent:session-panel-changed", handler);
      window.removeEventListener("personagent:conversations-changed", handler);
    };
  }, [queryClient]);

  const snapshot = panel.data;
  useEffect(() => {
    if (!snapshot) return;
    persistSessionPanelCache(baseUrl, conversationId, workspaceRoot, snapshot);
  }, [baseUrl, conversationId, workspaceRoot, snapshot]);

  const usage = useMemo(() => mergeUsage(snapshot?.usage, liveUsage), [snapshot?.usage, liveUsage]);
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? summaryTab;

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

  const startBrowserRequest = (tabId: string) => {
    const requestId = (browserRequestIdsRef.current[tabId] ?? 0) + 1;
    browserRequestIdsRef.current[tabId] = requestId;
    updateBrowserTab(tabId, (browser) => ({ ...browser, requestId, loading: true, error: undefined }));
    return requestId;
  };

  const applyBrowserView = (
    tabId: string,
    view: SessionBrowserView,
    options: { addHistory?: boolean; historyIndex?: number } = {},
    requestId?: number,
  ) => {
    updateBrowserTab(tabId, (browser) => {
      if (requestId !== undefined && browserRequestIdsRef.current[tabId] !== requestId) return browser;
      const nextUrl = view.url && view.url !== "about:blank" ? view.url : browser.currentUrl;
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
          view.can_capture || view.render_mode === "html_mirror"
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

  const loadBrowserView = async (tabId: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await getSessionBrowserView(baseUrl, browser.browserId, viewport, conversationId);
      applyBrowserView(tabId, view, {}, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const navigateBrowser = async (tabId: string, rawUrl: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    const normalized = normalizeBrowserUrl(rawUrl);
    if (!browser || !normalized || !baseUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await navigateSessionBrowser(baseUrl, browser.browserId, { url: normalized, ...viewport }, conversationId);
      applyBrowserView(tabId, view, { addHistory: true }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const moveBrowserHistory = async (tabId: string, direction: -1 | 1, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl) return;
    const historyIndex = browser.historyIndex + direction;
    const targetUrl = browser.history[historyIndex];
    if (!targetUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await navigateSessionBrowser(baseUrl, browser.browserId, { url: targetUrl, ...viewport }, conversationId);
      applyBrowserView(tabId, view, { historyIndex }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
    }
  };

  const refreshBrowser = async (tabId: string, viewport: SessionBrowserViewport) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !browser.currentUrl) return;
    const requestId = startBrowserRequest(tabId);
    try {
      const view = await navigateSessionBrowser(
        baseUrl,
        browser.browserId,
        { url: browser.currentUrl, ...viewport },
        conversationId,
      );
      applyBrowserView(tabId, view, { historyIndex: browser.historyIndex }, requestId);
    } catch (error) {
      setBrowserError(tabId, error, requestId);
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

  const actOnBrowserElement = async (
    tabId: string,
    nodeId: string,
    viewport: SessionBrowserViewport,
    action: "click" | "submit" = "click",
  ) => {
    const browser = browserForTab(tabId);
    if (!browser || !baseUrl || !conversationId) return;
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

  return (
    <aside className="flex h-full min-w-0 w-full flex-col bg-popover">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3">
        <PanelRightClose className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">Session Panel</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {snapshot?.title || (conversationId ? "Active session" : "No conversation")}
          </div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Close session panel" onClick={onClose}>
              <PanelRightClose className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Close</TooltipContent>
        </Tooltip>
      </div>

      <BrowserTabStrip
        tabs={tabs}
        activeTabId={activeTabId}
        onSelect={setActiveTabId}
        onClose={closeTab}
        onAdd={openBrowserPlaceholder}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-3">
        {isBrowserTab(activeTab) ? (
          <DetailTabContent
            tab={activeTab}
            onBrowserDraftChange={(value) => updateBrowserTab(activeTab.id, (browser) => ({ ...browser, draftUrl: value }))}
            onBrowserLoad={(viewport) => void loadBrowserView(activeTab.id, viewport)}
            onBrowserNavigate={(value, viewport) => void navigateBrowser(activeTab.id, value, viewport)}
            onBrowserBack={(viewport) => void moveBrowserHistory(activeTab.id, -1, viewport)}
            onBrowserForward={(viewport) => void moveBrowserHistory(activeTab.id, 1, viewport)}
            onBrowserRefresh={(viewport) => void refreshBrowser(activeTab.id, viewport)}
            onBrowserClick={(input) => void clickBrowser(activeTab.id, input)}
            onBrowserKey={(input) => void keyBrowser(activeTab.id, input)}
            onBrowserScroll={(input) => void scrollBrowser(activeTab.id, input)}
            onBrowserModeChange={(mode) => setBrowserMode(activeTab.id, mode)}
            onBrowserElementSelect={(nodeId, element) => selectBrowserElement(activeTab.id, nodeId, element)}
            onBrowserTextSelect={(selection) => addBrowserTextSelection(activeTab.id, selection)}
            onBrowserAnnotationDraftChange={(value) => updateAnnotationDraft(activeTab.id, value)}
            onBrowserAnnotationSave={() => void saveBrowserAnnotation(activeTab.id)}
            onBrowserAction={(nodeId, viewport) => void actOnBrowserElement(activeTab.id, nodeId, viewport)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
          />
        ) : !conversationId ? (
          <EmptyPanel text="Start or open a conversation to view session data." />
        ) : panel.isLoading ? (
          <PanelSkeleton />
        ) : panel.error ? (
          <EmptyPanel text={panel.error instanceof Error ? panel.error.message : String(panel.error)} />
        ) : activeTab.id === summaryTab.id ? (
          <SummaryContent
            snapshot={snapshot}
            usage={usage}
            loadingDetailId={loadingDetailId}
            onOpenDetail={openDetailTab}
            onOpenProjectDetail={(item) => void openProjectDetail(item)}
          />
        ) : (
          <DetailTabContent
            tab={activeTab}
            onBrowserDraftChange={(value) => updateBrowserTab(activeTab.id, (browser) => ({ ...browser, draftUrl: value }))}
            onBrowserLoad={(viewport) => void loadBrowserView(activeTab.id, viewport)}
            onBrowserNavigate={(value, viewport) => void navigateBrowser(activeTab.id, value, viewport)}
            onBrowserBack={(viewport) => void moveBrowserHistory(activeTab.id, -1, viewport)}
            onBrowserForward={(viewport) => void moveBrowserHistory(activeTab.id, 1, viewport)}
            onBrowserRefresh={(viewport) => void refreshBrowser(activeTab.id, viewport)}
            onBrowserClick={(input) => void clickBrowser(activeTab.id, input)}
            onBrowserKey={(input) => void keyBrowser(activeTab.id, input)}
            onBrowserScroll={(input) => void scrollBrowser(activeTab.id, input)}
            onBrowserModeChange={(mode) => setBrowserMode(activeTab.id, mode)}
            onBrowserElementSelect={(nodeId, element) => selectBrowserElement(activeTab.id, nodeId, element)}
            onBrowserTextSelect={(selection) => addBrowserTextSelection(activeTab.id, selection)}
            onBrowserAnnotationDraftChange={(value) => updateAnnotationDraft(activeTab.id, value)}
            onBrowserAnnotationSave={() => void saveBrowserAnnotation(activeTab.id)}
            onBrowserAction={(nodeId, viewport) => void actOnBrowserElement(activeTab.id, nodeId, viewport)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
          />
        )}
      </div>
    </aside>
  );
}

function BrowserTabStrip({
  tabs,
  activeTabId,
  onSelect,
  onClose,
  onAdd,
}: {
  tabs: BrowserTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onAdd: () => void;
}) {
  return (
    <div className="flex h-11 shrink-0 items-end border-b border-glass-border/25 bg-background/80 px-2 pt-1.5" role="tablist" aria-label="Session panel tabs">
      <div className="flex min-w-0 flex-1 items-end gap-1 overflow-x-auto">
        {tabs.map((tab) => {
          const active = tab.id === activeTabId;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={tab.title}
              className={cn(
                "group relative flex h-8 max-w-[170px] min-w-0 items-center gap-1.5 rounded-t-xl px-3 text-left text-xs transition-[background,color,box-shadow]",
                active
                  ? "bg-popover text-foreground shadow-[inset_0_1px_0_hsl(var(--glass-border)_/_0.45),inset_1px_0_0_hsl(var(--glass-border)_/_0.35),inset_-1px_0_0_hsl(var(--glass-border)_/_0.35)]"
                  : "bg-transparent text-muted-foreground hover:bg-muted/70 hover:text-foreground",
              )}
              onClick={() => onSelect(tab.id)}
            >
              <span className="min-w-0 flex-1 truncate">{tab.title}</span>
              {tab.closeable ? (
                <span
                  role="button"
                  aria-label={`Close tab ${tab.title}`}
                  tabIndex={0}
                  className="grid h-4 w-4 shrink-0 place-items-center rounded text-muted-foreground opacity-0 hover:bg-accent hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100"
                  onClick={(event) => {
                    event.stopPropagation();
                    onClose(tab.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      event.stopPropagation();
                      onClose(tab.id);
                    }
                  }}
                >
                  <X className="h-3 w-3" />
                </span>
              ) : null}
            </button>
          );
        })}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="New panel tab"
              className="mb-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" sideOffset={8} className="w-48 rounded-xl">
            <DropdownMenuLabel>New tab</DropdownMenuLabel>
            <DropdownMenuItem onClick={onAdd} className="gap-2 rounded-lg">
              <Globe2 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="min-w-0 flex-1">Browser</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <div className="h-8 min-w-2 flex-1" />
      </div>
    </div>
  );
}

function SummaryContent({
  snapshot,
  usage,
  loadingDetailId,
  onOpenDetail,
  onOpenProjectDetail,
}: {
  snapshot?: SessionPanelSnapshot;
  usage: SessionUsage;
  loadingDetailId: string | null;
  onOpenDetail: (detail: SessionDetailView) => void;
  onOpenProjectDetail: (item: ProjectItem) => void;
}) {
  const project = snapshot?.project;
  return (
    <div className="space-y-5">
      <MetricBand
        items={[
          ["Files", snapshot?.changed_files.length ?? 0],
          ["Sources", snapshot?.sources.length ?? 0],
          ["Tools", usage.tool_calls.value],
          ["Plans", usage.plans_created.value],
        ]}
      />
      <UsageSection usage={usage} />
      <FilesSection files={snapshot?.changed_files ?? []} onOpenDetail={onOpenDetail} />
      <SourcesSection sources={snapshot?.sources ?? []} onOpenDetail={onOpenDetail} />
      <ProjectSection
        project={project}
        loadingDetailId={loadingDetailId}
        onOpenProjectDetail={onOpenProjectDetail}
      />
    </div>
  );
}

function UsageSection({ usage }: { usage: SessionUsage }) {
  const rows: Array<[string, SessionUsageMetric]> = [
    ["Agent Output Tokens", usage.agent_output_tokens],
    ["Thinking Output Tokens", usage.thinking_output_tokens],
    ["Tool Calls", usage.tool_calls],
    ["Skills used count", usage.skills_used_count],
    ["MCP calls count", usage.mcp_calls_count],
    ["Plans Created", usage.plans_created],
    ["Todo's Created", usage.todos_created],
    ["SubAgents Used", usage.subagents_used],
  ];
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<Activity className="h-3.5 w-3.5" />} title="Agent Usage" />
      <div className="mt-2 divide-y divide-glass-border/25">
        {rows.map(([label, metric]) => (
          <div key={label} className="flex items-center gap-3 py-2 text-xs">
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{label}</span>
            <span className="font-mono text-foreground">{formatNumber(metric.value)}</span>
            {metric.estimated ? <span className="font-mono text-[10px] text-warning">estimated</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function FilesSection({
  files,
  onOpenDetail,
}: {
  files: ChangedFile[];
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<FilePenLine className="h-3.5 w-3.5" />} title="Changed Files" />
      {files.length === 0 ? <EmptyList text="No changed files in this session." /> : null}
      <div className="mt-2 divide-y divide-glass-border/25">
        {files.map((file) => (
          <button
            key={file.id}
            type="button"
            className="flex w-full min-w-0 items-center gap-2 py-2 text-left transition-colors hover:bg-accent/60"
            onClick={() =>
              onOpenDetail({
                type: "file",
                id: file.id,
                title: file.display_path,
                subtitle: file.source,
                metadata: {
                  path: file.path,
                  status: file.status,
                  source: file.source,
                  additions: file.added_lines,
                  deletions: file.removed_lines,
                },
                patch: file.diff || file.content,
              })
            }
          >
            <span className="min-w-0 flex-1 truncate text-xs text-foreground">{file.display_path}</span>
            <span className="font-mono text-[11px] text-success">+{file.added_lines}</span>
            <span className="font-mono text-[11px] text-destructive">-{file.removed_lines}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function SourcesSection({
  sources,
  onOpenDetail,
}: {
  sources: SessionSource[];
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<ExternalLink className="h-3.5 w-3.5" />} title="Sources" />
      {sources.length === 0 ? <EmptyList text="No sources registered." /> : null}
      <div className="mt-2 divide-y divide-glass-border/25">
        {sources.map((source) => (
          <button
            key={source.id}
            type="button"
            className="flex w-full min-w-0 items-start gap-2 py-2 text-left transition-colors hover:bg-accent/60"
            onClick={() =>
              onOpenDetail({
                type: "source",
                id: source.id,
                title: source.title,
                subtitle: source.domain,
                url: source.url,
                metadata: {
                  url: source.url,
                  domain: source.domain,
                  tool: source.tool_name,
                  description: source.description,
                },
              })
            }
          >
            <img src={source.favicon_url} alt="" className="mt-0.5 h-4 w-4 shrink-0 rounded-sm" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs text-foreground">{source.title}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{source.description || source.url}</span>
            </span>
            <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </div>
    </section>
  );
}

function ProjectSection({
  project,
  loadingDetailId,
  onOpenProjectDetail,
}: {
  project?: SessionPanelSnapshot["project"];
  loadingDetailId: string | null;
  onOpenProjectDetail: (item: ProjectItem) => void;
}) {
  if (!project) {
    return (
      <section className="border-t border-glass-border/25 pt-3">
        <SectionTitle icon={<GitBranch className="h-3.5 w-3.5" />} title="Project Details" />
        <EmptyList text="Project unavailable." />
      </section>
    );
  }
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<GitBranch className="h-3.5 w-3.5" />} title="Project Details" />
      <div className="mt-2 space-y-4">
        <div className="space-y-1 text-xs text-muted-foreground">
          <div className="truncate">{project.repo?.name_with_owner || "Repository not detected"}</div>
          <div className="truncate">Default branch: {project.repo?.default_branch || "N/A"}</div>
        </div>
        <ProjectGroup icon={<GitPullRequest className="h-3.5 w-3.5" />} title="Last PR's" items={project.prs} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<GitBranch className="h-3.5 w-3.5" />} title="Branches" items={project.branches} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<Upload className="h-3.5 w-3.5" />} title="Last Pushs" items={project.pushes} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<GitCommit className="h-3.5 w-3.5" />} title="Last Commits" items={project.commits} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        {project.errors.length ? (
          <div className="border-t border-warning/30 pt-2 text-[11px] leading-4 text-warning">
            {project.errors[0]}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ProjectGroup({
  icon,
  title,
  items,
  loadingDetailId,
  onOpen,
}: {
  icon: ReactNode;
  title: string;
  items: ProjectItem[];
  loadingDetailId: string | null;
  onOpen: (item: ProjectItem) => void;
}) {
  return (
    <div>
      <SectionTitle icon={icon} title={title} />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {items.length === 0 ? <div className="py-2 text-[11px] text-muted-foreground">No data.</div> : null}
        {items.map((item) => {
          const loading = loadingDetailId === `${item.type}:${item.id}`;
          return (
            <button
              key={`${item.type}:${item.id}`}
              type="button"
              className={cn(
                "group flex w-full min-w-0 items-center gap-2 py-2 text-left transition-colors hover:bg-accent/70",
                item.active && "text-primary",
              )}
              onClick={() => onOpen(item)}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-foreground group-hover:text-primary">{item.title}</span>
                {item.subtitle ? <span className="block truncate text-[11px] text-muted-foreground">{item.subtitle}</span> : null}
              </span>
              {loading ? <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DetailTabContent({
  tab,
  onBrowserDraftChange,
  onBrowserLoad,
  onBrowserNavigate,
  onBrowserBack,
  onBrowserForward,
  onBrowserRefresh,
  onBrowserClick,
  onBrowserKey,
  onBrowserScroll,
  onBrowserModeChange,
  onBrowserElementSelect,
  onBrowserTextSelect,
  onBrowserAnnotationDraftChange,
  onBrowserAnnotationSave,
  onBrowserAction,
  canPersistBrowserWorkspace,
}: {
  tab: BrowserTab;
  onBrowserDraftChange: (value: string) => void;
  onBrowserLoad: (viewport: SessionBrowserViewport) => void;
  onBrowserNavigate: (value: string, viewport: SessionBrowserViewport) => void;
  onBrowserBack: (viewport: SessionBrowserViewport) => void;
  onBrowserForward: (viewport: SessionBrowserViewport) => void;
  onBrowserRefresh: (viewport: SessionBrowserViewport) => void;
  onBrowserClick: (input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" }) => void;
  onBrowserKey: (input: SessionBrowserViewport & { text?: string; key?: string }) => void;
  onBrowserScroll: (input: SessionBrowserViewport & { delta_x: number; delta_y: number }) => void;
  onBrowserModeChange: (mode: BrowserState["mode"]) => void;
  onBrowserElementSelect: (nodeId: string, element?: BrowserElementMetadata) => void;
  onBrowserTextSelect: (selection: BrowserTextSelectionMetadata) => void;
  onBrowserAnnotationDraftChange: (value: string) => void;
  onBrowserAnnotationSave: () => void;
  onBrowserAction: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  canPersistBrowserWorkspace: boolean;
}) {
  if (isBrowserTab(tab)) {
    return (
      <BrowserTabContent
        browser={tab.browser ?? createEmptyBrowserState(tab.id)}
        onDraftChange={onBrowserDraftChange}
        onLoadView={onBrowserLoad}
        onNavigate={onBrowserNavigate}
        onBack={onBrowserBack}
        onForward={onBrowserForward}
        onRefresh={onBrowserRefresh}
        onBrowserClick={onBrowserClick}
        onBrowserKey={onBrowserKey}
        onBrowserScroll={onBrowserScroll}
        onModeChange={onBrowserModeChange}
        onElementSelect={onBrowserElementSelect}
        onTextSelect={onBrowserTextSelect}
        onAnnotationDraftChange={onBrowserAnnotationDraftChange}
        onAnnotationSave={onBrowserAnnotationSave}
        onBrowserAction={onBrowserAction}
        canPersistWorkspace={canPersistBrowserWorkspace}
      />
    );
  }
  if (!tab.detail) return <EmptyPanel text="Empty tab." />;
  const detail = tab.detail;
  return (
    <div className="space-y-3">
      <div className="border-b border-glass-border/25 pb-3">
        <div className="truncate text-sm font-medium text-foreground">{detail.title}</div>
        {detail.subtitle ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{detail.subtitle}</div> : null}
        {detail.url ? (
          <a href={detail.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
            Open URL
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </div>
      {detail.error ? (
        <div className="border-y border-destructive/30 py-2 text-xs text-destructive">
          {detail.error}
        </div>
      ) : null}
      {detail.metadata ? <MetadataBlock metadata={detail.metadata} /> : null}
      {detail.files?.length ? <FilesBlock files={detail.files} /> : null}
      {detail.commits?.length ? <CommitsBlock commits={detail.commits} /> : null}
      {detail.patch ? (
        <pre className="max-h-[48vh] overflow-auto rounded-xl border border-glass-border/35 bg-background/70 p-3 font-mono text-[11px] leading-5 text-muted-foreground">
          {detail.patch}
        </pre>
      ) : null}
    </div>
  );
}

function BrowserTabContent({
  browser,
  onDraftChange,
  onLoadView,
  onNavigate,
  onBack,
  onForward,
  onRefresh,
  onBrowserClick,
  onBrowserKey,
  onBrowserScroll,
  onModeChange,
  onElementSelect,
  onTextSelect,
  onAnnotationDraftChange,
  onAnnotationSave,
  onBrowserAction,
  canPersistWorkspace,
}: {
  browser: BrowserState;
  onDraftChange: (value: string) => void;
  onLoadView: (viewport: SessionBrowserViewport) => void;
  onNavigate: (value: string, viewport: SessionBrowserViewport) => void;
  onBack: (viewport: SessionBrowserViewport) => void;
  onForward: (viewport: SessionBrowserViewport) => void;
  onRefresh: (viewport: SessionBrowserViewport) => void;
  onBrowserClick: (input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" }) => void;
  onBrowserKey: (input: SessionBrowserViewport & { text?: string; key?: string }) => void;
  onBrowserScroll: (input: SessionBrowserViewport & { delta_x: number; delta_y: number }) => void;
  onModeChange: (mode: BrowserState["mode"]) => void;
  onElementSelect: (nodeId: string, element?: BrowserElementMetadata) => void;
  onTextSelect: (selection: BrowserTextSelectionMetadata) => void;
  onAnnotationDraftChange: (value: string) => void;
  onAnnotationSave: () => void;
  onBrowserAction: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  canPersistWorkspace: boolean;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const annotationInputRef = useRef<HTMLTextAreaElement | null>(null);
  const requestedInitialViewRef = useRef(false);
  const lastBrowserIdRef = useRef(browser.browserId);
  const [mirrorUrl, setMirrorUrl] = useState("");
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const canGoBack = browser.historyIndex > 0;
  const canGoForward = browser.historyIndex >= 0 && browser.historyIndex < browser.history.length - 1;
  const canRefresh = Boolean(browser.currentUrl);
  const imageSource =
    browser.view?.image_data && browser.view.image_mime_type
      ? `data:${browser.view.image_mime_type};base64,${browser.view.image_data}`
      : "";
  const showRenderedPage = Boolean(imageSource && browser.currentUrl);
  const documentHtml = browser.view?.document_html || browser.view?.browser_snapshot?.document_html || browser.view?.html || "";
  const elementMap = browser.view?.element_map || browser.view?.browser_snapshot?.element_map || [];
  const annotations = browser.view?.annotations || browser.view?.browser_snapshot?.annotations || [];
  const timelineEvents = browser.view?.timeline_events || browser.view?.browser_snapshot?.timeline_events || [];
  const showHtmlMirror = Boolean(browser.currentUrl && browser.view?.render_mode === "html_mirror" && documentHtml);
  const mirrorDocument = showHtmlMirror
    ? browserMirrorSrcDoc(documentHtml, browser.currentUrl, browser.browserId)
    : "";
  const annotationCounts = useMemo(() => browserAnnotationCounts(annotations), [annotations]);
  const selectedElement = browser.selectedNodeId
    ? elementMap.find((item) => item.node_id === browser.selectedNodeId) ?? browser.elementMetadata[browser.selectedNodeId]
    : undefined;
  const viewport = () => browserViewport(viewportRef.current, browser.view);
  const showEmptyState = !browser.loading && !showRenderedPage && !(showHtmlMirror && mirrorUrl);

  if (lastBrowserIdRef.current !== browser.browserId) {
    lastBrowserIdRef.current = browser.browserId;
    requestedInitialViewRef.current = false;
  }

  useEffect(() => {
    if (requestedInitialViewRef.current || browser.view || browser.loading) return;
    requestedInitialViewRef.current = true;
    onLoadView(viewport());
  }, [browser.browserId, browser.loading, browser.view, onLoadView]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data =
        event.data as
          | {
              type?: unknown;
              browserId?: unknown;
              url?: unknown;
              nodeId?: unknown;
              action?: unknown;
              element?: unknown;
              selection?: unknown;
            }
          | undefined;
      if (
        !data ||
        data.browserId !== browser.browserId
      ) {
        return;
      }
      if (data.type === "personagent-session-browser:navigate" && typeof data.url === "string") {
        onNavigate(data.url, viewport());
      } else if (data.type === "personagent-session-browser:element" && typeof data.nodeId === "string") {
        const element = normalizeBrowserElementMetadata(data.element, data.nodeId);
        if (browser.mode === "action") {
          onBrowserAction(data.nodeId, viewport());
        } else {
          onElementSelect(data.nodeId, element);
        }
      } else if (data.type === "personagent-session-browser:element-action" && typeof data.nodeId === "string") {
        onBrowserAction(data.nodeId, viewport(), data.action === "submit" ? "submit" : "click");
      } else if (data.type === "personagent-session-browser:text-selection") {
        const selection = normalizeBrowserTextSelection(data.selection);
        if (selection) {
          onTextSelect(selection);
        }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [browser.browserId, browser.mode, onBrowserAction, onElementSelect, onNavigate, onTextSelect]);

  useEffect(() => {
    if (browser.mode !== "annotate" || !browser.selectedNodeId) return;
    annotationInputRef.current?.focus();
  }, [browser.mode, browser.selectedNodeId]);

  useEffect(() => {
    if (!browser.loading) {
      setLoadingMessageIndex(0);
      return;
    }
    const interval = window.setInterval(() => {
      setLoadingMessageIndex((current) => (current + 1) % BROWSER_LOADING_MESSAGES.length);
    }, 1200);
    return () => window.clearInterval(interval);
  }, [browser.loading]);

  useEffect(() => {
    if (!mirrorDocument || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setMirrorUrl("");
      return;
    }
    const nextUrl = URL.createObjectURL(new Blob([mirrorDocument], { type: "text/html" }));
    setMirrorUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [mirrorDocument]);

  const postMirrorState = () => {
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage(
      {
        type: "personagent-session-browser:state",
        browserId: browser.browserId,
        mode: browser.mode,
        annotationCounts,
        selectedNodeId: browser.selectedNodeId || "",
      },
      "*",
    );
  };

  useEffect(() => {
    postMirrorState();
  }, [browser.browserId, browser.mode, browser.selectedNodeId, annotationCounts, mirrorUrl]);

  const handleViewportClick = (event: MouseEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view || !imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    viewportRef.current?.focus();
    const targetWidth = browser.view.viewport_width || rect.width;
    const targetHeight = browser.view.viewport_height || rect.height;
    onBrowserClick({
      width: targetWidth,
      height: targetHeight,
      x: ((event.clientX - rect.left) / rect.width) * targetWidth,
      y: ((event.clientY - rect.top) / rect.height) * targetHeight,
      button: event.button === 1 ? "middle" : event.button === 2 ? "right" : "left",
    });
  };

  const handleViewportKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view || event.ctrlKey || event.metaKey || event.altKey) return;
    const currentViewport = viewport();
    if (event.key.length === 1) {
      event.preventDefault();
      onBrowserKey({ ...currentViewport, text: event.key });
      return;
    }
    if (BROWSER_FORWARD_KEYS.has(event.key)) {
      event.preventDefault();
      onBrowserKey({ ...currentViewport, key: event.key });
    }
  };

  const handleViewportWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view) return;
    event.preventDefault();
    onBrowserScroll({ ...viewport(), delta_x: event.deltaX, delta_y: event.deltaY });
  };

  return (
    <div className="flex min-h-[calc(100vh-170px)] flex-col">
      <div className="-mx-3 -mt-3 flex h-11 shrink-0 items-center gap-1.5 border-b border-glass-border/25 bg-background/70 px-3">
        <BrowserNavButton label="Back" disabled={!canGoBack} onClick={() => onBack(viewport())}>
          <ArrowLeft className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <BrowserNavButton label="Forward" disabled={!canGoForward} onClick={() => onForward(viewport())}>
          <ArrowRight className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <BrowserNavButton label="Reload page" disabled={!canRefresh} onClick={() => onRefresh(viewport())}>
          <RefreshCw className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <form
          className="ml-1 min-w-0 flex-1"
          onSubmit={(event) => {
            event.preventDefault();
            onNavigate(browser.draftUrl, viewport());
          }}
        >
          <input
            aria-label="Enter URL"
            className="h-8 w-full rounded-full border border-glass-border/35 bg-card/70 px-3 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/50 focus:bg-background"
            placeholder="Enter URL"
            value={browser.draftUrl}
            onChange={(event) => onDraftChange(event.currentTarget.value)}
          />
        </form>
        <BrowserModeButton
          label="Inspect and annotate"
          active={browser.mode === "annotate"}
          disabled={!showHtmlMirror}
          onClick={() => onModeChange(browser.mode === "annotate" ? "browse" : "annotate")}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
        </BrowserModeButton>
        <BrowserModeButton
          label="Action mode"
          active={browser.mode === "action"}
          disabled={!showHtmlMirror || !canPersistWorkspace}
          onClick={() => onModeChange(browser.mode === "action" ? "browse" : "action")}
        >
          <MousePointerClick className="h-3.5 w-3.5" />
        </BrowserModeButton>
      </div>
      <div className="-mx-3 flex h-8 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-background/55 px-3 text-[11px] text-muted-foreground">
        <span className={cn("rounded-full border px-2 py-0.5", browserCssBadgeClass(browser.view?.css_fidelity))}>
          {browserCssLabel(browser.view?.css_fidelity)}
        </span>
        <span className="min-w-0 flex-1 truncate">
          {browser.mode === "annotate"
            ? "Annotation mode · hover and click an element"
            : browser.mode === "action"
              ? "Action mode · click mapped elements"
              : `${elementMap.length} mapped elements`}
        </span>
        {annotations.length ? (
          <span className="inline-flex items-center gap-1">
            <MessageSquarePlus className="h-3 w-3" />
            {annotations.length}
          </span>
        ) : null}
        {timelineEvents.length ? (
          <span className="inline-flex items-center gap-1">
            <ListChecks className="h-3 w-3" />
            {timelineEvents.length}
          </span>
        ) : null}
      </div>
      <div
        ref={viewportRef}
        role="application"
        aria-label="LightPanda browser viewport"
        tabIndex={0}
        className="relative -mx-3 -mb-4 min-h-[calc(100vh-220px)] flex-1 overflow-hidden bg-background outline-none"
        onClick={handleViewportClick}
        onKeyDown={handleViewportKeyDown}
        onWheel={handleViewportWheel}
      >
        {showRenderedPage ? (
          <img
            ref={imageRef}
            src={imageSource}
            alt={browser.view?.title || browser.currentUrl || "LightPanda browser"}
            title={`Browser ${browser.currentUrl || browser.view?.url || ""}`.trim()}
            className="h-full min-h-[calc(100vh-220px)] w-full select-none object-contain"
            draggable={false}
          />
        ) : showHtmlMirror && mirrorUrl ? (
          <iframe
            ref={iframeRef}
            title={`Browser ${browser.currentUrl}`}
            src={mirrorUrl}
            sandbox="allow-forms allow-scripts"
            onLoad={postMirrorState}
            className="h-full min-h-[calc(100vh-220px)] w-full border-0 bg-white"
          />
        ) : showEmptyState ? (
          <div className="flex h-full min-h-[260px] items-center justify-center px-8 text-center text-xs leading-5 text-muted-foreground">
            Enter a URL to open a page in this tab.
          </div>
        ) : null}
        {browser.loading ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-background/78 px-8 text-center backdrop-blur-sm">
            <div className="flex max-w-[300px] flex-col items-center gap-3 rounded-2xl border border-glass-border/35 bg-card/86 px-5 py-5 shadow-floating ring-1 ring-white/[0.04]">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <div className="space-y-1">
                <div className="text-sm font-medium text-foreground">{BROWSER_LOADING_MESSAGES[loadingMessageIndex]}</div>
                <div className="text-[11px] leading-4 text-muted-foreground">
                  Preparando HTML, CSS e mapa de elementos do Browser.
                </div>
              </div>
            </div>
          </div>
        ) : null}
        {browser.error ? (
          <div className="absolute inset-x-4 bottom-4 rounded-lg border border-destructive/35 bg-background/90 px-3 py-2 text-[11px] leading-4 text-destructive">
            {browser.error}
          </div>
        ) : null}
        {browser.mode === "annotate" && browser.selectedNodeId ? (
          <form
            data-browser-annotation-editor="true"
            className="absolute z-30 max-w-[calc(100%-24px)] rounded-2xl border border-glass-border/40 bg-card/88 p-2 text-xs shadow-floating ring-1 ring-white/[0.04] backdrop-blur-2xl"
            style={browserAnnotationEditorStyle(selectedElement?.bounds, browser.view)}
            onSubmit={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onAnnotationSave();
            }}
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
            onWheel={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <div className="mb-2 flex items-start gap-2">
              <MessageSquarePlus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-foreground">
                  {selectedElementLabel(selectedElement, browser.selectedNodeId)}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                  {selectedElement?.text || selectedElement?.selector || "Browser element"}
                </div>
              </div>
              <button
                type="button"
                className="text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => onElementSelect("")}
                aria-label="Close annotation editor"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <textarea
              ref={annotationInputRef}
              value={browser.annotationDraft}
              onChange={(event) => onAnnotationDraftChange(event.currentTarget.value)}
              placeholder="Ask the agent about this element or describe a change"
              rows={1}
              className="max-h-24 min-h-10 w-full resize-none rounded-xl border border-glass-border/30 bg-background/45 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/75 focus:border-primary/45"
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  onAnnotationSave();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  onElementSelect("");
                }
              }}
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => onElementSelect("")}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={!browser.annotationDraft.trim()}
              >
                Send to Agent
              </Button>
            </div>
          </form>
        ) : null}
        {timelineEvents.length ? (
          <div className="pointer-events-none absolute inset-x-3 top-3 max-h-28 space-y-1 overflow-hidden">
            {timelineEvents.slice(-3).map((event) => (
              <div
                key={event.id}
                className="truncate rounded-full border border-glass-border/30 bg-background/82 px-2 py-1 text-[11px] text-muted-foreground shadow-lg"
              >
                <span className="text-foreground">{event.source}</span>
                <span className="mx-1">·</span>
                {event.label}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function BrowserNavButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
    >
      {children}
    </button>
  );
}

function BrowserModeButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs transition-colors disabled:pointer-events-none disabled:opacity-35",
        active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function MetadataBlock({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (entries.length === 0) return null;
  return (
    <dl className="grid gap-x-4 gap-y-2 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 border-b border-glass-border/25 pb-2">
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/70">{labelize(key)}</dt>
          <dd className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-muted-foreground">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FilesBlock({ files }: { files: Array<Record<string, unknown>> }) {
  return (
    <div className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<FilePenLine className="h-3.5 w-3.5" />} title="Files" />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {files.map((file, index) => (
          <div key={`${String(file.filename ?? file.path ?? index)}-${index}`} className="py-2">
            <div className="flex min-w-0 items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-foreground">{String(file.filename ?? file.path ?? "file")}</span>
              {file.additions !== undefined ? <span className="font-mono text-success">+{String(file.additions)}</span> : null}
              {file.deletions !== undefined ? <span className="font-mono text-destructive">-{String(file.deletions)}</span> : null}
            </div>
            {typeof file.patch === "string" && file.patch.trim() ? (
              <pre className="mt-2 max-h-44 overflow-auto rounded-lg border border-glass-border/35 bg-background/70 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
                {file.patch}
              </pre>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function CommitsBlock({ commits }: { commits: Array<Record<string, unknown>> }) {
  return (
    <div className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<GitCommit className="h-3.5 w-3.5" />} title="Commits" />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {commits.map((commit, index) => (
          <div key={`${String(commit.sha ?? index)}-${index}`} className="py-2 text-xs">
            <div className="truncate font-medium text-foreground">{String(commit.message ?? commit.sha ?? "commit")}</div>
            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
              {String(commit.sha ?? "")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricBand({ items }: { items: Array<[string, number]> }) {
  return (
    <div className="grid grid-cols-4 gap-2">
      {items.map(([label, value]) => (
        <div key={label} className="border-b border-glass-border/25 pb-2">
          <div className="font-mono text-sm text-foreground">{formatNumber(value)}</div>
          <div className="truncate text-[10px] text-muted-foreground">{label}</div>
        </div>
      ))}
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
      {icon}
      <span>{title}</span>
    </div>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return <div className="flex min-h-[220px] items-center justify-center px-6 text-center text-xs text-muted-foreground">{text}</div>;
}

function EmptyList({ text }: { text: string }) {
  return <div className="py-2 text-[11px] text-muted-foreground">{text}</div>;
}

function PanelSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="grid grid-cols-4 gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border-b border-glass-border/25 pb-2">
            <div className="h-5 w-8 rounded bg-muted" />
            <div className="mt-1 h-3 w-14 rounded bg-muted/60" />
          </div>
        ))}
      </div>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-24 rounded bg-muted/60" />
        </div>
        <div className="mt-2 divide-y divide-glass-border/25">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <div className="h-3 w-full rounded bg-muted/50" />
              <div className="h-3 w-8 rounded bg-muted/30" />
            </div>
          ))}
        </div>
      </section>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-28 rounded bg-muted/60" />
        </div>
        <div className="mt-2 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 w-full rounded-lg border border-glass-border/25 bg-muted/20" />
          ))}
        </div>
      </section>
    </div>
  );
}

function mergeUsage(snapshot: SessionUsage | undefined, live: SessionUsage): SessionUsage {
  const base = snapshot ?? emptySessionUsage();
  const next = emptySessionUsage();
  for (const key of Object.keys(next) as Array<keyof SessionUsage>) {
    next[key] = {
      value: (base[key]?.value ?? 0) + (live[key]?.value ?? 0),
      estimated: Boolean(base[key]?.estimated || live[key]?.estimated),
    };
  }
  return next;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function labelize(value: string) {
  return value.replace(/_/g, " ");
}

function normalizeBrowserUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

const BROWSER_FORWARD_KEYS = new Set([
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

function isBrowserViewportControlTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, button, [contenteditable='true'], [data-browser-annotation-editor='true']",
    ),
  );
}

function browserViewport(element: HTMLElement | null, view?: SessionBrowserView): SessionBrowserViewport {
  const rect = element?.getBoundingClientRect();
  const width = Math.round(rect?.width || view?.viewport_width || 1024);
  const height = Math.round(rect?.height || view?.viewport_height || 720);
  return {
    width: Math.min(Math.max(width, 320), 2400),
    height: Math.min(Math.max(height, 240), 1800),
  };
}

function browserAnnotationCounts(annotations: SessionBrowserAnnotation[]) {
  return annotations.reduce<Record<string, number>>((counts, annotation) => {
    if (!annotation.node_id) return counts;
    counts[annotation.node_id] = (counts[annotation.node_id] || 0) + 1;
    return counts;
  }, {});
}

function browserAnnotationEditorStyle(bounds?: BrowserElementMetadata["bounds"], view?: SessionBrowserView) {
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

function localBrowserAnnotation({
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

function browserAnnotationToComposerAnnotation({
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

function browserTextSelectionToComposerAnnotation({
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

function normalizeBrowserElementMetadata(value: unknown, fallbackNodeId: string): BrowserElementMetadata | undefined {
  if (!value || typeof value !== "object") return undefined;
  const source = value as Record<string, unknown>;
  const nodeId = typeof source.node_id === "string" && source.node_id ? source.node_id : fallbackNodeId;
  if (!nodeId) return undefined;
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
    node_id: nodeId,
    role: typeof source.role === "string" ? source.role : undefined,
    tag: typeof source.tag === "string" ? source.tag : undefined,
    text: typeof source.text === "string" ? source.text : undefined,
    selector: typeof source.selector === "string" ? source.selector : undefined,
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

function normalizeBrowserTextSelection(value: unknown): BrowserTextSelectionMetadata | undefined {
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

function nextComposerAnnotationId() {
  const current = useChatStore.getState().composerAnnotations;
  return Math.max(0, ...current.map((annotation) => annotation.id)) + 1;
}

function browserAnnotationDisplayPath(url: string, title: string) {
  const host = browserHostname(url);
  if (host && title && title !== host) return `${title} · ${host}`;
  return host || title || "Browser";
}

function browserHostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

function browserMirrorSrcDoc(
  html: string,
  currentUrl: string,
  browserId: string,
) {
  const sanitizedHtml = sanitizeBrowserMirrorHtml(html);
  const base = `<base href="${escapeHtmlAttribute(currentUrl)}">`;
  const csp = [
    "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'",
    "img-src * data: blob:",
    "style-src * 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline' blob:",
    "font-src * data:",
    "frame-src * data: blob:",
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">`;
  const overlayStyle = `<style>
	html[data-pa-browser-mode="annotate"],
	html[data-pa-browser-mode="annotate"] body,
	html[data-pa-browser-mode="annotate"] * {
	  cursor: crosshair !important;
	}
	html[data-pa-browser-mode="action"],
	html[data-pa-browser-mode="action"] body,
	html[data-pa-browser-mode="action"] * {
	  cursor: pointer !important;
	}
	.pa-browser-inspect-target {
	  scroll-margin: 6px !important;
	}
	.pa-inspector-fill {
	  position: fixed !important;
	  z-index: 2147483646 !important;
	  box-sizing: border-box !important;
	  border: 2px solid #2296ff !important;
	  border-radius: var(--pa-inspector-radius, 3px) !important;
	  background: rgba(34, 150, 255, 0.18) !important;
	  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14), 0 0 0 1px rgba(34, 150, 255, 0.28) !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: left 110ms ease, top 110ms ease, width 110ms ease, height 110ms ease, border-radius 110ms ease, opacity 100ms ease !important;
	}
	.pa-inspector-fill.is-hidden {
	  opacity: 0 !important;
	}
	.pa-inspector-tooltip {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  left: 0;
	  top: 0;
	  min-width: 176px !important;
	  max-width: min(240px, calc(100vw - 16px)) !important;
	  border: 1px solid rgba(96, 165, 250, 0.32) !important;
	  border-radius: 10px !important;
	  background: rgba(9, 17, 31, 0.96) !important;
	  color: #e5eefb !important;
	  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
	  font: 500 11px/1.25 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  letter-spacing: 0 !important;
	  padding: 8px !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: opacity 100ms ease, transform 130ms ease !important;
	}
	.pa-inspector-tooltip.is-hidden {
	  opacity: 0 !important;
	}
	.pa-inspector-title,
	.pa-inspector-row {
	  display: grid !important;
	  grid-template-columns: 52px minmax(0, 1fr) !important;
	  gap: 8px !important;
	  align-items: center !important;
	}
	.pa-inspector-title {
	  margin-bottom: 5px !important;
	}
	.pa-inspector-tag {
	  display: inline-flex !important;
	  min-width: 0 !important;
	  justify-content: center !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.13) !important;
	  color: #f8fafc !important;
	  font-weight: 700 !important;
	  padding: 2px 6px !important;
	  text-transform: lowercase !important;
	}
	.pa-inspector-value {
	  min-width: 0 !important;
	  overflow: hidden !important;
	  text-overflow: ellipsis !important;
	  white-space: nowrap !important;
	}
	.pa-inspector-label {
	  color: #8ea1b8 !important;
	  font-weight: 600 !important;
	}
	.pa-selection-toolbar {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  display: flex !important;
	  align-items: center !important;
	  gap: 6px !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(10, 18, 32, 0.96) !important;
	  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28) !important;
	  padding: 4px !important;
	  pointer-events: auto !important;
	}
	.pa-selection-toolbar.is-hidden {
	  display: none !important;
	}
	.pa-selection-toolbar button {
	  border: 0 !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.16) !important;
	  color: #dbeafe !important;
	  cursor: pointer !important;
	  font: 600 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  padding: 7px 10px !important;
	}
	[data-pa-comment-count] {
	  outline: 1px solid rgba(249, 115, 22, 0.58) !important;
	  outline-offset: 2px !important;
	  box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.12) !important;
	}
	.pa-comment-anchor {
	  position: relative !important;
	}
	.pa-comment-marker {
	  position: absolute !important;
	  z-index: 2147483647 !important;
	  top: -9px !important;
	  right: -9px !important;
	  display: inline-grid !important;
	  min-width: 18px !important;
	  height: 18px !important;
	  place-items: center !important;
	  border: 1px solid rgba(255, 255, 255, 0.72) !important;
	  border-radius: 999px !important;
	  background: #f97316 !important;
	  color: #111827 !important;
	  font: 700 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22) !important;
	  pointer-events: none !important;
	}
	</style>`;
 const script = `<script>
	(() => {
	  const browserId = ${JSON.stringify(browserId)};
	  let mode = "browse";
	  let annotationCounts = {};
	  let selectedNodeId = "";
	  const interactiveSelector = "a[href],button,input,textarea,select,label,summary,[role='button'],[role='link'],[role='menuitem'],[role='tab'],[role='checkbox'],[role='radio'],[contenteditable='true']";
	  const inspectableSelector = [
	    interactiveSelector,
	    "form,[role],h1,h2,h3,h4,h5,h6,p,li,article,section,main,nav,header,footer,div,span,img,svg,canvas"
	  ].join(",");
	  const ignoredTags = new Set(["HTML", "BODY", "HEAD", "SCRIPT", "STYLE", "META", "LINK", "BASE", "TITLE", "NOSCRIPT", "TEMPLATE"]);
	  const voidTags = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"]);
	  let activeTarget = null;
	  let highlightOverlay = null;
	  let tooltip = null;
	  let selectionToolbar = null;
	  let lastSelectionMetadata = null;
	  let pendingMouse = null;
	  let hoverFrame = 0;

	  const applyMode = (nextMode) => {
	    mode = nextMode === "annotate" || nextMode === "action" ? nextMode : "browse";
	    document.documentElement.setAttribute("data-pa-browser-mode", mode);
	    if (mode === "browse") clearHover();
	  };

	  const send = (url) => {
	    if (!url) return;
	    window.parent.postMessage({ type: "personagent-session-browser:navigate", browserId, url }, "*");
	  };
	  const sendElement = (element) => {
	    if (!element) return;
	    const metadata = elementMetadata(element);
	    if (!metadata.node_id) return;
	    window.parent.postMessage({
	      type: "personagent-session-browser:element",
	      browserId,
	      nodeId: metadata.node_id,
	      element: metadata,
	    }, "*");
	  };
	  const sendElementAction = (nodeId, action) => {
	    if (!nodeId) return;
	    window.parent.postMessage({ type: "personagent-session-browser:element-action", browserId, nodeId, action }, "*");
	  };
	  const sendTextSelection = (selection) => {
	    if (!selection || !selection.text) return;
	    window.parent.postMessage({
	      type: "personagent-session-browser:text-selection",
	      browserId,
	      selection,
	    }, "*");
	  };
	  const cssEscape = (value) => {
	    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
	    return String(value).replace(/["\\\\]/g, "\\\\$&");
	  };
	  const selectedTarget = () => {
	    if (!selectedNodeId) return null;
	    return document.querySelector('[data-pa-node-id="' + cssEscape(selectedNodeId) + '"]');
	  };
	  const trimText = (value, limit) => String(value || "").replace(/\\s+/g, " ").trim().slice(0, limit);
	  const elementText = (element) => {
	    if (!element || !element.getAttribute) return "";
	    const aria = element.getAttribute("aria-label") || element.getAttribute("alt") || element.getAttribute("title");
	    if (aria) return trimText(aria, 180);
	    const tag = element.tagName;
	    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
	      return trimText(element.value || element.getAttribute("placeholder") || element.getAttribute("name") || "", 180);
	    }
	    return trimText(element.innerText || element.textContent || "", 180);
	  };
	  const roleFor = (element) => {
	    if (!element || !element.getAttribute) return "element";
	    const explicitRole = element.getAttribute("role");
	    if (explicitRole) return explicitRole;
	    const tag = element.tagName.toLowerCase();
	    if (tag === "a") return "link";
	    if (tag === "button") return "button";
	    if (["input", "textarea", "select"].includes(tag)) return "field";
	    if (/^h[1-6]$/.test(tag)) return "heading";
	    return tag;
	  };
	  const stableHash = (value) => {
	    let hash = 2166136261;
	    const text = String(value || "");
	    for (let index = 0; index < text.length; index += 1) {
	      hash ^= text.charCodeAt(index);
	      hash = Math.imul(hash, 16777619);
	    }
	    return (hash >>> 0).toString(36);
	  };
	  const cssPath = (element) => {
	    if (!element || !element.tagName) return "";
	    if (element.id) return "#" + cssEscape(element.id);
	    const parts = [];
	    let node = element;
	    while (node && node.nodeType === 1 && node !== document.documentElement) {
	      const tag = node.tagName.toLowerCase();
	      if (node.id) {
	        parts.unshift(tag + "#" + cssEscape(node.id));
	        break;
	      }
	      let nth = 1;
	      let sibling = node;
	      while ((sibling = sibling.previousElementSibling)) {
	        if (sibling.tagName === node.tagName) nth += 1;
	      }
	      parts.unshift(tag + ":nth-of-type(" + nth + ")");
	      if (node.parentElement === document.body) break;
	      node = node.parentElement;
	    }
	    return parts.join(" > ");
	  };
	  const ensureNodeId = (element) => {
	    if (!element || !element.setAttribute) return "";
	    const existing = element.getAttribute("data-pa-node-id");
	    if (existing) return existing;
	    const signature = [cssPath(element), roleFor(element), elementText(element).slice(0, 90)].join("|");
	    const nodeId = "pa_dom_" + stableHash(signature);
	    element.setAttribute("data-pa-node-id", nodeId);
	    return nodeId;
	  };
	  const canContainMarker = (element) => {
	    if (!element || !element.tagName) return false;
	    return !voidTags.has(element.tagName);
	  };
	  const boundsFor = (element) => {
	    const rect = element.getBoundingClientRect();
	    return {
	      x: Math.round(rect.left),
	      y: Math.round(rect.top),
	      width: Math.round(rect.width),
	      height: Math.round(rect.height),
	    };
	  };
	  const elementMetadata = (element) => {
	    const tag = element.tagName.toLowerCase();
	    const style = window.getComputedStyle(element);
	    const form = tag === "form" ? element : element.closest("form");
	    const href = tag === "a" && element.getAttribute("href")
	      ? new URL(element.getAttribute("href"), document.baseURI).href
	      : undefined;
	    const formAction = form && form.getAttribute("action")
	      ? new URL(form.getAttribute("action"), document.baseURI).href
	      : undefined;
	    return {
	      node_id: ensureNodeId(element),
	      role: roleFor(element),
	      tag,
	      text: elementText(element),
	      selector: cssPath(element),
	      href,
	      name: element.getAttribute("name") || element.getAttribute("aria-label") || undefined,
	      input_type: tag === "input" ? String(element.getAttribute("type") || "text").toLowerCase() : undefined,
	      form_method: form ? String(form.getAttribute("method") || "get").toLowerCase() : undefined,
	      form_action: formAction,
	      bounds: boundsFor(element),
	      visible: true,
	      color: style.color,
	      background: style.backgroundColor,
	      display: style.display,
	      position: style.position,
	      padding: trimText(style.padding, 80),
	      margin: trimText(style.margin, 80),
	      radius: trimText(style.borderRadius, 80),
	      font: trimText(style.fontSize + " " + style.fontFamily, 96),
	    };
	  };
	  const isVisibleCandidate = (element) => {
	    if (!element || !element.tagName || ignoredTags.has(element.tagName)) return false;
	    if (element.closest && element.closest(".pa-inspector-tooltip, .pa-inspector-fill, .pa-selection-toolbar, .pa-comment-marker")) return false;
	    const rect = element.getBoundingClientRect();
	    if (rect.width < 4 || rect.height < 4) return false;
	    const style = window.getComputedStyle(element);
	    if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity || "1") === 0) return false;
	    return true;
	  };
	  const containsPoint = (element, x, y) => {
	    const rect = element.getBoundingClientRect();
	    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
	  };
	  const normalizeCandidate = (element, x, y) => {
	    if (!isVisibleCandidate(element)) return null;
	    const interactive = element.closest ? element.closest(interactiveSelector) : null;
	    if (mode === "action" && interactive && interactive !== element && isVisibleCandidate(interactive) && containsPoint(interactive, x, y)) {
	      return interactive;
	    }
	    if (["PATH", "USE", "G"].includes(element.tagName)) {
	      const svg = element.closest ? element.closest("svg") : null;
	      if (svg && isVisibleCandidate(svg) && containsPoint(svg, x, y)) return svg;
	    }
	    return element;
	  };
	  const candidateScore = (element, x, y) => {
	    const rect = element.getBoundingClientRect();
	    const area = rect.width * rect.height;
	    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
	    const centerDistance = Math.hypot(x - (rect.left + rect.width / 2), y - (rect.top + rect.height / 2));
	    const interactive = element.matches && element.matches(interactiveSelector);
	    const semantic = element.matches && element.matches("form,[role],h1,h2,h3,h4,h5,h6,p,li,article,section,main,nav,header,footer");
	    const text = elementText(element);
	    let depth = 0;
	    let parent = element.parentElement;
	    while (parent && parent !== document.body && depth < 24) {
	      depth += 1;
	      parent = parent.parentElement;
	    }
	    let score = Math.log(area + 1) * 12 + Math.min(centerDistance / 4, 100) - Math.min(depth * 2, 48);
	    if (interactive) score -= mode === "action" ? 160 : 12;
	    if (semantic) score -= mode === "action" ? 35 : 6;
	    if (text) score -= 14;
	    if (area > viewportArea * 0.65 && !interactive) score += 160;
	    if (area < 24) score += 30;
	    if (mode === "annotate" && area > viewportArea * 0.18 && !interactive) score += 70;
	    return score;
	  };
	  const targetFromPoint = (x, y) => {
	    const elements = typeof document.elementsFromPoint === "function"
	      ? document.elementsFromPoint(x, y)
	      : [document.elementFromPoint(x, y)].filter(Boolean);
	    const seen = new Set();
	    const candidates = [];
	    for (const raw of elements) {
	      const candidate = normalizeCandidate(raw, x, y);
	      if (!candidate || seen.has(candidate)) continue;
	      seen.add(candidate);
	      candidates.push(candidate);
	    }
	    if (!candidates.length) return null;
	    candidates.sort((left, right) => candidateScore(left, x, y) - candidateScore(right, x, y));
	    return candidates[0];
	  };
	  const createTooltip = () => {
	    if (tooltip) return tooltip;
	    tooltip = document.createElement("div");
	    tooltip.className = "pa-inspector-tooltip is-hidden";
	    (document.body || document.documentElement).appendChild(tooltip);
	    return tooltip;
	  };
	  const createHighlightOverlay = () => {
	    if (highlightOverlay) return highlightOverlay;
	    highlightOverlay = document.createElement("div");
	    highlightOverlay.className = "pa-inspector-fill is-hidden";
	    (document.body || document.documentElement).appendChild(highlightOverlay);
	    return highlightOverlay;
	  };
	  const positionHighlightOverlay = (element) => {
	    const overlay = createHighlightOverlay();
	    if (!element) {
	      overlay.classList.add("is-hidden");
	      return;
	    }
	    const rect = element.getBoundingClientRect();
	    const style = window.getComputedStyle(element);
	    overlay.style.left = Math.round(rect.left) + "px";
	    overlay.style.top = Math.round(rect.top) + "px";
	    overlay.style.width = Math.round(rect.width) + "px";
	    overlay.style.height = Math.round(rect.height) + "px";
	    overlay.style.setProperty("--pa-inspector-radius", style.borderRadius && style.borderRadius !== "0px" ? style.borderRadius : "2px");
	    overlay.classList.remove("is-hidden");
	  };
	  const appendTooltipRow = (root, label, value, title) => {
	    if (!value) return;
	    const row = document.createElement("div");
	    row.className = title ? "pa-inspector-title" : "pa-inspector-row";
	    const labelNode = document.createElement("span");
	    labelNode.className = title ? "pa-inspector-tag" : "pa-inspector-label";
	    labelNode.textContent = label;
	    const valueNode = document.createElement("span");
	    valueNode.className = "pa-inspector-value";
	    valueNode.textContent = value;
	    row.appendChild(labelNode);
	    row.appendChild(valueNode);
	    root.appendChild(row);
	  };
	  const isTransparentColor = (value) => {
	    const normalized = String(value || "").replace(/\\s+/g, "").toLowerCase();
	    return !normalized || normalized === "transparent" || normalized === "rgba(0,0,0,0)";
	  };
	  const compactColor = (value) => String(value || "").replace(/\\s+/g, "");
	  const compactCss = (metadata) => {
	    const values = [
	      metadata.display,
	      metadata.position && metadata.position !== "static" ? metadata.position : "",
	      metadata.radius && metadata.radius !== "0px" ? "r " + metadata.radius : "",
	    ].filter(Boolean);
	    return values.join(" · ");
	  };
	  const compactColors = (metadata) => {
	    const values = [compactColor(metadata.color)];
	    if (!isTransparentColor(metadata.background)) values.push(compactColor(metadata.background));
	    return values.filter(Boolean).join(" / ");
	  };
	  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
	  const tooltipPositionFor = (element, width, height) => {
	    const rect = element.getBoundingClientRect();
	    const margin = 8;
	    const gap = 8;
	    const viewportWidth = window.innerWidth;
	    const viewportHeight = window.innerHeight;
	    const centerTop = clamp(rect.top + rect.height / 2 - height / 2, margin, Math.max(margin, viewportHeight - height - margin));
	    const centerLeft = clamp(rect.left + rect.width / 2 - width / 2, margin, Math.max(margin, viewportWidth - width - margin));
	    const candidates = [];
	    if (viewportWidth - rect.right >= width + gap + margin) candidates.push({ left: rect.right + gap, top: centerTop });
	    if (rect.left >= width + gap + margin) candidates.push({ left: rect.left - width - gap, top: centerTop });
	    if (viewportHeight - rect.bottom >= height + gap + margin) candidates.push({ left: centerLeft, top: rect.bottom + gap });
	    if (rect.top >= height + gap + margin) candidates.push({ left: centerLeft, top: rect.top - height - gap });
	    if (candidates.length) return candidates[0];
	    return {
	      left: clamp(rect.right + gap, margin, Math.max(margin, viewportWidth - width - margin)),
	      top: clamp(rect.bottom + gap, margin, Math.max(margin, viewportHeight - height - margin)),
	    };
	  };
	  const showTooltip = (element, x, y) => {
	    const root = createTooltip();
	    const metadata = elementMetadata(element);
	    root.replaceChildren();
	    appendTooltipRow(
	      root,
	      metadata.tag || "node",
	      metadata.role + " · " + metadata.bounds.width + "x" + metadata.bounds.height,
	      true
	    );
	    appendTooltipRow(root, "CSS", compactCss(metadata));
	    appendTooltipRow(root, "Color", compactColors(metadata));
	    const width = Math.min(root.offsetWidth || 192, window.innerWidth - 16);
	    const height = Math.min(root.offsetHeight || 72, window.innerHeight - 16);
	    const position = tooltipPositionFor(element, width, height);
	    root.style.setProperty("left", Math.round(position.left) + "px", "important");
	    root.style.setProperty("top", Math.round(position.top) + "px", "important");
	    root.style.setProperty("transform", "translate3d(0, 0, 0)", "important");
	    root.classList.remove("is-hidden");
	  };
	  const hideTooltip = () => {
	    if (tooltip) tooltip.classList.add("is-hidden");
	  };
	  const setActiveTarget = (element, x, y) => {
	    if (activeTarget === element) {
	      if (element) positionHighlightOverlay(element);
	      if (element) showTooltip(element, x, y);
	      return;
	    }
	    if (activeTarget) activeTarget.classList.remove("pa-browser-inspect-target");
	    activeTarget = element;
	    if (activeTarget) {
	      ensureNodeId(activeTarget);
	      activeTarget.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(activeTarget);
	      showTooltip(activeTarget, x, y);
	    } else {
	      positionHighlightOverlay(null);
	      hideTooltip();
	    }
	  };
	  const scheduleHover = (event) => {
	    if (mode !== "annotate" && mode !== "action") return;
	    pendingMouse = { x: event.clientX, y: event.clientY };
	    if (hoverFrame) return;
	    hoverFrame = window.requestAnimationFrame(() => {
	      hoverFrame = 0;
	      if (!pendingMouse) return;
	      const target = targetFromPoint(pendingMouse.x, pendingMouse.y);
	      setActiveTarget(target, pendingMouse.x, pendingMouse.y);
	    });
	  };
	  const clearHover = () => {
	    pendingMouse = null;
	    if (activeTarget) activeTarget.classList.remove("pa-browser-inspect-target");
	    activeTarget = null;
	    const selected = mode === "annotate" ? selectedTarget() : null;
	    if (selected) {
	      selected.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(selected);
	    } else {
	      positionHighlightOverlay(null);
	    }
	    hideTooltip();
	  };
	  const indexAnnotatableElements = () => {
	    let indexed = 0;
	    for (const element of document.querySelectorAll(inspectableSelector)) {
	      if (indexed >= 1600) break;
	      if (!isVisibleCandidate(element)) continue;
	      ensureNodeId(element);
	      indexed += 1;
	    }
	  };
	  const applyAnnotationMarkers = () => {
	    indexAnnotatableElements();
	    for (const marker of document.querySelectorAll(".pa-comment-marker")) marker.remove();
	    for (const marked of document.querySelectorAll("[data-pa-comment-count]")) {
	      marked.removeAttribute("data-pa-comment-count");
	      marked.classList.remove("pa-comment-anchor");
	    }
	    for (const nodeId of Object.keys(annotationCounts)) {
	      const element = document.querySelector('[data-pa-node-id="' + cssEscape(nodeId) + '"]');
	      if (!element) continue;
	      const count = String(annotationCounts[nodeId]);
	      element.setAttribute("data-pa-comment-count", count);
	      if (!canContainMarker(element) || element.querySelector(":scope > .pa-comment-marker")) continue;
	      element.classList.add("pa-comment-anchor");
	      const marker = document.createElement("span");
	      marker.className = "pa-comment-marker";
	      marker.textContent = count;
	      element.appendChild(marker);
	    }
	    const selected = mode === "annotate" ? selectedTarget() : null;
	    if (!activeTarget && selected) {
	      selected.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(selected);
	    }
	  };
	  const selectionElement = (selection) => {
	    if (!selection || selection.rangeCount === 0) return null;
	    const range = selection.getRangeAt(0);
	    let node = range.commonAncestorContainer;
	    if (node && node.nodeType !== 1) node = node.parentElement;
	    return node && node.nodeType === 1 ? node : null;
	  };
	  const selectionOffsets = (element, range, selectedText) => {
	    if (!element || !range) return {};
	    try {
	      const prefixRange = document.createRange();
	      prefixRange.selectNodeContents(element);
	      prefixRange.setEnd(range.startContainer, range.startOffset);
	      const start = prefixRange.toString().length;
	      return { start_offset: start, end_offset: start + selectedText.length };
	    } catch {
	      return {};
	    }
	  };
	  const selectionMetadata = () => {
	    const selection = window.getSelection();
	    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
	    const text = trimText(selection.toString(), 2000);
	    if (!text) return null;
	    const range = selection.getRangeAt(0);
	    const rect = range.getBoundingClientRect();
	    if (!rect || rect.width < 2 || rect.height < 2) return null;
	    const element = selectionElement(selection);
	    const metadata = element ? elementMetadata(element) : null;
	    return {
	      text,
	      node_id: metadata ? metadata.node_id : undefined,
	      selector: metadata ? metadata.selector : undefined,
	      role: metadata ? metadata.role : undefined,
	      tag: metadata ? metadata.tag : undefined,
	      ...selectionOffsets(element, range, text),
	      bounds: {
	        x: Math.round(rect.left),
	        y: Math.round(rect.top),
	        width: Math.round(rect.width),
	        height: Math.round(rect.height),
	      },
	    };
	  };
	  const createSelectionToolbar = () => {
	    if (selectionToolbar) return selectionToolbar;
	    selectionToolbar = document.createElement("div");
	    selectionToolbar.className = "pa-selection-toolbar is-hidden";
	    const button = document.createElement("button");
	    button.type = "button";
	    button.textContent = "Send to Agent";
	    button.addEventListener("click", (event) => {
	      event.preventDefault();
	      event.stopPropagation();
	      if (lastSelectionMetadata) sendTextSelection(lastSelectionMetadata);
	      hideSelectionToolbar();
	      const selection = window.getSelection();
	      if (selection) selection.removeAllRanges();
	    });
	    selectionToolbar.appendChild(button);
	    (document.body || document.documentElement).appendChild(selectionToolbar);
	    return selectionToolbar;
	  };
	  const hideSelectionToolbar = () => {
	    if (selectionToolbar) selectionToolbar.classList.add("is-hidden");
	  };
	  const showSelectionToolbar = () => {
	    const metadata = selectionMetadata();
	    if (!metadata) {
	      lastSelectionMetadata = null;
	      hideSelectionToolbar();
	      return;
	    }
	    lastSelectionMetadata = metadata;
	    const toolbar = createSelectionToolbar();
	    const margin = 10;
	    const width = toolbar.offsetWidth || 120;
	    const height = toolbar.offsetHeight || 34;
	    const left = Math.min(Math.max(metadata.bounds.x, margin), Math.max(margin, window.innerWidth - width - margin));
	    const top = Math.min(Math.max(metadata.bounds.y - height - 8, margin), Math.max(margin, window.innerHeight - height - margin));
	    toolbar.style.left = Math.round(left) + "px";
	    toolbar.style.top = Math.round(top) + "px";
	    toolbar.classList.remove("is-hidden");
	  };
	  const formDataForSubmit = (form, submitter) => {
	    try {
	      return submitter ? new FormData(form, submitter) : new FormData(form);
	    } catch {
	      return new FormData(form);
	    }
	  };
	  const submitForm = (form, submitter) => {
	    if (!form || !form.getAttribute) return false;
	    const method = String(form.getAttribute("method") || "get").toLowerCase();
	    if (method !== "get") {
	      const mappedForm = form.closest("[data-pa-node-id]");
	      if (mappedForm) sendElementAction(mappedForm.getAttribute("data-pa-node-id"), "submit");
	      return true;
	    }
	    const url = new URL(form.getAttribute("action") || document.baseURI, document.baseURI);
	    const data = formDataForSubmit(form, submitter);
	    for (const [key, value] of data.entries()) {
	      if (key) url.searchParams.append(key, String(value));
	    }
	    send(url.href);
	    return true;
	  };
	  if (document.readyState === "loading") {
	    document.addEventListener("DOMContentLoaded", applyAnnotationMarkers, { once: true });
	  } else {
	    applyAnnotationMarkers();
	  }
	  document.addEventListener("mousemove", scheduleHover, true);
	  document.addEventListener("mouseleave", clearHover, true);
	  document.addEventListener("selectionchange", () => window.setTimeout(showSelectionToolbar, 0));
	  document.addEventListener("mouseup", () => window.setTimeout(showSelectionToolbar, 0), true);
	  window.addEventListener("blur", () => {
	    clearHover();
	    hideSelectionToolbar();
	  });
	  window.addEventListener("scroll", () => {
	    if (activeTarget) positionHighlightOverlay(activeTarget);
	    showSelectionToolbar();
	  }, true);
	  window.addEventListener("message", (event) => {
	    const data = event.data || {};
	    if (!data || data.browserId !== browserId || data.type !== "personagent-session-browser:state") return;
	    applyMode(data.mode);
	    annotationCounts = data.annotationCounts && typeof data.annotationCounts === "object" ? data.annotationCounts : {};
	    selectedNodeId = typeof data.selectedNodeId === "string" ? data.selectedNodeId : "";
	    applyAnnotationMarkers();
	    if (!activeTarget && !selectedNodeId) positionHighlightOverlay(null);
	  });
	  window.parent.postMessage({ type: "personagent-session-browser:ready", browserId }, "*");
	  document.addEventListener("click", (event) => {
	    if (event.target && event.target.closest && event.target.closest(".pa-selection-toolbar")) {
	      return;
	    }
	    if (mode === "annotate" || mode === "action") {
	      const target = activeTarget && containsPoint(activeTarget, event.clientX, event.clientY)
	        ? activeTarget
	        : targetFromPoint(event.clientX, event.clientY);
	      if (target) {
	        event.preventDefault();
	        event.stopPropagation();
	        sendElement(target);
	        return;
	      }
	    }
	    const submitter = event.target && event.target.closest
	      ? event.target.closest("button, input[type='submit'], input[type='image']")
	      : null;
	    const submitterType = submitter ? String(submitter.getAttribute("type") || "submit").toLowerCase() : "";
	    const form = submitter && (submitter.form || submitter.closest("form"));
	    if (form && (!submitterType || submitterType === "submit" || submitterType === "image")) {
	      event.preventDefault();
	      event.stopPropagation();
	      submitForm(form, submitter);
	      return;
	    }
	    const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
	    if (!anchor) return;
	    event.preventDefault();
	    send(new URL(anchor.getAttribute("href"), document.baseURI).href);
	  }, true);
	  document.addEventListener("keydown", (event) => {
	    if (event.defaultPrevented || event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
	    const target = event.target;
	    if (!target || !target.form || target.tagName === "TEXTAREA") return;
	    event.preventDefault();
	    event.stopPropagation();
	    submitForm(target.form, null);
	  }, true);
	  document.addEventListener("submit", (event) => {
	    const form = event.target;
	    if (!form || !form.getAttribute) return;
	    event.preventDefault();
	    submitForm(form, null);
	  }, true);
	})();
	</script>`;
  if (/<head(\s[^>]*)?>/i.test(sanitizedHtml)) {
    return sanitizedHtml.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${meta}${base}${overlayStyle}${script}`);
  }
  return `${meta}${base}${overlayStyle}${script}${sanitizedHtml}`;
}

function sanitizeBrowserMirrorHtml(html: string) {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, "")
    .replace(/<script\b[^>]*\/?>/gi, "")
    .replace(/<link\b(?=[^>]*\brel=["']?modulepreload\b)[^>]*>/gi, "")
    .replace(/<link\b(?=[^>]*\brel=["']?preload\b)(?=[^>]*\bas=["']?(?:script|worker)\b)[^>]*>/gi, "");
}

function escapeHtmlAttribute(value: string) {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function scriptJson(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

function browserCssLabel(value?: string) {
  if (value === "pixel") return "Pixel render";
  if (value === "original_embedded") return "Original + Embedded CSS";
  if (value === "embedded") return "Embedded CSS";
  if (value === "fallback_html") return "Fallback HTML";
  return "Original CSS";
}

function browserCssBadgeClass(value?: string) {
  if (value === "fallback_html") return "border-warning/40 bg-warning/10 text-warning";
  if (value === "original_embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "pixel") return "border-success/35 bg-success/10 text-success";
  return "border-glass-border/35 bg-card/70 text-muted-foreground";
}

function selectedElementLabel(element: SessionBrowserElement | undefined, nodeId: string) {
  if (!element) return nodeId;
  const role = element.role || element.tag || "element";
  const text = element.text ? ` · ${element.text.slice(0, 90)}` : "";
  return `${role}${text}`;
}
