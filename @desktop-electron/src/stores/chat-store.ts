import { createContext, createElement, useContext, type ReactNode } from "react";
import { useStore } from "zustand";
import { createStore, type StoreApi } from "zustand/vanilla";
import {
  rejectTool,
  streamApproveTool,
} from "../api/client";
import { errorMessage } from "../api/errors";

import { useAppStore } from "./app-store";
import {
  emptySessionUsage,
  type ChatMessageUi,
  type PersistedMessage,
  type ToolApprovalUi,
} from "../types/chat";

import {
  type ChatState,
  type ComposerAnnotation as ComposerAnnotationInternal,
  thinkingStates,
  setConversationStatus,
  isActiveGenerationState,
  hasActiveToolBlocks,
  latestTodoSnapshotFromMessages,
  latestContextWindowEstimate,
  estimateConversationContextTokens,
  findAgentMessageIdForTool,
  resetLiveTokenTotals,
} from "./chat-store/internal";
import { createComposerSlice } from "./chat-store/composer-slice";
import { createConversationSlice } from "./chat-store/conversation-slice";
import { createStreamingSlice } from "./chat-store/streaming-slice";
import { createPlanApprovalSlice } from "./chat-store/plan-approval-slice";
import {
  handleChunk,
  flushTextBuffer,
  closeActiveReasoning,
  stringValue,
  isRecord,
  messageFromPersisted,
  isRenderablePersistedMessage,
} from "./chat-store/streaming-helpers";

export type { ComposerAnnotation } from "./chat-store/internal";
type ComposerAnnotation = ComposerAnnotationInternal;

export type ChatStoreApi = StoreApi<ChatState>;

interface CreateChatStoreOptions {
  initialWorkspaceRoot?: string | null;
  paneId?: string;
  syncWorkspaceSelection?: boolean;
}

export function createChatStore(options: CreateChatStoreOptions = {}): ChatStoreApi {
  const syncWorkspaceSelection = options.syncWorkspaceSelection ?? true;
  const paneId = options.paneId || "main";

  return createStore<ChatState>((set, get) => ({
  workspaceRoot: options.initialWorkspaceRoot,
  messages: [],

  ...createComposerSlice(set, get),
  ...createConversationSlice(set, get, {
    syncWorkspaceSelection,
    messageFromPersisted,
    isRenderablePersistedMessage,
    isRecord,
  }),
  ...createStreamingSlice(set, get, { paneId }),
  ...createPlanApprovalSlice(set, get),

  setWorkspaceRoot: (workspaceRoot) => set({ workspaceRoot: workspaceRoot?.trim() || undefined }),

  approvePendingTool: async () => {
    const pending = get().pendingToolApproval;
    if (!pending || get().isStreaming) return;
    const appState = useAppStore.getState();
    const agentId = findAgentMessageIdForTool(get().messages, pending.toolCallId) ?? `${Date.now()}_agent`;
    const controller = new AbortController();
    resetLiveTokenTotals();
    set((state) => {
      const hasAgentMessage = state.messages.some((message) => message.id === agentId);
      const agentMessage: ChatMessageUi = {
        id: agentId,
        role: "agent",
        label: "PersonAgent",
        content: "",
        reasoning: "",
        reasoningBlocks: [],
        toolBlocks: [],
        teamEvents: [],
        parts: [],
        isStreaming: true,
        isReasoningStreaming: false,
      };
      const messages = hasAgentMessage
        ? state.messages.map((message) => (message.id === agentId ? { ...message, isStreaming: true } : message))
        : [...state.messages, agentMessage];
      return {
        messages,
        isStreaming: true,
        isFinalizing: false,
        activeController: controller,
        activeAgentId: agentId,
        pendingToolApproval: undefined,
        nextStepSuggestion: undefined,
        liveSessionUsage: emptySessionUsage(),
        liveSubAgentIds: [],
        latestTodoSnapshot: latestTodoSnapshotFromMessages(messages, agentId),
        contextTokenEstimate: estimateConversationContextTokens(messages),
        contextWindowEstimate: latestContextWindowEstimate(messages),
        error: undefined,
      };
    });
    setConversationStatus(set, pending.conversationId, "running");
    try {
      for await (const chunk of streamApproveTool(
        appState.baseUrl,
        {
          conversationId: pending.conversationId,
          approvalId: pending.approvalId,
          argsHash: pending.argsHash,
        },
        controller.signal,
      )) {
        handleChunk(chunk, agentId, set, get, appState.selectedWorkspace);
      }
    } catch (error) {
      if (!controller.signal.aborted && isActiveGenerationState(get(), controller, agentId)) {
        set({ error: errorMessage(error) });
        setConversationStatus(set, pending.conversationId, "error");
      }
    } finally {
      flushTextBuffer(agentId, set);
      thinkingStates.delete(agentId);
      set((state) => {
        const hasActiveTools = hasActiveToolBlocks(state, agentId);
        const shouldClearStreaming = isActiveGenerationState(state, controller, agentId) && !hasActiveTools;
        const messages = state.messages.map((item) =>
          item.id === agentId ? closeActiveReasoning(item, false) : item,
        );
        return {
          isStreaming: shouldClearStreaming ? false : state.isStreaming,
          isFinalizing: state.activeAgentId === agentId || !state.activeAgentId ? false : state.isFinalizing,
          activeController: state.activeController === controller ? undefined : state.activeController,
          activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
          messages,
          contextTokenEstimate: shouldClearStreaming ? estimateConversationContextTokens(messages) : state.contextTokenEstimate,
          contextWindowEstimate: latestContextWindowEstimate(messages) ?? state.contextWindowEstimate,
        };
      });
    }
  },

  rejectPendingTool: async () => {
    const pending = get().pendingToolApproval;
    if (!pending || get().isStreaming) return;
    try {
      const response = await rejectTool(useAppStore.getState().baseUrl, {
        conversationId: pending.conversationId,
        approvalId: pending.approvalId,
      });
      set({ pendingToolApproval: undefined, error: undefined });
      setConversationStatus(set, pending.conversationId, "idle");
      const injected = typeof response.injected_message === "string" ? response.injected_message.trim() : "";
      if (injected) await get().sendMessage(injected);
    } catch (error) {
      set({ error: errorMessage(error) });
      setConversationStatus(set, pending.conversationId, "error");
    }
  },

  setAgentFeedback: (messageId, feedback) => {
    set((state) => ({
      messages: state.messages.map((message) => {
        if (message.id !== messageId) return message;
        const current = stringValue(message.metadata?.feedback);
        return {
          ...message,
          metadata: {
            ...(message.metadata ?? {}),
            feedback: current === feedback ? undefined : feedback,
          },
        };
      }),
    }));
  },

  setReasoningBlockExpanded: (messageId, blockId, expanded) => {
    set((state) => ({
      messages: state.messages.map((message) => {
        if (message.id !== messageId) return message;
        return {
          ...message,
          reasoningBlocks: message.reasoningBlocks.map((block) =>
            block.id === blockId ? { ...block, userExpanded: expanded } : block,
          ),
        };
      }),
    }));
  },
}));
}

const defaultChatStore = createChatStore({ paneId: "main", syncWorkspaceSelection: true });

const ChatStoreContext = createContext<ChatStoreApi | null>(null);

export function ChatStoreProvider({
  store,
  children,
}: {
  store: ChatStoreApi;
  children: ReactNode;
}) {
  return createElement(ChatStoreContext.Provider, { value: store }, children);
}

type ChatStoreHook = {
  <T>(selector: (state: ChatState) => T): T;
  getState: ChatStoreApi["getState"];
  setState: ChatStoreApi["setState"];
  subscribe: ChatStoreApi["subscribe"];
  getInitialState: ChatStoreApi["getInitialState"];
};

export const useChatStore = Object.assign(
  function useContextualChatStore<T>(selector: (state: ChatState) => T): T {
    const store = useContext(ChatStoreContext) ?? defaultChatStore;
    return useStore(store, selector);
  },
  {
    getState: defaultChatStore.getState,
    setState: defaultChatStore.setState,
    subscribe: defaultChatStore.subscribe,
    getInitialState: defaultChatStore.getInitialState,
  },
) as ChatStoreHook;

export function getDefaultChatStore() {
  return defaultChatStore;
}
