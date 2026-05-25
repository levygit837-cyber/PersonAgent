import {
  actSessionBrowser,
  createSessionBrowserAnnotation,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../../../api/client";
import type { ComposerAnnotation } from "../../../../stores/chat-store";
import {
  browserAnnotationToComposerAnnotation,
  browserTextSelectionToComposerAnnotation,
  localBrowserAnnotation,
} from "../helpers/browser-helpers";
import {
  type BrowserElementMetadata,
  type BrowserState,
  type BrowserTextSelectionMetadata,
} from "../helpers/helpers";

export interface AnnotationDeps {
  browserForTab: (tabId: string) => BrowserState | undefined;
  updateBrowserTab: (tabId: string, updater: (browser: BrowserState) => BrowserState) => void;
  startBrowserRequest: (tabId: string, options?: { showLoading?: boolean }) => number;
  applyBrowserView: (
    tabId: string,
    view: SessionBrowserView,
    options?: { addHistory?: boolean; historyIndex?: number },
    requestId?: number,
  ) => void;
  setBrowserError: (tabId: string, error: unknown, requestId?: number) => void;
  baseUrl: string;
  conversationId: string | undefined;
  addComposerAnnotation: (annotation: ComposerAnnotation) => void;
}

export interface AnnotationApi {
  setBrowserMode: (tabId: string, mode: BrowserState["mode"]) => void;
  selectBrowserElement: (tabId: string, nodeId: string, element?: BrowserElementMetadata) => void;
  updateAnnotationDraft: (tabId: string, value: string) => void;
  addBrowserTextSelection: (tabId: string, selection: BrowserTextSelectionMetadata) => void;
  saveBrowserAnnotation: (tabId: string) => Promise<void>;
  activateBrowserElement: (
    tabId: string,
    nodeId: string,
    viewport: SessionBrowserViewport,
    action?: "click" | "submit",
  ) => Promise<void>;
}

export function createBrowserAnnotation(deps: AnnotationDeps): AnnotationApi {
  const {
    browserForTab,
    updateBrowserTab,
    startBrowserRequest,
    applyBrowserView,
    setBrowserError,
    baseUrl,
    conversationId,
    addComposerAnnotation,
  } = deps;

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

  return {
    setBrowserMode,
    selectBrowserElement,
    updateAnnotationDraft,
    addBrowserTextSelection,
    saveBrowserAnnotation,
    activateBrowserElement,
  };
}
