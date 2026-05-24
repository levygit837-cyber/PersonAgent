import { describe, it, expect, vi, beforeEach } from "vitest";
import { createToolApprovalSlice } from "./tool-approval-slice";
import type { ChatState } from "./internal";

vi.mock("../../api/client", () => ({
  streamApproveTool: vi.fn(),
  rejectTool: vi.fn(),
}));

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      baseUrl: "http://test",
      selectedWorkspace: "/workspace",
    })),
  },
}));

function createTestSlice() {
  let state: Record<string, unknown> = {
    messages: [],
    isStreaming: false,
    isFinalizing: false,
    activeAgentId: undefined,
    activeController: undefined,
    pendingToolApproval: undefined,
    error: undefined,
    conversationId: undefined,
    liveSessionUsage: { agent_output_tokens: { value: 0, estimated: false }, thinking_output_tokens: { value: 0, estimated: false } },
    liveSubAgentIds: [],
    latestTodoSnapshot: undefined,
    contextTokenEstimate: 0,
    contextWindowEstimate: undefined,
    browserToolBlocks: [],
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
  const slice = createToolApprovalSlice(set, get);
  Object.assign(state, slice);
  return { state, set, get, slice };
}

describe("createToolApprovalSlice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("approvePendingTool is a function", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.approvePendingTool).toBe("function");
  });

  it("rejectPendingTool is a function", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.rejectPendingTool).toBe("function");
  });

  it("approvePendingTool does nothing when no pending approval", async () => {
    const { slice, set } = createTestSlice();
    await slice.approvePendingTool();
    expect(set).not.toHaveBeenCalled();
  });

  it("approvePendingTool does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
      toolCallId: "t1",
      argsHash: "h1",
    };
    await slice.approvePendingTool();
    expect(set).not.toHaveBeenCalled();
  });

  it("approvePendingTool sets streaming state and calls API", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
      toolCallId: "t1",
      argsHash: "h1",
    };
    const { streamApproveTool } = await import("../../api/client");
    (streamApproveTool as any).mockImplementation(async function* () {
      // empty stream
    });
    await slice.approvePendingTool();
    expect(streamApproveTool).toHaveBeenCalled();
    expect(set).toHaveBeenCalled();
  });

  it("approvePendingTool handles stream error gracefully", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
      toolCallId: "t1",
      argsHash: "h1",
    };
    const { streamApproveTool } = await import("../../api/client");
    (streamApproveTool as any).mockImplementation(async function* () {
      throw new Error("stream failed");
    });
    await slice.approvePendingTool();
    expect((state as any).error).toBeDefined();
  });

  it("rejectPendingTool does nothing when no pending approval", async () => {
    const { slice, set } = createTestSlice();
    await slice.rejectPendingTool();
    expect(set).not.toHaveBeenCalled();
  });

  it("rejectPendingTool does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
    };
    await slice.rejectPendingTool();
    expect(set).not.toHaveBeenCalled();
  });

  it("rejectPendingTool calls rejectTool API", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
    };
    const { rejectTool } = await import("../../api/client");
    (rejectTool as any).mockResolvedValue({});
    await slice.rejectPendingTool();
    expect(rejectTool).toHaveBeenCalledWith("http://test", {
      conversationId: "c1",
      approvalId: "a1",
    });
    expect((state as any).pendingToolApproval).toBeUndefined();
  });

  it("rejectPendingTool sends injected message when present", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
    };
    const { rejectTool } = await import("../../api/client");
    (rejectTool as any).mockResolvedValue({ injected_message: "tool rejected feedback" });
    await slice.rejectPendingTool();
    expect((state as any).sendMessage).toHaveBeenCalledWith("tool rejected feedback");
  });

  it("rejectPendingTool sets error on failure", async () => {
    const { state, slice } = createTestSlice();
    (state as any).pendingToolApproval = {
      conversationId: "c1",
      approvalId: "a1",
    };
    const { rejectTool } = await import("../../api/client");
    (rejectTool as any).mockRejectedValue(new Error("reject failed"));
    await slice.rejectPendingTool();
    expect((state as any).error).toBeDefined();
  });
});
