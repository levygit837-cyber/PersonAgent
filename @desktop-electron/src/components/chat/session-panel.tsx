import { PanelRightClose } from "lucide-react";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { BrowserTabStrip } from "./session-panel/components/browser-tab-strip";
import { DetailTabContent, SummaryContent } from "./session-panel/components/detail-sections";
import { EmptyPanel, PanelSkeleton } from "./session-panel/components/shared-ui";
import { useBrowserTabs } from "./session-panel/hooks/use-browser-tabs";
import { useSessionPanelState } from "./session-panel/hooks/use-session-panel-state";
export { SESSION_PANEL_CACHE_STORAGE_KEY } from "./session-panel/services/cache";
export { browserMirrorSrcDoc, sanitizeBrowserMirrorHtml } from "./session-panel/components/browser-mirror";
import { summaryTab, isBrowserTab } from "./session-panel/helpers";

export function SessionPanel({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const {
    baseUrl,
    workspaceRoot,
    conversationId,
    isStreaming,
    browserToolBlocks,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
    snapshot,
    usage,
    panelIsLoading,
    panelError,
  } = useSessionPanelState(visible);
  const {
    tabs,
    activeTabId,
    activeTab,
    loadingDetailId,
    browserVisualEvents,
    browserToolEvent,
    setActiveTabId,
    closeTab,
    openBrowserPlaceholder,
    openDetailTab,
    openProjectDetail,
    updateBrowserTab,
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
    setBrowserCooperationMode,
    decideBrowserProposal,
    recordBrowserEvents,
    setBrowserError,
  } = useBrowserTabs({
    browserToolBlocks,
    isStreaming,
    conversationId,
    baseUrl,
    workspaceRoot,
    visible,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
  });
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
            browserToolEvent={browserToolEvent}
            browserVisualEvents={browserVisualEvents}
          />
        ) : !conversationId ? (
          <EmptyPanel text="Start or open a conversation to view session data." />
        ) : panelIsLoading ? (
          <PanelSkeleton />
        ) : panelError ? (
          <EmptyPanel text={panelError instanceof Error ? panelError.message : String(panelError)} />
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
            browserToolEvent={browserToolEvent}
            browserVisualEvents={browserVisualEvents}
          />
        )}
      </div>
    </aside>
  );
}
