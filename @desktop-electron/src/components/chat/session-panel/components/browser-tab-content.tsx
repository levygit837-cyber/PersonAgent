import { Loader2, MessageSquarePlus, X } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { Button } from "../../../ui/button";
import { browserAnnotationEditorStyle } from "../helpers/browser-helpers";
import { browserRenderedElementStyle } from "../helpers/browser-viewport-helpers";
import { selectedElementLabel } from "../helpers/browser-normalization-helpers";
import { BrowserProposalOverlay } from "./browser-cooperation";
import { BrowserTracingPanel } from "./browser-tracing";
import { BROWSER_LOADING_MESSAGES } from "../helpers";
import { useBrowserTabContent } from "./browser-tab-content/use-browser-tab-content";
import { BrowserTabToolbar } from "./browser-tab-content/browser-tab-toolbar";
import { BrowserTabStatusBar } from "./browser-tab-content/browser-tab-status-bar";
import type { BrowserTabContentProps } from "./browser-tab-content/browser-tab-content-types";

export function BrowserTabContent(props: BrowserTabContentProps) {
  const {
    viewportRef,
    iframeRef,
    imageRef,
    annotationInputRef,
    mirrorUrl,
    mirrorReady,
    loadingMessageIndex,
    tracingOpen,
    tracingTab,
    canGoBack,
    canGoForward,
    canRefresh,
    imageSource,
    showRenderedPage,
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
  } = useBrowserTabContent(props);

  return (
    <div className="flex min-h-[calc(100vh-170px)] flex-col">
      <BrowserTabToolbar
        browser={props.browser}
        canGoBack={canGoBack}
        canGoForward={canGoForward}
        canRefresh={canRefresh}
        canInspectBrowser={canInspectBrowser}
        cooperationMode={cooperationMode}
        canPersistWorkspace={props.canPersistWorkspace}
        tracingOpen={tracingOpen}
        viewport={viewport}
        onDraftChange={props.onDraftChange}
        onNavigate={props.onNavigate}
        onBack={props.onBack}
        onForward={props.onForward}
        onRefresh={props.onRefresh}
        onModeChange={props.onModeChange}
        onCooperationModeChange={props.onCooperationModeChange}
        onToggleTracing={() => setTracingOpen((open) => !open)}
      />
      <BrowserTabStatusBar
        browser={props.browser}
        elementMapLength={elementMap.length}
        backendTabsLength={backendTabs.length}
        annotationsLength={annotations.length}
        timelineEventsLength={timelineEvents.length}
      />
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
              alt={props.browser.view?.title || props.browser.currentUrl || "LightPanda browser"}
              title={`Browser ${props.browser.currentUrl || props.browser.view?.url || ""}`.trim()}
              className="h-full min-h-[calc(100vh-220px)] w-full select-none object-contain"
              draggable={false}
            />
            {pixelHoverElement?.bounds && props.browser.view ? (
              <div
                className="pointer-events-none absolute z-20 rounded-[var(--browser-highlight-radius,4px)] border-2 border-primary bg-primary/18 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.18)] transition-all duration-100"
                style={browserRenderedElementStyle(pixelHoverElement.bounds, imageRef.current, props.browser.view)}
              />
            ) : null}
          </>
        ) : showHtmlMirror && mirrorUrl ? (
          <iframe
            ref={iframeRef}
            title={`Browser ${props.browser.currentUrl}`}
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
        {activeProposal && props.browser.view ? (
          <BrowserProposalOverlay
            proposal={activeProposal}
            target={activeProposalTarget}
            elementMap={elementMap}
            view={props.browser.view}
            surface={showRenderedPage ? imageRef.current : viewportRef.current}
            onDecision={props.onProposalDecision}
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
            onProposalDecision={props.onProposalDecision}
          />
        ) : null}
        {props.browser.loading || showMirrorPreparing ? (
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
        {props.browser.error ? (
          <div className="absolute inset-x-4 bottom-4 rounded-lg border border-destructive/35 bg-background/90 px-3 py-2 text-[11px] leading-4 text-destructive">
            {props.browser.error}
          </div>
        ) : null}
        {props.browser.mode === "annotate" && props.browser.selectedNodeId ? (
          <form
            data-browser-annotation-editor="true"
            className="absolute z-30 max-w-[calc(100%-24px)] rounded-2xl border border-glass-border/40 bg-card/88 p-2 text-xs shadow-floating ring-1 ring-white/[0.04] backdrop-blur-2xl"
            style={browserAnnotationEditorStyle(selectedElement?.bounds, props.browser.view)}
            onSubmit={(event) => {
              event.preventDefault();
              event.stopPropagation();
              props.onAnnotationSave();
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
                  {selectedElementLabel(selectedElement, props.browser.selectedNodeId)}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                  {selectedElement?.text || selectedElement?.selector || "Browser element"}
                </div>
              </div>
              <button
                type="button"
                className="text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => props.onElementSelect("")}
                aria-label="Close annotation editor"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <textarea
              ref={annotationInputRef}
              value={props.browser.annotationDraft}
              onChange={(event) => props.onAnnotationDraftChange(event.currentTarget.value)}
              placeholder="Ask the agent about this element or describe a change"
              rows={1}
              className="max-h-24 min-h-10 w-full resize-none rounded-xl border border-glass-border/30 bg-background/45 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/75 focus:border-primary/45"
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  props.onAnnotationSave();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  props.onElementSelect("");
                }
              }}
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => props.onElementSelect("")}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={!props.browser.annotationDraft.trim()}
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
