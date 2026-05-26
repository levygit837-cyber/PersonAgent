import type {
  BrowserState,
  BrowserElementMetadata,
  BrowserTextSelectionMetadata,
  BrowserTracingTab,
  BrowserVisualEvent,
  BrowserToolEvent,
} from "../../helpers";
import type {
  SessionBrowserCooperationEvent,
  SessionBrowserCooperationMode,
  SessionBrowserViewport,
} from "../../../../../api/client";

export interface BrowserTabContentProps {
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
}
