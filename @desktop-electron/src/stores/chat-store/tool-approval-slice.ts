import {
  rejectTool,
  streamApproveTool,
} from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useAppStore } from "../app-store";
import {
  emptySessionUsage,
  type ChatMessageUi,
} from "../../types/chat";
import type { ChatSet, ChatGet } from "./internal";
import {
  thinkingStates,
  setConversationStatus,
  isActiveGenerationState,
  hasActiveToolBlocks,
  latestTodoSnapshotFromMessages,
  latestContextWindowEstimate,
  estimateConversationContextTokens,
  findAgentMessageIdForTool,
  resetLiveTokenTotals,
} from "./internal";
import {
  handleChunk,
  flushTextBuffer,
  closeActiveReasoning,
} from "./streaming-helpers";

export function createToolApprovalSlice(
  set: ChatSet,
  get: ChatGet,
) {
  return {
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
  };
}
