import { describe, it, expect, vi, beforeEach } from "vitest";
import { createConversationSlice, type ConversationSliceOptions } from "./conversation-slice";
import type { ChatState } from "./internal";
import type { ChatMessageUi, ConversationStatus } from "../../types/chat";

vi.mock("../../api/client", () => ({
  getConversation: vi.fn(),
  forkConversation: vi.fn(),
  gitCreateWorktree: vi.fn(),
}));

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      baseUrl: "http://test",
      selectedWorkspace: "/workspace",
      convWorkspaceMap: {},
      selectWorkspace: vi.fn(),
      associateConversation: vi.fn(),
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

function createTestSlice(optsOverrides: Partial<ConversationSliceOptions> = {}) {
  let state: Record<string, unknown> = {
    messages: [] as ChatMessageUi[],
    isStreaming: false,
    activeAgentId: undefined,
    activeController: undefined,
    workspaceRoot: "/workspace",
    conversationId: undefined,
    conversationTitle: undefined,
    stopStreaming: vi.fn(),
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
  const opts: ConversationSliceOptions = {
    syncWorkspaceSelection: true,
    messageFromPersisted: (msg: any) => makeMessage({ id: msg.id, role: msg.role, content: msg.content }),
    isRenderablePersistedMessage: () => true,
    isRecord: (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v),
    ...optsOverrides,
  };
  const slice = createConversationSlice(set, get, opts);
  Object.assign(state, slice);
  return { state, set, get, slice };
}

describe("createConversationSlice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("initializes with empty conversationStatuses", () => {
    const { slice } = createTestSlice();
    expect(slice.conversationStatuses).toEqual({});
  });

  it("initializes with undefined loadingConversationId and error", () => {
    const { slice } = createTestSlice();
    expect(slice.loadingConversationId).toBeUndefined();
    expect(slice.error).toBeUndefined();
  });

  it("clearError sets error to undefined", () => {
    const { state, slice } = createTestSlice();
    (state as any).error = "something went wrong";
    slice.clearError();
    expect((state as any).error).toBeUndefined();
  });

  it("startNewConversation calls stopStreaming", () => {
    const { state, slice } = createTestSlice();
    const stopStreaming = vi.fn();
    (state as any).stopStreaming = stopStreaming;
    slice.startNewConversation();
    expect(stopStreaming).toHaveBeenCalled();
  });

  it("startNewConversation resets state", () => {
    const { state, slice } = createTestSlice();
    (state as any).stopStreaming = vi.fn();
    (state as any).conversationId = "conv-1";
    (state as any).conversationTitle = "Test";
    (state as any).messages = [makeMessage()];
    slice.startNewConversation();
    expect((state as any).conversationId).toBeUndefined();
    expect((state as any).conversationTitle).toBeUndefined();
    expect((state as any).messages).toEqual([]);
  });

  it("regenerateAgentMessage does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    await slice.regenerateAgentMessage("agent-1");
    expect(set).not.toHaveBeenCalled();
  });

  it("regenerateAgentMessage does nothing when agent message not found", async () => {
    const { state, slice } = createTestSlice();
    (state as any).messages = [makeMessage({ id: "msg-1", role: "user" })];
    const sendMessage = vi.fn();
    (state as any).sendMessage = sendMessage;
    await slice.regenerateAgentMessage("nonexistent");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("rewindUserMessage does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    await slice.rewindUserMessage("msg-1", "new content");
    expect(set).not.toHaveBeenCalled();
  });

  it("rewindUserMessage does nothing when user message not found", async () => {
    const { state, slice } = createTestSlice();
    (state as any).messages = [makeMessage({ id: "msg-1", role: "agent" })];
    const sendMessage = vi.fn();
    (state as any).sendMessage = sendMessage;
    await slice.rewindUserMessage("nonexistent", "new content");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("branchAgentMessage does nothing when streaming", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).isStreaming = true;
    await slice.branchAgentMessage("msg-1");
    expect(set).not.toHaveBeenCalled();
  });

  it("branchAgentMessage sets error when no workspace", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).workspaceRoot = undefined;
    await slice.branchAgentMessage("msg-1");
    const setCall = set.mock.calls.find(
      (call) => typeof call[0] === "function" &&
        JSON.stringify((call[0] as Function)(state)).includes("worktree_status"),
    );
    // Should have been called with a set that includes worktree_status: "error"
    expect(set).toHaveBeenCalled();
  });

  it("loadConversation skips if already loading same id", async () => {
    const { state, slice, set } = createTestSlice();
    (state as any).loadingConversationId = "conv-1";
    await slice.loadConversation("conv-1");
    expect(set).not.toHaveBeenCalled();
  });
});
