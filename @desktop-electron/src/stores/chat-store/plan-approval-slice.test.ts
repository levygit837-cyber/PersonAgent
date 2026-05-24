import { describe, it, expect, vi, beforeEach } from "vitest";
import { createPlanApprovalSlice } from "./plan-approval-slice";
import type { ChatState } from "./internal";

vi.mock("../../api/client", () => ({
  approvePlan: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
}));

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      baseUrl: "http://test",
    })),
  },
}));

function createTestSlice() {
  let state: Record<string, unknown> = {
    messages: [],
    isStreaming: false,
    isProcessingPlanDecision: false,
    pendingPlanApproval: undefined,
    error: undefined,
    conversationId: undefined,
    sendMessage: vi.fn(),
  };
  const set = vi.fn((partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)) => {
    if (typeof partial === "function") {
      Object.assign(state, partial(state as unknown as ChatState));
    } else {
      Object.assign(state, partial);
    }
  });
  const get = vi.fn(() => state as unknown as ChatState);
  const slice = createPlanApprovalSlice(set, get);
  Object.assign(state, slice);
  return { state, set, get, slice };
}

describe("createPlanApprovalSlice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("initializes with isProcessingPlanDecision false", () => {
    const { slice } = createTestSlice();
    expect(slice.isProcessingPlanDecision).toBe(false);
  });

  it("approvePendingPlan is a function", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.approvePendingPlan).toBe("function");
  });

  it("continuePendingPlan is a function", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.continuePendingPlan).toBe("function");
  });

  it("cancelPendingPlan is a function", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.cancelPendingPlan).toBe("function");
  });

  it("approvePendingPlan does nothing when no pending approval", async () => {
    const { slice, set } = createTestSlice();
    await slice.approvePendingPlan();
    expect(set).not.toHaveBeenCalled();
  });

  it("approvePendingPlan does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    await slice.approvePendingPlan();
    expect(set).not.toHaveBeenCalled();
  });

  it("approvePendingPlan does nothing when already processing", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isProcessingPlanDecision = true;
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    await slice.approvePendingPlan();
    expect(set).not.toHaveBeenCalled();
  });

  it("approvePendingPlan calls approvePlan API", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    const { approvePlan } = await import("../../api/client");
    (approvePlan as any).mockResolvedValue({ plan_status: "approved" });
    await slice.approvePendingPlan("looks good");
    expect(approvePlan).toHaveBeenCalledWith("http://test", {
      conversationId: "c1",
      approvalId: "a1",
      feedback: "looks good",
    });
    expect(set).toHaveBeenCalled();
  });

  it("approvePendingPlan sets error on failure", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    const { approvePlan } = await import("../../api/client");
    (approvePlan as any).mockRejectedValue(new Error("network error"));
    await slice.approvePendingPlan();
    expect((state as any).error).toBeDefined();
    expect((state as any).isProcessingPlanDecision).toBe(false);
  });

  it("continuePendingPlan does nothing when no pending approval", async () => {
    const { slice, set } = createTestSlice();
    await slice.continuePendingPlan();
    expect(set).not.toHaveBeenCalled();
  });

  it("continuePendingPlan calls continuePlan API", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    const { continuePlan } = await import("../../api/client");
    (continuePlan as any).mockResolvedValue({ plan_status: "draft" });
    await slice.continuePendingPlan("need more detail");
    expect(continuePlan).toHaveBeenCalledWith("http://test", {
      conversationId: "c1",
      approvalId: "a1",
      feedback: "need more detail",
    });
  });

  it("cancelPendingPlan does nothing when no pending approval", async () => {
    const { slice, set } = createTestSlice();
    await slice.cancelPendingPlan();
    expect(set).not.toHaveBeenCalled();
  });

  it("cancelPendingPlan calls cancelPlan API", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    const { cancelPlan } = await import("../../api/client");
    (cancelPlan as any).mockResolvedValue({});
    await slice.cancelPendingPlan("no thanks");
    expect(cancelPlan).toHaveBeenCalledWith("http://test", {
      conversationId: "c1",
      approvalId: "a1",
      feedback: "no thanks",
    });
  });

  it("cancelPendingPlan resets isProcessingPlanDecision on error", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingPlanApproval = { conversationId: "c1", approvalId: "a1" };
    const { cancelPlan } = await import("../../api/client");
    (cancelPlan as any).mockRejectedValue(new Error("fail"));
    await slice.cancelPendingPlan();
    expect((state as any).isProcessingPlanDecision).toBe(false);
  });
});
