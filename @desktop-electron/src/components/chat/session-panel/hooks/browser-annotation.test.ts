import { describe, expect, it, vi } from "vitest";
import { createBrowserAnnotation, type AnnotationDeps } from "./browser-annotation";
import type { BrowserState } from "../helpers/helpers";
import type { SessionBrowserView } from "../../../../api/client";

function makeBrowserState(overrides: Partial<BrowserState> = {}): BrowserState {
  return {
    browserId: "b1",
    pageId: "p1",
    currentUrl: "https://example.com",
    draftUrl: "https://example.com",
    history: [],
    historyIndex: -1,
    mode: "browse",
    elementMetadata: {},
    annotationDraft: "",
    loading: false,
    requestId: 0,
    ...overrides,
  };
}

function makeDeps(overrides: Partial<AnnotationDeps> = {}): AnnotationDeps {
  return {
    browserForTab: vi.fn().mockReturnValue(makeBrowserState()),
    updateBrowserTab: vi.fn(),
    startBrowserRequest: vi.fn().mockReturnValue(1),
    applyBrowserView: vi.fn(),
    setBrowserError: vi.fn(),
    baseUrl: "https://api.example.com",
    conversationId: "conv1",
    addComposerAnnotation: vi.fn(),
    ...overrides,
  };
}

describe("createBrowserAnnotation", () => {
  describe("setBrowserMode", () => {
    it("switches to annotate mode", () => {
      const updateBrowserTab = vi.fn();
      const { setBrowserMode } = createBrowserAnnotation(makeDeps({ updateBrowserTab }));
      setBrowserMode("browser:b1", "annotate");
      expect(updateBrowserTab).toHaveBeenCalledOnce();
      const [, updater] = updateBrowserTab.mock.calls[0];
      const result = updater(makeBrowserState({ mode: "browse" }));
      expect(result.mode).toBe("annotate");
    });

    it("switches to browse mode and clears selected node", () => {
      const updateBrowserTab = vi.fn();
      const { setBrowserMode } = createBrowserAnnotation(makeDeps({ updateBrowserTab }));
      setBrowserMode("browser:b1", "browse");
      const [, updater] = updateBrowserTab.mock.calls[0];
      const result = updater(makeBrowserState({ mode: "annotate", selectedNodeId: "n1", annotationDraft: "draft" }));
      expect(result.mode).toBe("browse");
      expect(result.selectedNodeId).toBeUndefined();
      expect(result.annotationDraft).toBe("");
    });
  });

  describe("selectBrowserElement", () => {
    it("selects a node and stores element metadata", () => {
      const updateBrowserTab = vi.fn();
      const { selectBrowserElement } = createBrowserAnnotation(makeDeps({ updateBrowserTab }));
      selectBrowserElement("browser:b1", "n1", { node_id: "n1", text: "hello" });
      const [, updater] = updateBrowserTab.mock.calls[0];
      const result = updater(makeBrowserState());
      expect(result.selectedNodeId).toBe("n1");
      expect(result.elementMetadata["n1"]).toEqual({ node_id: "n1", text: "hello" });
      expect(result.error).toBeUndefined();
    });

    it("does not store element metadata when node_id is missing", () => {
      const updateBrowserTab = vi.fn();
      const { selectBrowserElement } = createBrowserAnnotation(makeDeps({ updateBrowserTab }));
      selectBrowserElement("browser:b1", "n1");
      const [, updater] = updateBrowserTab.mock.calls[0];
      const result = updater(makeBrowserState({ elementMetadata: { existing: { node_id: "existing", text: "keep" } } }));
      expect(result.selectedNodeId).toBe("n1");
      expect(result.elementMetadata).toEqual({ existing: { node_id: "existing", text: "keep" } });
    });
  });

  describe("updateAnnotationDraft", () => {
    it("updates the annotation draft text", () => {
      const updateBrowserTab = vi.fn();
      const { updateAnnotationDraft } = createBrowserAnnotation(makeDeps({ updateBrowserTab }));
      updateAnnotationDraft("browser:b1", "new draft");
      const [, updater] = updateBrowserTab.mock.calls[0];
      const result = updater(makeBrowserState({ annotationDraft: "old" }));
      expect(result.annotationDraft).toBe("new draft");
    });
  });

  describe("addBrowserTextSelection", () => {
    it("does nothing when browser is undefined", () => {
      const addComposerAnnotation = vi.fn();
      const { addBrowserTextSelection } = createBrowserAnnotation(makeDeps({
        browserForTab: vi.fn().mockReturnValue(undefined),
        addComposerAnnotation,
      }));
      addBrowserTextSelection("browser:b1", { text: "selected text" });
      expect(addComposerAnnotation).not.toHaveBeenCalled();
    });

    it("does nothing when selection text is empty", () => {
      const addComposerAnnotation = vi.fn();
      const { addBrowserTextSelection } = createBrowserAnnotation(makeDeps({ addComposerAnnotation }));
      addBrowserTextSelection("browser:b1", { text: "  " });
      expect(addComposerAnnotation).not.toHaveBeenCalled();
    });

    it("calls addComposerAnnotation with selection data", () => {
      const addComposerAnnotation = vi.fn();
      const { addBrowserTextSelection } = createBrowserAnnotation(makeDeps({ addComposerAnnotation }));
      addBrowserTextSelection("browser:b1", { text: "selected text", node_id: "n1" });
      expect(addComposerAnnotation).toHaveBeenCalledOnce();
    });
  });

  describe("saveBrowserAnnotation", () => {
    it("returns early when no node is selected", async () => {
      const setBrowserError = vi.fn();
      const { saveBrowserAnnotation } = createBrowserAnnotation(makeDeps({
        browserForTab: vi.fn().mockReturnValue(makeBrowserState({ selectedNodeId: undefined })),
        setBrowserError,
      }));
      await saveBrowserAnnotation("browser:b1");
      expect(setBrowserError).not.toHaveBeenCalled();
    });

    it("returns early when draft is empty", async () => {
      const setBrowserError = vi.fn();
      const { saveBrowserAnnotation } = createBrowserAnnotation(makeDeps({
        browserForTab: vi.fn().mockReturnValue(makeBrowserState({ selectedNodeId: "n1", annotationDraft: "  " })),
        setBrowserError,
      }));
      await saveBrowserAnnotation("browser:b1");
      expect(setBrowserError).not.toHaveBeenCalled();
    });
  });

  describe("activateBrowserElement", () => {
    it("returns early when browser is undefined", async () => {
      const deps = makeDeps({ browserForTab: vi.fn().mockReturnValue(undefined) });
      const { activateBrowserElement } = createBrowserAnnotation(deps);
      await expect(activateBrowserElement("browser:b1", "n1", { width: 1024, height: 720 })).resolves.toBeUndefined();
      expect(deps.startBrowserRequest).not.toHaveBeenCalled();
    });

    it("returns early when baseUrl is empty", async () => {
      const deps = makeDeps({ baseUrl: "" });
      const { activateBrowserElement } = createBrowserAnnotation(deps);
      await expect(activateBrowserElement("browser:b1", "n1", { width: 1024, height: 720 })).resolves.toBeUndefined();
    });
  });
});
