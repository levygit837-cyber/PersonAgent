import { describe, expect, it, vi } from "vitest";
import { useBrowserCooperation, type CooperationDeps } from "./use-browser-cooperation";
import { renderHook } from "@testing-library/react";
import type { BrowserState, BrowserTab } from "../helpers/helpers";

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

function makeBrowserTab(overrides: Partial<BrowserTab> = {}): BrowserTab {
  return {
    id: "browser:b1",
    title: "Browser",
    closeable: true,
    browser: makeBrowserState(),
    ...overrides,
  };
}

function makeDeps(overrides: Partial<CooperationDeps> = {}): CooperationDeps {
  return {
    browserForTab: vi.fn().mockReturnValue(makeBrowserState()),
    updateBrowserTab: vi.fn(),
    setBrowserError: vi.fn(),
    cooperationSocketsRef: { current: {} },
    activeTab: makeBrowserTab(),
    baseUrl: "https://api.example.com",
    conversationId: "conv1",
    visible: true,
    approvePendingTool: vi.fn(),
    rejectPendingTool: vi.fn(),
    ...overrides,
  };
}

function makeMockSocket(overrides: Partial<{ send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> }> = {}): WebSocket {
  return {
    readyState: WebSocket.OPEN,
    send: overrides.send ?? vi.fn(),
    close: overrides.close ?? vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onopen: null,
    onclose: null,
    onerror: null,
    onmessage: null,
    binaryType: "blob",
    bufferedAmount: 0,
    extensions: "",
    protocol: "",
    url: "",
    CONNECTING: 0,
    OPEN: WebSocket.OPEN,
    CLOSING: 2,
    CLOSED: 3,
  } as unknown as WebSocket;
}

function renderCooperationHook(deps: CooperationDeps) {
  return renderHook(() => useBrowserCooperation(deps));
}

describe("useBrowserCooperation", () => {
  describe("applyBrowserCooperationPatch", () => {
    it("does nothing when cooperation is undefined", () => {
      const updateBrowserTab = vi.fn();
      const { result } = renderCooperationHook(makeDeps({ updateBrowserTab }));
      result.current.applyBrowserCooperationPatch("browser:b1", undefined);
      expect(updateBrowserTab).not.toHaveBeenCalled();
    });

    it("does nothing when updateBrowserTab would yield no view on current", () => {
      const updateBrowserTab = vi.fn();
      const { result } = renderCooperationHook(makeDeps({ updateBrowserTab }));
      result.current.applyBrowserCooperationPatch("browser:b1", { enabled: true });
      expect(updateBrowserTab).toHaveBeenCalledOnce();
    });

    it("calls updateBrowserTab with cooperation patch", () => {
      const updateBrowserTab = vi.fn();
      const { result } = renderCooperationHook(makeDeps({ updateBrowserTab }));
      result.current.applyBrowserCooperationPatch("browser:b1", { mode: "observe_only" });
      expect(updateBrowserTab).toHaveBeenCalledOnce();
    });
  });

  describe("setBrowserCooperationMode", () => {
    it("returns early when browser is undefined", async () => {
      const setBrowserError = vi.fn();
      const { result } = renderCooperationHook(makeDeps({
        browserForTab: vi.fn().mockReturnValue(undefined),
        setBrowserError,
      }));
      await expect(result.current.setBrowserCooperationMode("browser:b1", "observe_only")).resolves.toBeUndefined();
      expect(setBrowserError).not.toHaveBeenCalled();
    });

    it("returns early when baseUrl is empty", async () => {
      const setBrowserError = vi.fn();
      const { result } = renderCooperationHook(makeDeps({
        baseUrl: "",
        setBrowserError,
      }));
      await expect(result.current.setBrowserCooperationMode("browser:b1", "observe_only")).resolves.toBeUndefined();
    });

    it("returns early when conversationId is undefined", async () => {
      const setBrowserError = vi.fn();
      const { result } = renderCooperationHook(makeDeps({
        conversationId: undefined,
        setBrowserError,
      }));
      await expect(result.current.setBrowserCooperationMode("browser:b1", "observe_only")).resolves.toBeUndefined();
    });

    it("sends via WebSocket when socket is open", async () => {
      const mockSocket = makeMockSocket();
      const cooperationSocketsRef = { current: { b1: mockSocket } };
      const { result } = renderCooperationHook(makeDeps({ cooperationSocketsRef }));
      await result.current.setBrowserCooperationMode("browser:b1", "observe_only");
      expect(mockSocket.send).toHaveBeenCalledWith(
        JSON.stringify({ type: "mode.set", enabled: true, mode: "observe_only" }),
      );
    });

    it("turns off cooperation with mode off", async () => {
      const mockSocket = makeMockSocket();
      const cooperationSocketsRef = { current: { b1: mockSocket } };
      const browser = makeBrowserState();
      const { result } = renderCooperationHook(makeDeps({
        cooperationSocketsRef,
        browserForTab: vi.fn().mockReturnValue(browser),
      }));
      await result.current.setBrowserCooperationMode("browser:b1", "off");
      expect(mockSocket.send).toHaveBeenCalledWith(
        JSON.stringify({ type: "mode.set", enabled: false, mode: "observe_only" }),
      );
    });
  });

  describe("decideBrowserProposal", () => {
    it("returns early when browser is undefined", async () => {
      const { result } = renderCooperationHook(makeDeps({
        browserForTab: vi.fn().mockReturnValue(undefined),
      }));
      await expect(result.current.decideBrowserProposal("browser:b1", { proposal_id: "p1" }, "approve")).resolves.toBeUndefined();
    });

    it("returns early when proposal ID is empty", async () => {
      const { result } = renderCooperationHook(makeDeps());
      await expect(result.current.decideBrowserProposal("browser:b1", {}, "approve")).resolves.toBeUndefined();
    });

    it("sends approval via WebSocket and calls approve", async () => {
      const mockSocket = makeMockSocket();
      const cooperationSocketsRef = { current: { b1: mockSocket } };
      const approvePendingTool = vi.fn();
      const { result } = renderCooperationHook(makeDeps({ cooperationSocketsRef, approvePendingTool }));
      await result.current.decideBrowserProposal("browser:b1", { proposal_id: "p1" }, "approve");
      expect(mockSocket.send).toHaveBeenCalledWith(
        JSON.stringify({ type: "proposal.approve", proposal_id: "p1" }),
      );
      expect(approvePendingTool).toHaveBeenCalledOnce();
    });

    it("calls reject for deny decision", async () => {
      const mockSocket = makeMockSocket();
      const cooperationSocketsRef = { current: { b1: mockSocket } };
      const rejectPendingTool = vi.fn();
      const { result } = renderCooperationHook(makeDeps({ cooperationSocketsRef, rejectPendingTool }));
      await result.current.decideBrowserProposal("browser:b1", { proposal_id: "p1" }, "deny");
      expect(rejectPendingTool).toHaveBeenCalledOnce();
    });
  });

  describe("recordBrowserEvents", () => {
    it("returns early when browser is undefined", async () => {
      const { result } = renderCooperationHook(makeDeps({
        browserForTab: vi.fn().mockReturnValue(undefined),
      }));
      await expect(result.current.recordBrowserEvents("browser:b1", [{ kind: "click" }])).resolves.toBeUndefined();
    });

    it("returns early when events array is empty", async () => {
      const { result } = renderCooperationHook(makeDeps());
      await expect(result.current.recordBrowserEvents("browser:b1", [])).resolves.toBeUndefined();
    });

    it("returns early when baseUrl is empty", async () => {
      const { result } = renderCooperationHook(makeDeps({ baseUrl: "" }));
      await expect(result.current.recordBrowserEvents("browser:b1", [{ kind: "click" }])).resolves.toBeUndefined();
    });

    it("sends via WebSocket when socket is open", async () => {
      const mockSocket = makeMockSocket();
      const cooperationSocketsRef = { current: { b1: mockSocket } };
      const browser = makeBrowserState({ view: { cooperation: { enabled: true } } as any });
      const { result } = renderCooperationHook(makeDeps({
        cooperationSocketsRef,
        browserForTab: vi.fn().mockReturnValue(browser),
      }));
      const events = [{ kind: "click" }];
      await result.current.recordBrowserEvents("browser:b1", events);
      expect(mockSocket.send).toHaveBeenCalledWith(
        JSON.stringify({ type: "event_batch", events }),
      );
    });
  });
});
