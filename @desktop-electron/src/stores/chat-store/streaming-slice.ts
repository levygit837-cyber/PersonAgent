import {
  streamChatCompletion,
  streamTeamChat,
} from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useAppStore } from "../app-store";
import {
  buildChatRequest,
  buildTeamRunStart,
  emptySessionUsage,
  type ChatMessageUi,
  type StreamChunk,
} from "../../types/chat";
import type { ChatSet, ChatGet, ChatState, SendMessageOptions } from "./internal";
import {
  thinkingStates,
  getEffectiveWorkspaceRoot,
  setConversationStatus,
  handleLocalSlashCommand,
  resetLiveTokenTotals,
  estimateConversationContextTokens,
  latestContextWindowEstimate,
  isActiveGenerationState,
  hasActiveToolBlocks,
} from "./internal";
import {
  handleChunk,
  handleTeamEvent,
  flushTextBuffer,
  closeActiveReasoning,
} from "./streaming-helpers";

export interface StreamingSliceOptions {
  paneId: string;
}

export function createStreamingSlice(
  set: ChatSet,
  get: ChatGet,
  opts: StreamingSliceOptions,
) {
  const { paneId } = opts;

  return {
    isStreaming: false,
    isFinalizing: false,
    activeAgentId: undefined as string | undefined,
    activeController: undefined as AbortController | undefined,
    liveSessionUsage: emptySessionUsage(),
    liveSubAgentIds: [] as string[],
    latestTodoSnapshot: undefined as ChatState["latestTodoSnapshot"],
    contextTokenEstimate: 0,
    contextWindowEstimate: undefined as ChatState["contextWindowEstimate"],
    browserToolBlocks: [] as ChatState["browserToolBlocks"],

    sendMessage: async (text: string, systemPrompt?: string, options?: SendMessageOptions) => {
      const message = text.trim();
      if (!message || get().isStreaming) return;

      if (handleLocalSlashCommand(message, set, get)) return;

      const appState = useAppStore.getState();
      const workspaceRoot = getEffectiveWorkspaceRoot(get());
      const contextAttachments = options?.contextAttachments ?? [];
      const displayAttachments = options?.displayAttachments ?? contextAttachments;
      const userMessage: ChatMessageUi | null = options?.hideUserMessage
        ? null
        : {
            id: `${Date.now()}_user`,
            role: "user",
            label: "You",
            content: message,
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
            metadata: displayAttachments.length
              ? { context_attachments: displayAttachments }
              : undefined,
          };
      const agentId = `${paneId}_${Date.now()}_${Math.random().toString(36).slice(2)}_agent`;
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
      const controller = new AbortController();
      resetLiveTokenTotals();
      set((state) => {
        const messages = [...state.messages, ...(userMessage ? [userMessage] : []), agentMessage];
        return {
          messages,
          isStreaming: true,
          isFinalizing: false,
          activeController: controller,
          activeAgentId: agentId,
          pendingPlanApproval: undefined,
          nextStepSuggestion: undefined,
          liveSessionUsage: emptySessionUsage(),
          liveSubAgentIds: [],
          latestTodoSnapshot: undefined,
          contextTokenEstimate: estimateConversationContextTokens(messages),
          contextWindowEstimate: latestContextWindowEstimate(messages),
          error: undefined,
        };
      });
      if (get().conversationId) setConversationStatus(set, get().conversationId, "running");

      const requestInput = {
        conversationId: get().conversationId,
        message,
        provider: appState.provider,
        model: appState.selectedModelId,
        reasoningPreset: appState.reasoningPreset,
        workspaceRoot,
        systemPrompt,
        contextAttachments,
        planModeRequested: options?.planModeRequested,
        permissionMode: options?.permissionMode,
      };
      const payload = buildChatRequest(requestInput);

      try {
        if (appState.teamMode) {
          for await (const event of streamTeamChat(appState.baseUrl, buildTeamRunStart(requestInput), controller.signal)) {
            handleTeamEvent(event, agentId, set, get);
          }
        } else {
          for await (const chunk of streamChatCompletion(appState.baseUrl, payload, controller.signal)) {
            handleChunk(chunk, agentId, set, get, workspaceRoot);
          }
        }
      } catch (error) {
        if (!controller.signal.aborted && isActiveGenerationState(get(), controller, agentId)) {
          const conversationId = get().conversationId;
          set({ error: errorMessage(error) });
          if (conversationId) setConversationStatus(set, conversationId, "error");
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

    stopStreaming: () => {
      const controller = get().activeController;
      controller?.abort();
      const agentId = get().activeAgentId;
      if (agentId) {
        flushTextBuffer(agentId, set);
        thinkingStates.delete(agentId);
      }
      set((state) => ({
        isStreaming: false,
        isFinalizing: false,
        activeController: undefined,
        activeAgentId: undefined,
        messages: state.messages.map((item) =>
          item.id === agentId ? closeActiveReasoning(item, false) : item,
        ),
      }));
    },
  };
}
