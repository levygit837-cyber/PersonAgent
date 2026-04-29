import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode, type WheelEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
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
  connectSessionBrowserCooperation,
  createSessionBrowserAnnotation,
  getSessionBrowserView,
  getSessionPanel,
  getSessionProjectDetail,
  ingestSessionBrowserEvents,
  keySessionBrowser,
  navigateSessionBrowser,
  scrollSessionBrowser,
  setSessionBrowserCooperation,
  type SessionBrowserAnnotation,
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserCooperationWsEvent,
  type SessionBrowserElement,
  type SessionBrowserTimelineEvent,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../api/client";
import { cn } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore, type ComposerAnnotation } from "../../stores/chat-store";
import type {
  ChangedFile,
  ChatMessageUi,
  ProjectItem,
  SessionPanelSnapshot,
  SessionSource,
  SessionUsage,
  SessionUsageMetric,
  ToolBlockStatus,
  ToolBlockUi,
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
import { readSessionPanelCache, persistSessionPanelCache } from "./session-panel/cache";
import { browserMirrorSrcDoc } from "./session-panel/browser-mirror";
export { SESSION_PANEL_CACHE_STORAGE_KEY } from "./session-panel/cache";
export { browserMirrorSrcDoc, sanitizeBrowserMirrorHtml } from "./session-panel/browser-mirror";

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
  mode: "browse" | "annotate";
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

type BrowserTracingTab = "timeline" | "raw" | "state" | "agent" | "proposals";

type BrowserGhostTrace = {
  x: number;
  y: number;
  effect: string;
  visible: boolean;
  nonce: number;
};

type BrowserToolVisualEffect = "map" | "click" | "type" | "scroll" | "extract" | "highlight";

type BrowserToolVisual = {
  id: string;
  toolName: string;
  status: ToolBlockStatus;
  effect: BrowserToolVisualEffect;
  browserId?: string;
  pageId?: string;
  windowId?: string;
  url?: string;
  nodeId?: string;
  target?: BrowserElementMetadata;
  elements: BrowserElementMetadata[];
  coordinates?: { x: number; y: number };
  data: Record<string, unknown>;
};

const summaryTab: BrowserTab = {
  id: "summary",
  title: "Summary",
  closeable: false,
};

const SESSION_PANEL_STREAMING_REFETCH_MS = 1_500;
const SESSION_PANEL_STALE_MS = 5 * 60_000;
const BROWSER_LOADING_MESSAGES = [
  "Preparando o ambiente...",
  "Baixando HTML da pagina...",
  "Aplicando CSS original...",
  "Estilizando seu site...",
  "Mapeando elementos clicaveis...",
];
let composerAnnotationSequence = 0;

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

function browserCooperationFromView(view?: SessionBrowserView) {
  return view?.cooperation ?? view?.workspace_state?.cooperation ?? view?.browser_snapshot?.cooperation;
}

function isBrowserCooperationEvent(value: unknown): value is SessionBrowserCooperationEvent {
  return Boolean(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      typeof (value as { kind?: unknown }).kind === "string",
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
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const paneWorkspaceRoot = useChatStore((state) => state.workspaceRoot);
  const workspaceRoot = paneWorkspaceRoot || selectedWorkspace;
  const conversationId = useChatStore((state) => state.conversationId);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const liveUsage = useChatStore((state) => state.liveSessionUsage);
  const chatMessages = useChatStore((state) => state.messages);
  const addComposerAnnotation = useChatStore((state) => state.addComposerAnnotation);
  const approvePendingTool = useChatStore((state) => state.approvePendingTool);
  const rejectPendingTool = useChatStore((state) => state.rejectPendingTool);
  const queryClient = useQueryClient();
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([summaryTab]);
  const [activeTabId, setActiveTabId] = useState(summaryTab.id);
  const browserRequestIdsRef = useRef<Record<string, number>>({});
  const browserWorkspacePersistKeysRef = useRef<Record<string, string>>({});
  const cooperationSocketsRef = useRef<Record<string, WebSocket>>({});
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
    refetchInterval: isStreaming ? SESSION_PANEL_STREAMING_REFETCH_MS : false,
    refetchIntervalInBackground: true,
    staleTime: SESSION_PANEL_STALE_MS,
    refetchOnWindowFocus: false,
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
  const browserToolVisual = useMemo(() => latestBrowserToolVisual(chatMessages), [chatMessages]);
  const appliedBrowserToolViewRef = useRef("");

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
          view.can_capture || view.render_mode === "html_mirror" || view.render_mode === "computed_html" || view.render_mode === "pixel"
            ? undefined
            : view.screenshot_error || "Browser rendering is unavailable.",
        view,
      };
    });
  };

  useEffect(() => {
    if (!browserToolVisual || browserToolVisual.status !== "completed") return;
    const view = browserViewFromToolVisual(browserToolVisual);
    if (!view) return;
    const matchingTab = tabs.find((tab) => {
      if (!isBrowserTab(tab)) return false;
      return browserToolVisualAppliesToBrowser(browserToolVisual, tab.browser ?? createEmptyBrowserState(tab.id));
    });
    if (!matchingTab) return;
    const applyKey = [
      browserToolVisual.id,
      view.url || "",
      view.title || "",
      view.active_tab_id || "",
      browserToolVisual.data.image_data ? String(browserToolVisual.data.image_data).length : "",
    ].join(":");
    if (appliedBrowserToolViewRef.current === applyKey) return;
    appliedBrowserToolViewRef.current = applyKey;
    applyBrowserView(matchingTab.id, view, { addHistory: browserToolVisual.effect !== "map" });
  }, [browserToolVisual, tabs]);

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
            onBrowserElementActivate={(nodeId, viewport) => void activateBrowserElement(activeTab.id, nodeId, viewport)}
            onBrowserCooperationModeChange={(mode) => void setBrowserCooperationMode(activeTab.id, mode)}
            onBrowserEvents={(events) => void recordBrowserEvents(activeTab.id, events)}
            onBrowserProposalDecision={(proposal, decision) => void decideBrowserProposal(activeTab.id, proposal, decision)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
            browserToolVisual={browserToolVisual}
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
            onBrowserElementActivate={(nodeId, viewport) => void activateBrowserElement(activeTab.id, nodeId, viewport)}
            onBrowserCooperationModeChange={(mode) => void setBrowserCooperationMode(activeTab.id, mode)}
            onBrowserEvents={(events) => void recordBrowserEvents(activeTab.id, events)}
            onBrowserProposalDecision={(proposal, decision) => void decideBrowserProposal(activeTab.id, proposal, decision)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
            browserToolVisual={browserToolVisual}
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
  browserToolVisual,
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
  onBrowserElementActivate,
  onBrowserCooperationModeChange,
  onBrowserEvents,
  onBrowserProposalDecision,
  canPersistBrowserWorkspace,
}: {
  tab: BrowserTab;
  browserToolVisual?: BrowserToolVisual;
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
  onBrowserElementActivate: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  onBrowserCooperationModeChange: (mode: SessionBrowserCooperationMode | "off") => void;
  onBrowserEvents: (events: SessionBrowserCooperationEvent[]) => void;
  onBrowserProposalDecision: (
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => void;
  canPersistBrowserWorkspace: boolean;
}) {
  if (isBrowserTab(tab)) {
    return (
      <BrowserTabContent
        browser={tab.browser ?? createEmptyBrowserState(tab.id)}
        browserToolVisual={browserToolVisual}
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
        onBrowserElementActivate={onBrowserElementActivate}
        onCooperationModeChange={onBrowserCooperationModeChange}
        onBrowserEvents={onBrowserEvents}
        onProposalDecision={onBrowserProposalDecision}
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
  browserToolVisual,
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
  onBrowserElementActivate,
  onCooperationModeChange,
  onBrowserEvents,
  onProposalDecision,
  canPersistWorkspace,
}: {
  browser: BrowserState;
  browserToolVisual?: BrowserToolVisual;
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
  onBrowserElementActivate: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  onCooperationModeChange: (mode: SessionBrowserCooperationMode | "off") => void;
  onBrowserEvents: (events: SessionBrowserCooperationEvent[]) => void;
  onProposalDecision: (
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => void;
  canPersistWorkspace: boolean;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const annotationInputRef = useRef<HTMLTextAreaElement | null>(null);
  const requestedInitialViewRef = useRef(false);
  const lastBrowserIdRef = useRef(browser.browserId);
  const [mirrorUrl, setMirrorUrl] = useState("");
  const [pixelHoverNodeId, setPixelHoverNodeId] = useState<string | null>(null);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const [tracingOpen, setTracingOpen] = useState(false);
  const [tracingTab, setTracingTab] = useState<BrowserTracingTab>("timeline");
  const [ghostTrace, setGhostTrace] = useState<BrowserGhostTrace>({
    x: 20,
    y: 20,
    effect: "highlight",
    visible: false,
    nonce: 0,
  });
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
  const backendTabs = browser.view?.tabs || browser.view?.browser_snapshot?.tabs || [];
  const visibleBrowserToolVisual = browserToolVisualAppliesToBrowser(browserToolVisual, browser)
    ? browserToolVisual
    : undefined;
  const cooperation = browserCooperationFromView(browser.view);
  const cooperationEnabled = Boolean(cooperation?.enabled);
  const cooperationMode = cooperationEnabled ? cooperation?.mode ?? cooperation?.agent_control ?? "observe_only" : "off";
  const rawEvents = useMemo(() => recordArray(cooperation?.raw_events), [cooperation?.raw_events]);
  const usefulTimeline = useMemo(() => recordArray(cooperation?.useful_timeline), [cooperation?.useful_timeline]);
  const recentUserEvents = useMemo(() => recordArray(cooperation?.recent_user_events), [cooperation?.recent_user_events]);
  const recentAgentEvents = useMemo(() => recordArray(cooperation?.recent_agent_events), [cooperation?.recent_agent_events]);
  const pendingProposals = useMemo(
    () =>
      recordArray(cooperation?.pending_action_proposals).filter(
        (proposal) => String(proposal.status ?? "awaiting_approval") === "awaiting_approval",
      ),
    [cooperation?.pending_action_proposals],
  );
  const activeProposal = pendingProposals[0];
  const activeProposalTarget = activeProposal ? recordValue(activeProposal.target) : {};
  const showHtmlMirror = Boolean(
    browser.currentUrl &&
      (browser.view?.render_mode === "html_mirror" || browser.view?.render_mode === "computed_html") &&
      documentHtml,
  );
  const mirrorDocument = useMemo(
    () =>
      showHtmlMirror
        ? browserMirrorSrcDoc(documentHtml, browser.currentUrl, browser.browserId, elementMap, false)
        : "",
    [browser.browserId, browser.currentUrl, documentHtml, elementMap, showHtmlMirror],
  );
  const canInspectBrowser = showHtmlMirror || showRenderedPage;
  const annotationCounts = useMemo(() => browserAnnotationCounts(annotations), [annotations]);
  const selectedElement = browser.selectedNodeId
    ? elementMap.find((item) => item.node_id === browser.selectedNodeId) ?? browser.elementMetadata[browser.selectedNodeId]
    : undefined;
  const pixelHoverElement = pixelHoverNodeId ? elementMap.find((item) => item.node_id === pixelHoverNodeId) : undefined;
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
              events?: unknown;
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
        onElementSelect(data.nodeId, element);
      } else if (data.type === "personagent-session-browser:element-action" && typeof data.nodeId === "string") {
        onBrowserElementActivate(data.nodeId, viewport(), data.action === "submit" ? "submit" : "click");
      } else if (data.type === "personagent-session-browser:text-selection") {
        const selection = normalizeBrowserTextSelection(data.selection);
        if (selection) {
          onTextSelect(selection);
        }
      } else if (data.type === "personagent-session-browser:event-batch" && Array.isArray(data.events)) {
        const events = data.events.filter(isBrowserCooperationEvent);
        if (events.length) onBrowserEvents(events);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [browser.browserId, onBrowserElementActivate, onBrowserEvents, onElementSelect, onNavigate, onTextSelect]);

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
    const traceEvent = latestBrowserTraceEvent(recentAgentEvents, timelineEvents);
    if (!traceEvent || !browser.view) return;
    const surface = showRenderedPage ? imageRef.current : viewportRef.current;
    const point = browserTracePoint(traceEvent, elementMap, browser.view, surface);
    if (!point) return;
    const effect = String(traceEvent.trace_effect ?? traceEvent.effect ?? traceEvent.event_type ?? "highlight");
    setGhostTrace((current) => ({
      x: point.x,
      y: point.y,
      effect,
      visible: true,
      nonce: current.nonce + 1,
    }));
    const timeout = window.setTimeout(() => {
      setGhostTrace((current) => ({ ...current, effect: "highlight" }));
    }, 700);
    return () => window.clearTimeout(timeout);
  }, [
    browser.view,
    elementMap,
    recentAgentEvents,
    showRenderedPage,
    timelineEvents,
  ]);

  useEffect(() => {
    if (!visibleBrowserToolVisual || !browser.view) return;
    const surface = showRenderedPage ? imageRef.current : viewportRef.current;
    const point = browserToolVisualPoint(visibleBrowserToolVisual, elementMap, browser.view, surface);
    if (!point) return;
    setGhostTrace((current) => ({
      x: point.x,
      y: point.y,
      effect: visibleBrowserToolVisual.effect,
      visible: true,
      nonce: current.nonce + 1,
    }));
    const timeout = window.setTimeout(() => {
      setGhostTrace((current) => ({ ...current, effect: "highlight" }));
    }, 850);
    return () => window.clearTimeout(timeout);
  }, [
    browser.view,
    elementMap,
    showRenderedPage,
    visibleBrowserToolVisual,
  ]);

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
        cooperationEnabled,
      },
      "*",
    );
  };

  useEffect(() => {
    postMirrorState();
  }, [browser.browserId, browser.mode, browser.selectedNodeId, annotationCounts, cooperationEnabled, mirrorUrl]);

  const handleViewportClick = (event: MouseEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view) return;
    if (browser.mode !== "browse" && pixelHoverElement?.node_id) {
      event.preventDefault();
      event.stopPropagation();
      onElementSelect(pixelHoverElement.node_id, pixelHoverElement as BrowserElementMetadata);
      return;
    }
    if (!imageRef.current) return;
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

  const handleViewportMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    if (browser.mode === "browse" || !browser.view) return;
    const surface = showRenderedPage ? imageRef.current : showHtmlMirror ? viewportRef.current : null;
    if (!surface) return;
    const element = browserElementAtRenderedPoint(event, surface, browser.view, elementMap);
    setPixelHoverNodeId(element?.node_id ?? null);
  };

  const handleViewportMouseLeave = () => {
    setPixelHoverNodeId(null);
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
          disabled={!canInspectBrowser}
          onClick={() => onModeChange(browser.mode === "annotate" ? "browse" : "annotate")}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
        </BrowserModeButton>
        <BrowserCooperationModeMenu
          value={cooperationMode}
          disabled={!canPersistWorkspace}
          onChange={onCooperationModeChange}
        />
        <BrowserModeButton
          label="Tracing"
          active={tracingOpen}
          disabled={!canInspectBrowser}
          onClick={() => setTracingOpen((open) => !open)}
        >
          <Activity className="h-3.5 w-3.5" />
        </BrowserModeButton>
      </div>
      <div className="-mx-3 flex h-8 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-background/55 px-3 text-[11px] text-muted-foreground">
        <span className={cn("rounded-full border px-2 py-0.5", browserCssBadgeClass(browser.view?.css_fidelity))}>
          {browserCssLabel(browser.view?.css_fidelity)}
        </span>
        <span className="min-w-0 flex-1 truncate">
          {browser.mode === "annotate"
            ? "Annotation mode · hover and click an element"
            : `${elementMap.length} mapped elements${backendTabs.length > 1 ? ` · ${backendTabs.length} tabs` : ""}`}
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
        onMouseMove={handleViewportMouseMove}
        onMouseLeave={handleViewportMouseLeave}
        onKeyDown={handleViewportKeyDown}
        onWheel={handleViewportWheel}
      >
        {showRenderedPage ? (
          <>
            <img
              ref={imageRef}
              src={imageSource}
              alt={browser.view?.title || browser.currentUrl || "LightPanda browser"}
              title={`Browser ${browser.currentUrl || browser.view?.url || ""}`.trim()}
              className="h-full min-h-[calc(100vh-220px)] w-full select-none object-contain"
              draggable={false}
            />
            {pixelHoverElement?.bounds && browser.view ? (
              <div
              className="pointer-events-none absolute z-20 rounded-[var(--browser-highlight-radius,4px)] border-2 border-primary bg-primary/18 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.18)] transition-all duration-100"
              style={browserRenderedElementStyle(pixelHoverElement.bounds, imageRef.current, browser.view)}
              />
            ) : null}
          </>
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
        {activeProposal && browser.view ? (
          <BrowserProposalOverlay
            proposal={activeProposal}
            target={activeProposalTarget}
            elementMap={elementMap}
            view={browser.view}
            surface={showRenderedPage ? imageRef.current : viewportRef.current}
            onDecision={onProposalDecision}
          />
        ) : null}
        {visibleBrowserToolVisual && browser.view ? (
          <BrowserToolVisualOverlay
            visual={visibleBrowserToolVisual}
            elementMap={elementMap}
            view={browser.view}
            surface={showRenderedPage ? imageRef.current : viewportRef.current}
          />
        ) : null}
        <BrowserGhostCursor trace={ghostTrace} />
        {tracingOpen ? (
          <BrowserTracingPanel
            cooperation={cooperation}
            rawEvents={rawEvents}
            usefulTimeline={usefulTimeline}
            recentUserEvents={recentUserEvents}
            recentAgentEvents={recentAgentEvents}
            pendingProposals={pendingProposals}
            activeTab={tracingTab}
            onTabChange={setTracingTab}
            onClose={() => setTracingOpen(false)}
            onProposalDecision={onProposalDecision}
          />
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

function BrowserCooperationModeMenu({
  value,
  disabled,
  onChange,
}: {
  value: SessionBrowserCooperationMode | "off";
  disabled: boolean;
  onChange: (mode: SessionBrowserCooperationMode | "off") => void;
}) {
  const options: Array<{ value: SessionBrowserCooperationMode | "off"; label: string }> = [
    { value: "off", label: "Off" },
    { value: "observe_only", label: "Observe" },
    { value: "suggest_before_action", label: "Suggest" },
    { value: "agent_control", label: "Control" },
  ];
  const active = options.find((option) => option.value === value) ?? options[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Browser cooperation mode"
          disabled={disabled}
          className={cn(
            "inline-flex h-7 max-w-[132px] shrink-0 items-center gap-1.5 rounded-full border border-glass-border/35 bg-card/70 px-2.5 text-[11px] text-foreground outline-none transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-35",
            value !== "off" && "border-primary/35 bg-primary/10 text-primary",
          )}
        >
          <span className="truncate">{active.label}</span>
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Cooperation</DropdownMenuLabel>
        {options.map((option) => (
          <DropdownMenuItem key={option.value} onSelect={() => onChange(option.value)}>
            <Check className={cn("mr-2 h-3.5 w-3.5", option.value === value ? "opacity-100" : "opacity-0")} />
            <span>{option.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function BrowserToolVisualOverlay({
  visual,
  elementMap,
  view,
  surface,
}: {
  visual: BrowserToolVisual;
  elementMap: SessionBrowserElement[];
  view: SessionBrowserView;
  surface: HTMLElement | null;
}) {
  const elements = browserToolOverlayElements(visual, elementMap);
  if (!elements.length) return null;
  const isMap = visual.effect === "map";
  return (
    <div className="pointer-events-none absolute inset-0 z-[32]" aria-hidden="true">
      {elements.slice(0, isMap ? 120 : 8).map((element, index) => {
        if (!element.bounds) return null;
        const isTarget = Boolean(visual.nodeId && element.node_id === visual.nodeId);
        return (
          <div
            key={`${visual.id}-${element.node_id || index}`}
            data-testid={`browser-tool-highlight-${element.node_id || index}`}
            className={cn(
              "absolute rounded-[4px] border transition-all duration-150",
              isMap
                ? "border-amber-300/85 bg-amber-300/10 shadow-[0_0_0_1px_rgba(251,191,36,0.14)]"
                : "border-primary bg-primary/16 shadow-[0_0_0_3px_rgba(34,150,255,0.14)]",
              isTarget && "border-2 border-primary bg-primary/22 shadow-[0_0_0_4px_rgba(34,150,255,0.20)]",
            )}
            style={browserRenderedElementStyle(element.bounds, surface, view)}
          />
        );
      })}
      <div className="absolute right-3 top-3 z-[33] rounded-full border border-glass-border/35 bg-background/92 px-2.5 py-1 text-[10px] font-medium text-muted-foreground shadow-floating backdrop-blur-xl">
        {browserToolVisualLabel(visual)}
      </div>
    </div>
  );
}

function BrowserProposalOverlay({
  proposal,
  target,
  elementMap,
  view,
  surface,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  target: Record<string, unknown>;
  elementMap: SessionBrowserElement[];
  view: SessionBrowserView;
  surface: HTMLElement | null;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  const bounds = browserTraceBounds(target, elementMap);
  if (!bounds) {
    return (
      <div className="absolute right-3 top-3 z-40 w-[min(340px,calc(100%-24px))] rounded-lg border border-primary/35 bg-background/94 p-3 text-xs shadow-floating backdrop-blur-xl">
        <ProposalBody proposal={proposal} onDecision={onDecision} />
      </div>
    );
  }
  const highlight = browserRenderedElementStyle(bounds, surface, view);
  const barTop = Math.max(8, highlight.top - 38);
  const barLeft = Math.max(8, Math.min(highlight.left, (view.viewport_width || 420) - 230));
  return (
    <>
      <div
        className="pointer-events-none absolute z-30 rounded-[4px] border-2 border-primary bg-primary/18 shadow-[0_0_0_3px_rgba(34,150,255,0.14)]"
        style={highlight}
      />
      <div
        className="absolute z-40 flex max-w-[min(360px,calc(100%-16px))] items-center gap-2 rounded-full border border-primary/35 bg-background/94 px-2 py-1.5 text-[11px] shadow-floating backdrop-blur-xl"
        style={{ left: barLeft, top: barTop }}
      >
        <span className="min-w-0 max-w-32 truncate text-muted-foreground">
          {String(proposal.tool_name ?? "Browser action")}
        </span>
        <button
          type="button"
          className="rounded-full bg-primary px-2.5 py-1 font-medium text-primary-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "approve");
          }}
        >
          Allow
        </button>
        <button
          type="button"
          className="rounded-full border border-destructive/35 px-2.5 py-1 font-medium text-destructive"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "deny");
          }}
        >
          Deny
        </button>
        <button
          type="button"
          className="rounded-full px-2 py-1 text-muted-foreground hover:text-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "dismiss");
          }}
        >
          Dismiss
        </button>
      </div>
    </>
  );
}

function ProposalBody({
  proposal,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">
            {String(proposal.tool_name ?? "Browser action")}
          </div>
          <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
            {String(proposal.reason ?? "The agent needs permission before executing this action.")}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-primary/30 px-2 py-0.5 font-mono text-[10px] text-primary">
          {String(proposal.mode ?? "ask")}
        </span>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" onClick={() => onDecision(proposal, "approve")}>
          Allow
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDecision(proposal, "deny")}>
          Deny
        </Button>
      </div>
    </div>
  );
}

function BrowserGhostCursor({ trace }: { trace: BrowserGhostTrace }) {
  if (!trace.visible) return null;
  const effect = trace.effect || "highlight";
  return (
    <div
      data-testid="browser-ghost-cursor"
      className="pointer-events-none absolute z-[35] transition-transform duration-500 ease-out"
      style={{ transform: `translate3d(${trace.x}px, ${trace.y}px, 0)` }}
      aria-hidden="true"
    >
      <div className="relative -left-1 -top-1">
        <MousePointerClick className="h-5 w-5 text-primary drop-shadow-[0_6px_14px_rgba(0,0,0,0.45)]" />
        {effect === "click" ? (
          <span key={trace.nonce} className="absolute left-0 top-0 h-6 w-6 animate-ping rounded-full border border-primary/70" />
        ) : null}
        {effect === "type" ? (
          <span key={trace.nonce} className="absolute left-5 top-1 h-4 w-0.5 animate-pulse bg-primary" />
        ) : null}
        {effect === "scroll" ? (
          <span key={trace.nonce} className="absolute left-4 top-5 h-10 w-1 rounded-full bg-primary/45 blur-[1px]" />
        ) : null}
        {effect === "extract" ? (
          <span key={trace.nonce} className="absolute left-4 top-4 h-8 w-8 rounded border border-primary/70 bg-primary/12" />
        ) : null}
      </div>
    </div>
  );
}

function BrowserTracingPanel({
  cooperation,
  rawEvents,
  usefulTimeline,
  recentUserEvents,
  recentAgentEvents,
  pendingProposals,
  activeTab,
  onTabChange,
  onClose,
  onProposalDecision,
}: {
  cooperation?: SessionBrowserView["cooperation"];
  rawEvents: Array<Record<string, unknown>>;
  usefulTimeline: Array<Record<string, unknown>>;
  recentUserEvents: Array<Record<string, unknown>>;
  recentAgentEvents: Array<Record<string, unknown>>;
  pendingProposals: Array<Record<string, unknown>>;
  activeTab: BrowserTracingTab;
  onTabChange: (tab: BrowserTracingTab) => void;
  onClose: () => void;
  onProposalDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  const tabs: Array<[BrowserTracingTab, string, number]> = [
    ["timeline", "Useful Timeline", usefulTimeline.length],
    ["raw", "Raw Events", rawEvents.length],
    ["state", "Page State", 0],
    ["agent", "Agent Actions", recentAgentEvents.length],
    ["proposals", "Proposals", pendingProposals.length],
  ];
  return (
    <aside
      data-browser-tracing-panel="true"
      className="absolute inset-y-3 right-3 z-50 flex w-[min(390px,calc(100%-24px))] flex-col overflow-hidden rounded-lg border border-glass-border/35 bg-background/96 shadow-floating backdrop-blur-xl"
      onClick={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-glass-border/25 px-3">
        <Activity className="h-3.5 w-3.5 text-primary" />
        <div className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">Tracing</div>
        <button type="button" className="text-muted-foreground hover:text-foreground" onClick={onClose} aria-label="Close tracing">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-glass-border/20 px-2 py-2">
        {tabs.map(([tab, label, count]) => (
          <button
            key={tab}
            type="button"
            className={cn(
              "shrink-0 rounded-full px-2.5 py-1 text-[11px] transition-colors",
              activeTab === tab ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
            onClick={() => onTabChange(tab)}
          >
            {label}
            {count ? <span className="ml-1 font-mono">{count}</span> : null}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {activeTab === "timeline" ? <TraceList items={usefulTimeline} empty="No useful timeline events yet." /> : null}
        {activeTab === "raw" ? <TraceList items={rawEvents} empty="No raw events persisted yet." raw /> : null}
        {activeTab === "state" ? (
          <TraceJson value={cooperation?.page_state ?? {}} />
        ) : null}
        {activeTab === "agent" ? <TraceList items={recentAgentEvents} empty="No agent browser actions yet." /> : null}
        {activeTab === "proposals" ? (
          <div className="space-y-2">
            {pendingProposals.length ? (
              pendingProposals.map((proposal) => (
                <div key={String(proposal.proposal_id ?? proposal.approval_id)} className="rounded-lg border border-glass-border/30 p-2">
                  <ProposalBody proposal={proposal} onDecision={onProposalDecision} />
                  <TraceJson value={proposal} compact />
                </div>
              ))
            ) : (
              <EmptyList text="No pending proposals." />
            )}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function TraceList({ items, empty, raw = false }: { items: Array<Record<string, unknown>>; empty: string; raw?: boolean }) {
  if (!items.length) return <EmptyList text={empty} />;
  return (
    <div className="space-y-2">
      {items.slice(-80).reverse().map((item, index) => (
        <div key={String(item.event_id ?? item.id ?? index)} className="rounded-lg border border-glass-border/25 p-2 text-xs">
          <div className="flex items-center gap-2">
            <TraceRoleBadge role={String(item.trace_role ?? item.role ?? item.source ?? "browser")} />
            <span className="min-w-0 flex-1 truncate text-foreground">
              {String(item.semantic_label ?? item.label ?? item.kind ?? item.event_type ?? "event")}
            </span>
            {item.sequence !== undefined ? <span className="font-mono text-[10px] text-muted-foreground">#{String(item.sequence)}</span> : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
            {item.kind ? <span>{String(item.kind)}</span> : null}
            {item.importance ? <span>{String(item.importance)}</span> : null}
            {item.trace_effect ? <span>{String(item.trace_effect)}</span> : null}
          </div>
          {raw ? <TraceJson value={item} compact /> : null}
        </div>
      ))}
    </div>
  );
}

function TraceRoleBadge({ role }: { role: string }) {
  const className =
    role === "agent"
      ? "border-primary/30 bg-primary/12 text-primary"
      : role === "user"
        ? "border-success/30 bg-success/10 text-success"
        : role === "system"
          ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
          : "border-glass-border/35 bg-muted/30 text-muted-foreground";
  return <span className={cn("rounded-full border px-2 py-0.5 font-mono text-[10px]", className)}>{role}</span>;
}

function TraceJson({ value, compact = false }: { value: unknown; compact?: boolean }) {
  return (
    <pre
      className={cn(
        "mt-2 overflow-auto rounded-md border border-glass-border/25 bg-card/50 p-2 font-mono text-[10px] leading-4 text-muted-foreground",
        compact ? "max-h-28" : "max-h-[55vh]",
      )}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
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

function latestBrowserToolVisual(messages: ChatMessageUi[]): BrowserToolVisual | undefined {
  for (const message of [...messages].reverse()) {
    if (message.role !== "agent") continue;
    for (const block of [...message.toolBlocks].reverse()) {
      const visual = browserToolVisualFromBlock(block);
      if (visual) return visual;
    }
  }
  return undefined;
}

function browserToolVisualFromBlock(block: ToolBlockUi): BrowserToolVisual | undefined {
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
  const target =
    normalizeBrowserElementMetadata(lastAction.target, nodeId || "") ??
    (nodeId ? elements.find((element) => element.node_id === nodeId) : undefined) ??
    normalizeBrowserElementMetadata({ ...result, node_id: nodeId || result.node_id || "browser_result" }, nodeId || "browser_result");
  const x = numericValue(lastAction.x ?? data.x);
  const y = numericValue(lastAction.y ?? data.y);
  return {
    id: `${block.id}:${block.status}:${browserStringValue(data.type) || block.name}`,
    toolName: block.name,
    status: block.status,
    effect,
    browserId: browserStringValue(data.browser_id),
    pageId: browserStringValue(data.page_id) ?? browserStringValue(data.active_tab_id),
    windowId: browserStringValue(data.window_id),
    url: browserStringValue(data.url) ?? browserStringValue(data.final_url),
    nodeId,
    target,
    elements,
    coordinates: x !== undefined && y !== undefined ? { x, y } : undefined,
    data,
  };
}

function browserToolEffect(block: ToolBlockUi): BrowserToolVisualEffect | undefined {
  if (!block.name.startsWith("Browser")) return undefined;
  if (block.name === "BrowserListTabs" || block.name === "BrowserReadContentChunk" || block.name === "BrowserCloseTab") {
    return undefined;
  }
  if (block.name === "BrowserGetElementMap") return "map";
  if (block.name === "BrowserClick") return "click";
  if (block.name === "BrowserType") return "type";
  if (block.name === "BrowserScroll" || block.name === "BrowserHistory") return "scroll";
  if (block.name === "BrowserScreenshot" || block.name === "BrowserExtractContent" || block.name === "BrowserGetHtml") return "extract";
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

function browserToolElements(data: Record<string, unknown>) {
  const rawElements = recordArray(data.elements).length ? recordArray(data.elements) : recordArray(data.element_map);
  return rawElements
    .map((item, index) => normalizeBrowserElementMetadata(item, browserStringValue(item.node_id) || `browser_tool_${index}`))
    .filter((item): item is BrowserElementMetadata => Boolean(item));
}

function browserToolVisualAppliesToBrowser(visual: BrowserToolVisual | undefined, browser: BrowserState) {
  if (!visual) return false;
  if (visual.url && browser.currentUrl && normalizeComparableUrl(visual.url) !== normalizeComparableUrl(browser.currentUrl)) {
    return false;
  }
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
  if (!visualIds.length) return true;
  if (visual.url && browser.currentUrl) return true;
  return false;
}

function browserViewFromToolVisual(visual: BrowserToolVisual): SessionBrowserView | undefined {
  const data = visual.data;
  const hasRenderableView = Boolean(
    browserStringValue(data.url) &&
      (browserStringValue(data.image_data) ||
        browserStringValue(data.document_html) ||
        browserStringValue(data.html) ||
        recordArray(data.element_map).length),
  );
  if (!hasRenderableView) return undefined;
  return {
    ...data,
    type: "browser_view",
    browser_id: browserStringValue(data.browser_id) || visual.browserId || "",
    url: browserStringValue(data.url) || visual.url || "",
    title: browserStringValue(data.title) || "",
    html: browserStringValue(data.html) || "",
    document_html: browserStringValue(data.document_html) || browserStringValue(data.html) || "",
    render_mode: browserRenderModeValue(data.render_mode),
    css_fidelity: browserStringValue(data.css_fidelity) || "pixel",
    element_map: browserToolElements({ element_map: data.element_map }),
    annotations: Array.isArray(data.annotations) ? (data.annotations as SessionBrowserAnnotation[]) : [],
    timeline_events: Array.isArray(data.timeline_events) ? (data.timeline_events as SessionBrowserTimelineEvent[]) : [],
    user_agent: browserStringValue(data.user_agent) || "",
    image_data: browserStringValue(data.image_data) || "",
    image_mime_type: browserStringValue(data.image_mime_type) || "",
    screenshot_method: browserStringValue(data.screenshot_method) || "",
    screenshot_error: browserStringValue(data.screenshot_error) || "",
    viewport_width: numericValue(data.viewport_width) || 1024,
    viewport_height: numericValue(data.viewport_height) || 720,
    can_capture: typeof data.can_capture === "boolean" ? data.can_capture : true,
  };
}

function browserToolOverlayElements(visual: BrowserToolVisual, elementMap: SessionBrowserElement[]) {
  const candidates = visual.effect === "map" ? [...visual.elements] : [];
  if (visual.target) candidates.unshift(visual.target);
  if (visual.nodeId) {
    const mapped = visual.elements.find((element) => element.node_id === visual.nodeId) ?? elementMap.find((element) => element.node_id === visual.nodeId);
    if (mapped) candidates.unshift(mapped);
  }
  const seen = new Set<string>();
  return candidates.filter((element, index) => {
    const bounds = element.bounds;
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return false;
    const key = element.node_id || `${bounds.x}:${bounds.y}:${index}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return visual.effect !== "map" || element.visible !== false;
  });
}

function browserToolVisualPoint(
  visual: BrowserToolVisual,
  elementMap: SessionBrowserElement[],
  view: SessionBrowserView,
  surface: HTMLElement | null,
) {
  if (visual.coordinates) {
    const rect = surface?.getBoundingClientRect();
    const scaleX = rect?.width ? rect.width / Math.max(1, view.viewport_width || rect.width) : 1;
    const scaleY = rect?.height ? rect.height / Math.max(1, view.viewport_height || rect.height) : 1;
    return { x: Math.round(visual.coordinates.x * scaleX), y: Math.round(visual.coordinates.y * scaleY) };
  }
  const [target] = browserToolOverlayElements(visual, elementMap);
  if (target?.bounds) {
    const style = browserRenderedElementStyle(target.bounds, surface, view);
    return {
      x: Math.round(style.left + style.width / 2),
      y: Math.round(style.top + style.height / 2),
    };
  }
  if (visual.effect === "scroll") {
    const rect = surface?.getBoundingClientRect();
    return { x: Math.round((rect?.width || view.viewport_width || 420) / 2), y: Math.round((rect?.height || view.viewport_height || 640) / 2) };
  }
  return undefined;
}

function browserToolVisualLabel(visual: BrowserToolVisual) {
  if (visual.effect === "map") return `Mapped ${visual.elements.length} elements`;
  const targetText = visual.target?.text || visual.target?.name || visual.nodeId || "";
  if (visual.effect === "click") return targetText ? `Click ${targetText}` : "Browser click";
  if (visual.effect === "type") return targetText ? `Input ${targetText}` : "Browser input";
  if (visual.effect === "scroll") return "Browser scroll";
  if (visual.effect === "extract") return "Browser read";
  return visual.toolName;
}

function browserStringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return undefined;
}

function browserRenderModeValue(value: unknown): SessionBrowserView["render_mode"] {
  const mode = browserStringValue(value);
  if (mode === "html_mirror" || mode === "computed_html" || mode === "pixel" || mode === "screenshot") return mode;
  return "screenshot";
}

function normalizeComparableUrl(value: string) {
  return value.trim().replace(/\/+$/, "");
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

function browserElementAtRenderedPoint(
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

function browserRenderedElementStyle(
  bounds: NonNullable<SessionBrowserElement["bounds"]>,
  image: HTMLElement | null,
  view: SessionBrowserView,
) {
  const rect = image?.getBoundingClientRect();
  const scaleX = rect?.width ? rect.width / Math.max(1, view.viewport_width || rect.width) : 1;
  const scaleY = rect?.height ? rect.height / Math.max(1, view.viewport_height || rect.height) : 1;
  return {
    left: Math.round(bounds.x * scaleX),
    top: Math.round(bounds.y * scaleY),
    width: Math.round(bounds.width * scaleX),
    height: Math.round(bounds.height * scaleY),
  };
}

function browserTraceBounds(target: Record<string, unknown>, elementMap: SessionBrowserElement[]) {
  const rawBounds = recordValue(target.bounds);
  const bounds = normalizeBounds(rawBounds);
  if (bounds) return bounds;
  const nodeId = String(target.node_id ?? "");
  if (!nodeId) return undefined;
  return elementMap.find((item) => item.node_id === nodeId)?.bounds;
}

function browserTracePoint(
  traceEvent: Record<string, unknown>,
  elementMap: SessionBrowserElement[],
  view: SessionBrowserView,
  surface: HTMLElement | null,
) {
  const coordinates = recordValue(traceEvent.coordinates);
  const x = numericValue(coordinates.x ?? traceEvent.x);
  const y = numericValue(coordinates.y ?? traceEvent.y);
  if (x !== undefined && y !== undefined) {
    const rect = surface?.getBoundingClientRect();
    const scaleX = rect?.width ? rect.width / Math.max(1, view.viewport_width || rect.width) : 1;
    const scaleY = rect?.height ? rect.height / Math.max(1, view.viewport_height || rect.height) : 1;
    return { x: Math.round(x * scaleX), y: Math.round(y * scaleY) };
  }
  const target = recordValue(traceEvent.target);
  const bounds = browserTraceBounds(target, elementMap);
  if (!bounds) return undefined;
  const style = browserRenderedElementStyle(bounds, surface, view);
  return {
    x: Math.round(style.left + style.width / 2),
    y: Math.round(style.top + style.height / 2),
  };
}

function latestBrowserTraceEvent(
  recentAgentEvents: Array<Record<string, unknown>>,
  timelineEvents: SessionBrowserTimelineEvent[],
) {
  const agentTrace = recentAgentEvents.at(-1);
  if (agentTrace) return agentTrace;
  const timelineTrace = timelineEvents
    .filter((event) => event.source === "agent")
    .at(-1);
  if (!timelineTrace) return undefined;
  return {
    ...timelineTrace,
    trace_effect: traceEffectFromEventType(timelineTrace.event_type),
    target: recordValue(timelineTrace.payload).target,
  };
}

function traceEffectFromEventType(eventType: string) {
  if (/click|tap/i.test(eventType)) return "click";
  if (/type|key|input/i.test(eventType)) return "type";
  if (/scroll/i.test(eventType)) return "scroll";
  if (/extract|read|html|screenshot/i.test(eventType)) return "extract";
  return "highlight";
}

function normalizeBounds(value: Record<string, unknown>) {
  const x = numericValue(value.x);
  const y = numericValue(value.y);
  const width = numericValue(value.width);
  const height = numericValue(value.height);
  if (x === undefined || y === undefined || width === undefined || height === undefined) return undefined;
  return { x, y, width, height };
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
}

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    : [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
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
  composerAnnotationSequence += 1;
  return Date.now() + composerAnnotationSequence;
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


function browserCssLabel(value?: string) {
  if (value === "pixel") return "Pixel render";
  if (value === "original_embedded") return "Original + Embedded CSS";
  if (value === "embedded") return "Embedded CSS";
  if (value === "computed") return "Computed CSS";
  if (value === "fallback_html") return "Fallback HTML";
  return "Original CSS";
}

function browserCssBadgeClass(value?: string) {
  if (value === "fallback_html") return "border-warning/40 bg-warning/10 text-warning";
  if (value === "original_embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "embedded") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "computed") return "border-primary/35 bg-primary/10 text-primary";
  if (value === "pixel") return "border-success/35 bg-success/10 text-success";
  return "border-glass-border/35 bg-card/70 text-muted-foreground";
}

function selectedElementLabel(element: SessionBrowserElement | undefined, nodeId: string) {
  if (!element) return nodeId;
  const role = element.role || element.tag || "element";
  const text = element.text ? ` · ${element.text.slice(0, 90)}` : "";
  return `${role}${text}`;
}
