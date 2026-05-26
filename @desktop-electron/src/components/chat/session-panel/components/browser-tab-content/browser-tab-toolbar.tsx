import { ArrowLeft, ArrowRight, MessageSquarePlus, RefreshCw, Activity } from "lucide-react";
import { BrowserModeButton, BrowserNavButton } from "../browser-controls";
import { BrowserCooperationModeMenu } from "../browser-cooperation";
import type { BrowserState } from "../../helpers";
import type { SessionBrowserCooperationMode, SessionBrowserViewport } from "../../../../../api/client";
import type { BrowserTabContentProps } from "./browser-tab-content-types";

interface BrowserTabToolbarProps {
  browser: BrowserState;
  canGoBack: boolean;
  canGoForward: boolean;
  canRefresh: boolean;
  canInspectBrowser: boolean;
  cooperationMode: SessionBrowserCooperationMode | "off";
  canPersistWorkspace: boolean;
  tracingOpen: boolean;
  viewport: () => SessionBrowserViewport;
  onDraftChange: BrowserTabContentProps["onDraftChange"];
  onNavigate: BrowserTabContentProps["onNavigate"];
  onBack: BrowserTabContentProps["onBack"];
  onForward: BrowserTabContentProps["onForward"];
  onRefresh: BrowserTabContentProps["onRefresh"];
  onModeChange: BrowserTabContentProps["onModeChange"];
  onCooperationModeChange: BrowserTabContentProps["onCooperationModeChange"];
  onToggleTracing: () => void;
}

export function BrowserTabToolbar({
  browser,
  canGoBack,
  canGoForward,
  canRefresh,
  canInspectBrowser,
  cooperationMode,
  canPersistWorkspace,
  tracingOpen,
  viewport,
  onDraftChange,
  onNavigate,
  onBack,
  onForward,
  onRefresh,
  onModeChange,
  onCooperationModeChange,
  onToggleTracing,
}: BrowserTabToolbarProps) {
  return (
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
        onClick={onToggleTracing}
      >
        <Activity className="h-3.5 w-3.5" />
      </BrowserModeButton>
    </div>
  );
}
