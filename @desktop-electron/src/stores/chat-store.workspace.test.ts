import { beforeEach, describe, expect, it, vi } from "vitest";
import { getConversation, streamChatCompletion } from "../api/client";
import { emptySessionUsage, type ChatMessageUi } from "../types/chat";
import { useAppStore } from "./app-store";
import { useChatStore } from "./chat-store";

const apiMocks = vi.hoisted(() => ({
  forkConversation: vi.fn(),
  getConversation: vi.fn(),
  gitCreateWorktree: vi.fn(),
  streamChatCompletion: vi.fn(),
}));

vi.mock("../api/client", () => ({
  approvePlan: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
  forkConversation: apiMocks.forkConversation,
  getConversation: apiMocks.getConversation,
  gitCreateWorktree: apiMocks.gitCreateWorktree,
  rejectTool: vi.fn(),
  streamApproveTool: vi.fn(),
  streamChatCompletion: apiMocks.streamChatCompletion,
  streamTeamChat: vi.fn(),
}));

describe("chat workspace routing", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete window.personAgent;
    apiMocks.forkConversation.mockReset();
    apiMocks.getConversation.mockReset();
    apiMocks.gitCreateWorktree.mockReset();
    apiMocks.streamChatCompletion.mockReset();
    apiMocks.forkConversation.mockResolvedValue({
      id: "conversation-fork",
      title: "Eval Session",
      messages: [],
      created_at: "2026-04-27T00:00:00Z",
      updated_at: "2026-04-27T00:00:00Z",
    });
    apiMocks.gitCreateWorktree.mockResolvedValue({
      success: true,
      branch: "personagent/message",
      path: "/workspaces/PersonAgent-message",
    });
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

  it("forks the persisted prefix before rewinding a user message", async () => {
    apiMocks.streamChatCompletion.mockImplementation(() => emptyStream());
    useChatStore.setState({
      conversationId: "conversation-eval",
      conversationTitle: "Eval Session",
      messages: [
        chatMessage({ id: "user-1", role: "user", content: "First prompt" }),
        chatMessage({ id: "agent-1", role: "agent", content: "First answer" }),
        chatMessage({
          id: "user-2",
          role: "user",
          content: "Original prompt",
          metadata: {
            context_attachments: [
              {
                type: "file",
                label: "@File",
                display_path: "src/app.ts",
              },
            ],
          },
        }),
        chatMessage({ id: "agent-2", role: "agent", content: "Second answer" }),
      ],
    });

    await useChatStore.getState().rewindUserMessage("user-2", "Edited prompt");

    expect(apiMocks.forkConversation).toHaveBeenCalledWith("http://localhost:8000", "conversation-eval", {
      title: "Eval Session",
      workspaceRoot: "/workspaces/WebPilot",
      messages: [
        expect.objectContaining({ role: "user", content: "First prompt" }),
        expect.objectContaining({ role: "assistant", content: "First answer" }),
      ],
    });
    expect(vi.mocked(streamChatCompletion)).toHaveBeenCalled();
    const payload = vi.mocked(streamChatCompletion).mock.calls[0][1];
    expect(payload).toMatchObject({
      conversation_id: "conversation-fork",
      message: "Edited prompt",
      context_attachments: [
        expect.objectContaining({
          type: "file",
          display_path: "src/app.ts",
        }),
      ],
    });
    expect(useChatStore.getState().messages.map((message) => message.content)).toEqual([
      "First prompt",
      "First answer",
      "Edited prompt",
      "",
    ]);
  });

  it("creates a worktree for an agent message and switches to it", async () => {
    useChatStore.setState({
      conversationId: "conversation-eval",
      messages: [chatMessage({ id: "agent-1", role: "agent", content: "Ready to branch" })],
    });

    await useChatStore.getState().branchAgentMessage("agent-1");

    expect(apiMocks.gitCreateWorktree).toHaveBeenCalledWith(
      "http://localhost:8000",
      "/workspaces/WebPilot",
      expect.objectContaining({
        sourceMessageId: "agent-1",
      }),
    );
    expect(useAppStore.getState().selectedWorkspace).toBe("/workspaces/PersonAgent-message");
    expect(useChatStore.getState().messages[0].metadata).toMatchObject({
      worktree_status: "ready",
      worktree_branch: "personagent/message",
      worktree_path: "/workspaces/PersonAgent-message",
    });
  });
});

async function* emptyStream() {
  return;
}

function chatMessage(overrides: Partial<ChatMessageUi>): ChatMessageUi {
  return {
    id: "message",
    role: "user",
    label: "You",
    content: "",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
    ...overrides,
  };
}
