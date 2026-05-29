import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, KeyboardEvent, WheelEvent } from "react";
import { fetchBackendText } from "../../../../../api/client";
import { useAppStore } from "../../../../../stores/app-store";
import {
  browserAnnotationCounts,
  browserToolEventAppliesToBrowser,
  browserToolEventIsPassive,
  normalizeBrowserTextSelection,
} from "../../helpers/browser-helpers";
import { normalizeBrowserElementMetadata, recordArray } from "../../helpers";
import {
  BROWSER_FORWARD_KEYS,
  browserElementAtRenderedPoint,
  browserViewport,
  isBrowserViewportControlTarget,
} from "../../helpers/browser-viewport-helpers";
import { browserVisualEventFromProposal, browserVisualEventsFromRecords } from "../../helpers/browser-visual-events";
import { browserMirrorSrcDoc } from "../browser-mirror";
import type { BrowserTabContentProps } from "./browser-tab-content-types";
import {
  BROWSER_LOADING_MESSAGES,
  browserCooperationFromView,
  isBrowserCooperationEvent,
  recordValue,
  resolveBackendUrlPath,
} from "../../helpers";
import type { BrowserTracingTab, BrowserElementMetadata, BrowserVisualEvent } from "../../helpers";
import type { SessionBrowserCooperationMode } from "../../../../../api/client";

export function useBrowserTabContent({
  browser,
  browserToolEvent,
  browserVisualEvents = [],
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
}: BrowserTabContentProps) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const annotationInputRef = useRef<HTMLTextAreaElement | null>(null);
  const requestedInitialViewRef = useRef(false);
  const lastBrowserIdRef = useRef(browser.browserId);
  const [mirrorUrl, setMirrorUrl] = useState("");
  const [mirrorReady, setMirrorReady] = useState(false);
  const [remoteDocumentHtml, setRemoteDocumentHtml] = useState("");
  const [pixelHoverNodeId, setPixelHoverNodeId] = useState<string | null>(null);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const [tracingOpen, setTracingOpen] = useState(false);
  const [tracingTab, setTracingTab] = useState<BrowserTracingTab>("timeline");

  const canGoBack = browser.historyIndex > 0;
  const canGoForward = browser.historyIndex >= 0 && browser.historyIndex < browser.history.length - 1;
  const canRefresh = Boolean(browser.currentUrl);
  const imageSource =
    browser.view?.image_data && browser.view.image_mime_type
      ? `data:${browser.view.image_mime_type};base64,${browser.view.image_data}`
      : resolveBackendUrlPath(
          baseUrl,
          browser.view?.preview_image_url || browser.view?.browser_snapshot?.preview_image_url,
        );
  const showRenderedPage = Boolean(imageSource && browser.currentUrl);
  const inlineDocumentHtml = browser.view?.document_html || browser.view?.browser_snapshot?.document_html || browser.view?.html || "";
  const documentUrl = resolveBackendUrlPath(
    baseUrl,
    browser.view?.document_url || browser.view?.browser_snapshot?.document_url,
  );
  const documentHtml = inlineDocumentHtml || remoteDocumentHtml;
  const elementMap = browser.view?.element_map || browser.view?.browser_snapshot?.element_map || [];
  const annotations = browser.view?.annotations || browser.view?.browser_snapshot?.annotations || [];
  const timelineEvents = browser.view?.timeline_events || browser.view?.browser_snapshot?.timeline_events || [];
  const backendTabs = browser.view?.tabs || browser.view?.browser_snapshot?.tabs || [];
  const cooperation = browserCooperationFromView(browser.view);
  const cooperationEnabled = Boolean(cooperation?.enabled);
  const cooperationMode: SessionBrowserCooperationMode | "off" = cooperationEnabled ? cooperation?.mode ?? cooperation?.agent_control ?? "observe_only" : "off";
  const rawEvents = useMemo(() => recordArray(cooperation?.raw_events), [cooperation?.raw_events]);
  const usefulTimeline = useMemo(() => recordArray(cooperation?.useful_timeline), [cooperation?.useful_timeline]);
  const recentUserEvents = useMemo(() => recordArray(cooperation?.recent_user_events), [cooperation?.recent_user_events]);
  const recentAgentEvents = useMemo(() => recordArray(cooperation?.recent_agent_events), [cooperation?.recent_agent_events]);
  const pendingProposals = useMemo(
    () =>
      recordArray(cooperation?.pending_action_proposals).filter(
        (proposal: Record<string, unknown>) => String(proposal.status ?? "awaiting_approval") === "awaiting_approval",
      ),
    [cooperation?.pending_action_proposals],
  );
  const activeProposal = pendingProposals[0];
  const activeProposalTarget = activeProposal ? recordValue(activeProposal.target) : {};
  const proposalVisual = useMemo(
    () => (activeProposal ? browserVisualEventFromProposal(activeProposal, browser) : undefined),
    [activeProposal, browser.browserId, browser.currentUrl, browser.view?.active_tab_id],
  );
  const viewVisualEvents = useMemo(
    () => browserVisualEventsFromRecords(browser.view?.visual_events ?? browser.view?.browser_snapshot?.visual_events),
    [browser.view?.visual_events, browser.view?.browser_snapshot?.visual_events],
  );
  const visibleBrowserVisualEvents = useMemo(
    () =>
      [proposalVisual, ...browserVisualEvents, ...viewVisualEvents]
        .filter((event): event is BrowserVisualEvent => Boolean(event))
        .filter((event) => browserToolEventAppliesToBrowser(event, browser))
        .slice(0, 8),
    [browser, browserVisualEvents, proposalVisual, viewVisualEvents],
  );
  const activeBrowserToolEvent = browserToolEventAppliesToBrowser(browserToolEvent, browser) ? browserToolEvent : undefined;
  const showHtmlMirror = Boolean(
    browser.currentUrl &&
      (browser.view?.render_mode === "html_mirror" || browser.view?.render_mode === "computed_html") &&
      documentHtml,
  );
  const mirrorElementMap = useMemo(() => elementMap, [browser.browserId, browser.currentUrl, documentHtml]);
  const mirrorDocument = useMemo(
    () =>
      showHtmlMirror
        ? browserMirrorSrcDoc(documentHtml, browser.currentUrl, browser.browserId, mirrorElementMap, false)
        : "",
    [browser.browserId, browser.currentUrl, documentHtml, mirrorElementMap, showHtmlMirror],
  );
  const canInspectBrowser = showHtmlMirror || showRenderedPage;
  const annotationCounts = useMemo(() => browserAnnotationCounts(annotations), [annotations]);
  const selectedElement = browser.selectedNodeId
    ? elementMap.find((item) => item.node_id === browser.selectedNodeId) ?? browser.elementMetadata[browser.selectedNodeId]
    : undefined;
  const pixelHoverElement = pixelHoverNodeId ? elementMap.find((item) => item.node_id === pixelHoverNodeId) : undefined;
  const viewport = () => browserViewport(viewportRef.current, browser.view);
  const showEmptyState = !browser.loading && !showRenderedPage && !(showHtmlMirror && mirrorUrl);
  const showMirrorPreparing = showHtmlMirror && Boolean(mirrorUrl) && !mirrorReady;

  if (lastBrowserIdRef.current !== browser.browserId) {
    lastBrowserIdRef.current = browser.browserId;
    requestedInitialViewRef.current = false;
  }

  useEffect(() => {
    if (requestedInitialViewRef.current || browser.view || browser.loading) return;
    if (activeBrowserToolEvent && browserToolEventIsPassive(activeBrowserToolEvent)) return;
    requestedInitialViewRef.current = true;
    onLoadView(viewport());
  }, [browser.browserId, browser.currentUrl, browser.loading, browser.view, onLoadView, activeBrowserToolEvent]);

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
      if (!data || data.browserId !== browser.browserId) return;
      if (data.type === "personagent-session-browser:ready") {
        setMirrorReady(true);
      } else if (data.type === "personagent-session-browser:navigate" && typeof data.url === "string") {
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
    if (inlineDocumentHtml || !documentUrl) {
      setRemoteDocumentHtml("");
      return;
    }
    let cancelled = false;
    setRemoteDocumentHtml("");
    fetchBackendText(documentUrl)
      .then((html) => {
        if (!cancelled) setRemoteDocumentHtml(html);
      })
      .catch(() => {
        if (!cancelled) setRemoteDocumentHtml("");
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, inlineDocumentHtml]);

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
      setMirrorReady(false);
      setMirrorUrl("");
      return;
    }
    const nextUrl = URL.createObjectURL(new Blob([mirrorDocument], { type: "text/html" }));
    setMirrorReady(false);
    setMirrorUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [mirrorDocument]);

  useEffect(() => {
    if (!mirrorUrl || mirrorReady) return;
    const timer = window.setTimeout(() => {
      setMirrorReady(true);
    }, 7000);
    return () => window.clearTimeout(timer);
  }, [mirrorUrl, mirrorReady]);

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

  const handleMirrorLoad = () => {
    postMirrorState();
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

  return {
    viewportRef,
    iframeRef,
    imageRef,
    annotationInputRef,
    mirrorUrl,
    mirrorReady,
    pixelHoverNodeId,
    loadingMessageIndex,
    tracingOpen,
    tracingTab,
    canGoBack,
    canGoForward,
    canRefresh,
    imageSource,
    showRenderedPage,
    documentHtml,
    elementMap,
    annotations,
    timelineEvents,
    backendTabs,
    cooperation,
    cooperationMode,
    rawEvents,
    usefulTimeline,
    recentUserEvents,
    recentAgentEvents,
    pendingProposals,
    activeProposal,
    activeProposalTarget,
    visibleBrowserVisualEvents,
    showHtmlMirror,
    canInspectBrowser,
    annotationCounts,
    selectedElement,
    pixelHoverElement,
    viewport,
    showEmptyState,
    showMirrorPreparing,
    handleMirrorLoad,
    handleViewportClick,
    handleViewportMouseMove,
    handleViewportMouseLeave,
    handleViewportKeyDown,
    handleViewportWheel,
    setTracingOpen,
    setTracingTab,
  };
}
