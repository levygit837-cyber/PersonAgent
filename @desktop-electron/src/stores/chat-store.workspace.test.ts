import { beforeEach, describe, expect, it, vi } from "vitest";
import { getConversation, streamChatCompletion } from "../api/client";
import { emptySessionUsage } from "../types/chat";
import { useAppStore } from "./app-store";
import { useChatStore } from "./chat-store";

const apiMocks = vi.hoisted(() => ({
  getConversation: vi.fn(),
  streamChatCompletion: vi.fn(),
}));

vi.mock("../api/client", () => ({
  approvePlan: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
  getConversation: apiMocks.getConversation,
  rejectTool: vi.fn(),
  streamApproveTool: vi.fn(),
  streamChatCompletion: apiMocks.streamChatCompletion,
  streamTeamChat: vi.fn(),
}));

describe("chat workspace routing", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete window.personAgent;
    apiMocks.getConversation.mockReset();
    apiMocks.streamChatCompletion.mockReset();
    apiMocks.getConversation.mockResolvedValue({
      id: "conversation-eval",
      title: "Eval Session",
      messages: [],
      created_at: "2026-04-27T00:00:00Z",
      updated_at: "2026-04-27T00:00:00Z",
    });
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/workspaces/WebPilot",
      recentWorkspaces: ["/workspaces/WebPilot"],
      convWorkspaceMap: {
        "conversation-eval": "/workspaces/Eval",
      },
      provider: "llama",
      selectedModelId: "local-model",
      reasoningPreset: "low",
      teamMode: false,
    });
    useChatStore.setState({
      messages: [],
      conversationId: undefined,
      conversationTitle: undefined,
      error: undefined,
      isStreaming: false,
      isFinalizing: false,
      loadingConversationId: undefined,
      activeController: undefined,
      activeAgentId: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
    });
  });

  it("runs /clear locally instead of sending it to the model", async () => {
    useChatStore.setState({
      conversationId: "conversation-eval",
      messages: [
        {
          id: "user-1",
          role: "user",
          label: "You",
          content: "old",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [],
          teamEvents: [],
          parts: [],
          isStreaming: false,
          isReasoningStreaming: false,
        },
      ],
    });

    await useChatStore.getState().sendMessage("/clear");

    expect(vi.mocked(streamChatCompletion)).not.toHaveBeenCalled();
    expect(useChatStore.getState().messages).toEqual([]);
    expect(useChatStore.getState().conversationId).toBeUndefined();
  });

  it("runs model and effort commands locally with a command response", async () => {
    await useChatStore.getState().sendMessage("/effort high");
    await useChatStore.getState().sendMessage("/model codex:gpt-5.5");

    expect(useAppStore.getState().reasoningPreset).toBe("high");
    expect(useAppStore.getState().provider).toBe("codex");
    expect(useAppStore.getState().selectedModelId).toBe("gpt-5.5");
    expect(vi.mocked(streamChatCompletion)).not.toHaveBeenCalled();
    expect(useChatStore.getState().messages.some((message) => message.content.includes("Reasoning effort changed"))).toBe(true);
    expect(useChatStore.getState().messages.some((message) => message.content.includes("Model changed"))).toBe(true);
  });

  it("opens the skills workspace locally", async () => {
    await useChatStore.getState().sendMessage("/skills");

    expect(useAppStore.getState().section).toBe("skills");
    expect(vi.mocked(streamChatCompletion)).not.toHaveBeenCalled();
  });

  it("forwards model-visible built-in commands to the chat stream", async () => {
    apiMocks.streamChatCompletion.mockImplementation(() => emptyStream());

    await useChatStore.getState().sendMessage("/plan inspect this change");

    expect(vi.mocked(streamChatCompletion)).toHaveBeenCalled();
  });

  it("switches the active workspace before loading a mapped conversation", async () => {
    await useChatStore.getState().loadConversation("conversation-eval");

    expect(vi.mocked(getConversation)).toHaveBeenCalledWith("http://localhost:8000", "conversation-eval");
    expect(useAppStore.getState().selectedWorkspace).toBe("/workspaces/Eval");
    expect(useAppStore.getState().recentWorkspaces[0]).toBe("/workspaces/Eval");
    expect(useChatStore.getState().conversationId).toBe("conversation-eval");
  });

  it("does not wait for Electron settings persistence before fetching the conversation", async () => {
    const settingsSet = vi.fn(() => new Promise<boolean>(() => undefined));
    window.personAgent = {
      platform: "linux",
      window: {
        minimize: vi.fn(),
        maximizeToggle: vi.fn(),
        close: vi.fn(),
        isMaximized: vi.fn(),
      },
      settings: {
        get: vi.fn(),
        set: settingsSet,
      },
      dialog: {
        selectWorkspace: vi.fn(),
      },
      fs: {
        readDir: vi.fn(),
      },
    } as unknown as Window["personAgent"];

    await useChatStore.getState().loadConversation("conversation-eval");

    expect(settingsSet).toHaveBeenCalledWith("personagent_selected_workspace", "/workspaces/Eval");
    expect(vi.mocked(getConversation)).toHaveBeenCalledWith("http://localhost:8000", "conversation-eval");
    expect(useChatStore.getState().conversationId).toBe("conversation-eval");
  });

  it("does not enqueue duplicate fetches while the same session is opening", async () => {
    let resolveDetail: (value: Awaited<ReturnType<typeof getConversation>>) => void = () => undefined;
    apiMocks.getConversation.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveDetail = resolve;
        }),
    );

    const firstLoad = useChatStore.getState().loadConversation("conversation-eval");
    const secondLoad = useChatStore.getState().loadConversation("conversation-eval");

    await Promise.resolve();

    expect(useChatStore.getState().loadingConversationId).toBe("conversation-eval");
    expect(vi.mocked(getConversation)).toHaveBeenCalledTimes(1);

    resolveDetail({
      id: "conversation-eval",
      title: "Eval Session",
      messages: [],
      created_at: "2026-04-27T00:00:00Z",
      updated_at: "2026-04-27T00:00:00Z",
    });

    await Promise.all([firstLoad, secondLoad]);

    expect(useChatStore.getState().loadingConversationId).toBeUndefined();
    expect(useChatStore.getState().conversationId).toBe("conversation-eval");
  });
});

async function* emptyStream() {
  return;
}
