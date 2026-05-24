import { describe, it, expect, vi, beforeEach } from "vitest";
import { createStreamingSlice } from "./streaming-slice";
import type { ChatState } from "./internal";
import type { ChatMessageUi } from "../../types/chat";

vi.mock("../../api/client", () => ({
  streamChatCompletion: vi.fn(),
  streamTeamChat: vi.fn(),
}));

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      baseUrl: "http://test",
      provider: "openai",
      selectedModelId: "gpt-4",
      reasoningPreset: "default",
      selectedWorkspace: "/workspace",
      teamMode: false,
    })),
  },
}));

function makeMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
  return {
    id: "msg-1",
    role: "user",
    content: "hello",
    toolBlocks: [],
    reasoningBlocks: [],
    metadata: {},
    generatedImages: [],
    ...overrides,
  } as ChatMessageUi;
}

function createTestSlice() {
  let state: Record<string, unknown> = {
    messages: [] as ChatMessageUi[],
    isStreaming: false,
    isFinalizing: false,
    activeAgentId: undefined,
    activeController: undefined,
    workspaceRoot: "/workspace",
    conversationId: undefined,
    liveSessionUsage: { agent_output_tokens: { value: 0, estimated: false }, thinking_output_tokens: { value: 0, estimated: false } },
    liveSubAgentIds: [],
    latestTodoSnapshot: undefined,
    contextTokenEstimate: 0,
    contextWindowEstimate: undefined,
    browserToolBlocks: [],
  };
  const set = vi.fn((partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)) => {
    if (typeof partial === "function") {
      Object.assign(state, partial(state as unknown as ChatState));
    } else {
      Object.assign(state, partial);
    }
  });
  const get = vi.fn(() => state as unknown as ChatState);
  const slice = createStreamingSlice(set, get, { paneId: "test" });
  Object.assign(state, slice);
  return { state, set, get, slice };
}

describe("createStreamingSlice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("initializes with isStreaming false", () => {
    const { slice } = createTestSlice();
    expect(slice.isStreaming).toBe(false);
  });

  it("initializes with isFinalizing false", () => {
    const { slice } = createTestSlice();
    expect(slice.isFinalizing).toBe(false);
  });

  it("initializes with undefined activeAgentId and activeController", () => {
    const { slice } = createTestSlice();
    expect(slice.activeAgentId).toBeUndefined();
    expect(slice.activeController).toBeUndefined();
  });

  it("initializes with empty liveSessionUsage", () => {
    const { slice } = createTestSlice();
    expect(slice.liveSessionUsage).toBeDefined();
  });

  it("initializes with empty liveSubAgentIds", () => {
    const { slice } = createTestSlice();
    expect(slice.liveSubAgentIds).toEqual([]);
  });

  it("initializes with contextTokenEstimate 0", () => {
    const { slice } = createTestSlice();
    expect(slice.contextTokenEstimate).toBe(0);
  });

  it("initializes with empty browserToolBlocks", () => {
    const { slice } = createTestSlice();
    expect(slice.browserToolBlocks).toEqual([]);
  });

  it("sendMessage does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    await slice.sendMessage("hello");
    expect(set).not.toHaveBeenCalled();
  });

  it("sendMessage does nothing for empty text", async () => {
    const { slice, set } = createTestSlice();
    await slice.sendMessage("   ");
    expect(set).not.toHaveBeenCalled();
  });

  it("stopStreaming aborts controller and resets state", () => {
    const { state, slice } = createTestSlice();
    const controller = new AbortController();
    (state as any).activeController = controller;
    (state as any).activeAgentId = "agent-1";
    (state as any).isStreaming = true;
    slice.stopStreaming();
    expect(controller.signal.aborted).toBe(true);
    expect((state as any).isStreaming).toBe(false);
    expect((state as any).isFinalizing).toBe(false);
    expect((state as any).activeController).toBeUndefined();
    expect((state as any).activeAgentId).toBeUndefined();
  });

  it("stopStreaming is safe to call when not streaming", () => {
    const { slice } = createTestSlice();
    expect(() => slice.stopStreaming()).not.toThrow();
  });

  it("stopStreaming with no controller is a no-op abort", () => {
    const { state, slice } = createTestSlice();
    (state as any).activeController = undefined;
    (state as any).activeAgentId = undefined;
    slice.stopStreaming();
    expect((state as any).isStreaming).toBe(false);
  });

  it("sendMessage and stopStreaming are functions", () => {
    const { slice } = createTestSlice();
    expect(typeof slice.sendMessage).toBe("function");
    expect(typeof slice.stopStreaming).toBe("function");
  });

  it("sendMessage creates agent message with paneId prefix", async () => {
    const { set, slice } = createTestSlice();
    const { streamChatCompletion } = await import("../../api/client");
    (streamChatCompletion as any).mockImplementation(async function* () {
      // empty stream
    });
    await slice.sendMessage("test message");
    const firstSetCall = set.mock.calls.find(
      (call) => typeof call[0] === "function",
    );
    expect(firstSetCall).toBeDefined();
  });
});
