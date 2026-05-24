import {
  forkConversation,
  getConversation,
  gitCreateWorktree,
} from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useAppStore } from "../app-store";
import {
  emptySessionUsage,
  type ChatMessageUi,
  type ConversationStatus,
  type PersistedMessage,
  type PlanApprovalUi,
} from "../../types/chat";
import type { ChatSet, ChatGet } from "./internal";
import {
  browserToolBlocksFromMessages,
  contextAttachmentsFromMessage,
  conversationForkMessages,
  estimateConversationContextTokens,
  getEffectiveWorkspaceRoot,
  inferConversationStatus,
  latestContextWindowEstimate,
  latestTodoSnapshotFromMessages,
  previousUserMessageIndex,
  resetLiveTokenTotals,
  setAgentMessageActionState,
  setConversationStatus,
  worktreeSlug,
} from "./internal";

export interface ConversationSliceOptions {
  syncWorkspaceSelection: boolean;
  messageFromPersisted: (msg: PersistedMessage) => ChatMessageUi;
  isRenderablePersistedMessage: (msg: PersistedMessage) => boolean;
  isRecord: (value: unknown) => value is Record<string, unknown>;
}

export function createConversationSlice(
  set: ChatSet,
  get: ChatGet,
  opts: ConversationSliceOptions,
) {
  const { syncWorkspaceSelection, messageFromPersisted, isRenderablePersistedMessage, isRecord } = opts;

  return {
    conversationStatuses: {} as Record<string, ConversationStatus>,
    loadingConversationId: undefined as string | undefined,
    error: undefined as string | undefined,

    loadConversation: async (id: string, workspaceRoot?: string | null) => {
      if (get().loadingConversationId === id) return;
      if (get().isStreaming || get().activeAgentId || get().activeController) {
        get().stopStreaming();
      }
      set({ loadingConversationId: id, error: undefined });
      try {
        const appStore = useAppStore.getState();
        const mappedWorkspace =
          workspaceRoot?.trim() ||
          appStore.convWorkspaceMap[id]?.trim() ||
          get().workspaceRoot?.trim();
        if (mappedWorkspace) {
          set({ workspaceRoot: mappedWorkspace });
        }
        if (syncWorkspaceSelection && mappedWorkspace && mappedWorkspace !== appStore.selectedWorkspace) {
          await appStore.selectWorkspace(mappedWorkspace);
        }

        const detail = await getConversation(useAppStore.getState().baseUrl, id);
        if (get().loadingConversationId !== id) return;
        const loadedMessages = detail.messages
          .filter((message) => message.role !== "system")
          .filter(isRenderablePersistedMessage)
          .map(messageFromPersisted);

        let pendingPlanApproval: PlanApprovalUi | undefined;
        for (let i = loadedMessages.length - 1; i >= 0; i--) {
          const msg = loadedMessages[i];
          if (msg.role === "agent") {
            const artifact = msg.metadata?.plan_approval;
            if (isRecord(artifact) && artifact.planStatus === "awaiting_approval") {
              pendingPlanApproval = {
                conversationId: String(artifact.conversationId ?? detail.id),
                approvalId: String(artifact.approvalId ?? ""),
                planId: String(artifact.planId ?? ""),
                planContent: String(artifact.planContent ?? ""),
                planStatus: String(artifact.planStatus ?? "awaiting_approval"),
                feedback: typeof artifact.feedback === "string" ? artifact.feedback : null,
              };
              break;
            }
          }
        }

        set({
          conversationId: detail.id,
          conversationTitle: detail.title,
          messages: loadedMessages,
          pendingPlanApproval,
          composerPlanMode: false,
          pendingToolApproval: undefined,
          nextStepSuggestion: undefined,
          composerAnnotations: [],
          liveSessionUsage: emptySessionUsage(),
          liveSubAgentIds: [],
          latestTodoSnapshot: latestTodoSnapshotFromMessages(loadedMessages),
          contextTokenEstimate: estimateConversationContextTokens(loadedMessages),
          contextWindowEstimate: latestContextWindowEstimate(loadedMessages),
          browserToolBlocks: browserToolBlocksFromMessages(loadedMessages),
          isFinalizing: false,
          loadingConversationId: undefined,
          error: undefined,
        });
        setConversationStatus(set, detail.id, inferConversationStatus(detail.messages));
        resetLiveTokenTotals();
      } catch (error) {
        if (get().loadingConversationId === id) {
          set({ error: errorMessage(error) });
        }
      } finally {
        set((state) => ({
          loadingConversationId:
            state.loadingConversationId === id ? undefined : state.loadingConversationId,
        }));
      }
    },

    startNewConversation: () => {
      get().stopStreaming();
      set({
        messages: [],
        composerAnnotations: [],
        conversationId: undefined,
        conversationTitle: undefined,
        pendingPlanApproval: undefined,
        composerPlanMode: false,
        pendingToolApproval: undefined,
        nextStepSuggestion: undefined,
        liveSessionUsage: emptySessionUsage(),
        liveSubAgentIds: [],
        latestTodoSnapshot: undefined,
        contextTokenEstimate: 0,
        contextWindowEstimate: undefined,
        browserToolBlocks: [],
        workspaceRoot: syncWorkspaceSelection ? get().workspaceRoot : get().workspaceRoot,
        isFinalizing: false,
        loadingConversationId: undefined,
        error: undefined,
      });
      resetLiveTokenTotals();
    },

    regenerateAgentMessage: async (messageId: string) => {
      if (get().isStreaming) return;
      const state = get();
      const agentIndex = state.messages.findIndex(
        (message) => message.id === messageId && message.role === "agent",
      );
      if (agentIndex < 0) return;
      const userIndex = previousUserMessageIndex(state.messages, agentIndex);
      if (userIndex < 0) return;
      const userMessage = state.messages[userIndex];
      await replayUserMessageFromIndex(userIndex, userMessage, userMessage.content, set, get);
    },

    rewindUserMessage: async (messageId: string, content: string) => {
      if (get().isStreaming) return;
      const state = get();
      const userIndex = state.messages.findIndex(
        (message) => message.id === messageId && message.role === "user",
      );
      if (userIndex < 0) return;
      const userMessage = state.messages[userIndex];
      await replayUserMessageFromIndex(userIndex, userMessage, content, set, get);
    },

    branchAgentMessage: async (messageId: string) => {
      if (get().isStreaming) return;
      const app = useAppStore.getState();
      const workspaceRoot = getEffectiveWorkspaceRoot(get());
      if (!workspaceRoot) {
        setAgentMessageActionState(set, messageId, {
          worktree_status: "error",
          worktree_error: "No workspace selected.",
        });
        return;
      }

      setAgentMessageActionState(set, messageId, {
        worktree_status: "running",
        worktree_error: undefined,
      });
      try {
        const result = await gitCreateWorktree(app.baseUrl, workspaceRoot, {
          name: worktreeSlug(get().conversationId, messageId),
          sourceMessageId: messageId,
        });
        set({ workspaceRoot: result.path });
        if (syncWorkspaceSelection) {
          await useAppStore.getState().selectWorkspace(result.path);
        }
        setAgentMessageActionState(set, messageId, {
          worktree_status: "ready",
          worktree_branch: result.branch,
          worktree_path: result.path,
          worktree_error: undefined,
        });
        window.dispatchEvent(new CustomEvent("personagent:workspace-changed"));
      } catch (error) {
        setAgentMessageActionState(set, messageId, {
          worktree_status: "error",
          worktree_error: errorMessage(error),
        });
      }
    },

    clearError: () => set({ error: undefined }),
  };
}

// ---------------------------------------------------------------------------
// Conversation replay helpers (used only by conversation actions)
// ---------------------------------------------------------------------------

async function replayUserMessageFromIndex(
  userIndex: number,
  userMessage: ChatMessageUi,
  content: string,
  set: ChatSet,
  get: ChatGet,
) {
  const state = get();
  const prefixMessages = state.messages.slice(0, userIndex);
  const attachments = contextAttachmentsFromMessage(userMessage);
  const replayContent = content.trim() || userMessage.content.trim() || "Attached context.";
  set((state) => ({
    messages: prefixMessages,
    error: undefined,
    pendingPlanApproval: undefined,
    pendingToolApproval: undefined,
    nextStepSuggestion: undefined,
  }));

  try {
    await prepareConversationReplay(prefixMessages, set, get);
  } catch (error) {
    set({ error: errorMessage(error) });
    return;
  }

  await get().sendMessage(
    replayContent,
    undefined,
    attachments.length
      ? { contextAttachments: attachments, displayAttachments: attachments }
      : undefined,
  );
}

async function prepareConversationReplay(
  prefixMessages: ChatMessageUi[],
  set: ChatSet,
  get: ChatGet,
) {
  const conversationId = get().conversationId;
  if (!conversationId) return;

  if (prefixMessages.length === 0) {
    set({ conversationId: undefined, conversationTitle: undefined });
    return;
  }

  const app = useAppStore.getState();
  const workspaceRoot = getEffectiveWorkspaceRoot(get());
  const fork = await forkConversation(app.baseUrl, conversationId, {
    title: get().conversationTitle,
    workspaceRoot,
    messages: conversationForkMessages(prefixMessages),
  });
  set({
    conversationId: fork.id,
    conversationTitle: fork.title,
  });
  void useAppStore.getState().associateConversation(fork.id, workspaceRoot);
  window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
}
