import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type WheelEvent } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ListChecks,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  X,
} from "lucide-react";
import {
  fetchBackendText,
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserViewport,
} from "../../../../api/client";
import { cn } from "../../../../lib/utils";
import { useAppStore } from "../../../../stores/app-store";
import { Button } from "../../../ui/button";
import {
  browserAnnotationCounts,
  browserAnnotationEditorStyle,
  browserToolEventAppliesToBrowser,
  browserToolEventIsPassive,
  normalizeBrowserTextSelection,
} from "../helpers/browser-helpers";
import { normalizeBrowserElementMetadata, recordArray } from "../helpers";
import { browserCssBadgeClass, browserCssLabel, selectedElementLabel } from "../helpers/browser-normalization-helpers";
import {
  BROWSER_FORWARD_KEYS,
  browserElementAtRenderedPoint,
  browserRenderedElementStyle,
  browserViewport,
  isBrowserViewportControlTarget,
} from "../helpers/browser-viewport-helpers";
import { browserVisualEventFromProposal, browserVisualEventsFromRecords } from "../helpers/browser-visual-events";
import { BrowserCooperationModeMenu, BrowserProposalOverlay } from "./browser-cooperation";
import { BrowserModeButton, BrowserNavButton } from "./browser-controls";
import { browserMirrorSrcDoc } from "./browser-mirror";
import { BrowserTracingPanel } from "./browser-tracing";
import type {
  BrowserState,
  BrowserElementMetadata,
  BrowserTextSelectionMetadata,
  BrowserTracingTab,
  BrowserVisualEvent,
  BrowserToolEvent,
} from "../helpers";
import {
  BROWSER_LOADING_MESSAGES,
  browserCooperationFromView,
  isBrowserCooperationEvent,
  recordValue,
  resolveBackendUrlPath,
} from "../helpers";

export function BrowserTabContent({
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
}: {
  browser: BrowserState;
  browserToolEvent?: BrowserToolEvent;
  browserVisualEvents?: BrowserVisualEvent[];
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
  const cooperationMode = cooperationEnabled ? cooperation?.mode ?? cooperation?.agent_control ?? "observe_only" : "off";
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
	            onLoad={handleMirrorLoad}
	            className={cn(
	              "h-full min-h-[calc(100vh-220px)] w-full border-0 bg-white transition-opacity duration-150",
	              !mirrorReady && "opacity-0",
	            )}
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
        {tracingOpen ? (
          <BrowserTracingPanel
            cooperation={cooperation}
            rawEvents={rawEvents}
            usefulTimeline={usefulTimeline}
            recentUserEvents={recentUserEvents}
            recentAgentEvents={recentAgentEvents}
            pendingProposals={pendingProposals}
            visualEvents={visibleBrowserVisualEvents}
            activeTab={tracingTab}
            onTabChange={setTracingTab}
            onClose={() => setTracingOpen(false)}
            onProposalDecision={onProposalDecision}
          />
        ) : null}
        {browser.loading || showMirrorPreparing ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-background/78 px-8 text-center backdrop-blur-sm">
            <div className="flex max-w-[300px] flex-col items-center gap-3 rounded-2xl border border-glass-border/35 bg-card/86 px-5 py-5 shadow-floating ring-1 ring-white/[0.04]">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <div className="space-y-1">
                <div className="text-sm font-medium text-foreground">
                  {showMirrorPreparing ? "Aguardando CSS da pagina..." : BROWSER_LOADING_MESSAGES[loadingMessageIndex]}
                </div>
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
