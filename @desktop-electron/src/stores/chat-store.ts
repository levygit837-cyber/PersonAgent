import { createContext, createElement, useContext, type ReactNode } from "react";
import { useStore } from "zustand";
import { createStore, type StoreApi } from "zustand/vanilla";
import {
  type ChatState,
  type ComposerAnnotation as ComposerAnnotationInternal,
} from "./chat-store/internal";
import { createComposerSlice } from "./chat-store/composer-slice";
import { createConversationSlice } from "./chat-store/conversation-slice";
import { createStreamingSlice } from "./chat-store/streaming-slice";
import { createPlanApprovalSlice } from "./chat-store/plan-approval-slice";
import { createToolApprovalSlice } from "./chat-store/tool-approval-slice";
import {
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
  ...createToolApprovalSlice(set, get),

  setWorkspaceRoot: (workspaceRoot) => set({ workspaceRoot: workspaceRoot?.trim() || undefined }),

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
