import { useAppStore } from "../app-store";
import {
  emptySessionUsage,
  type StreamChunk,
} from "../../types/chat";
import { isToolEvent, isToolGroupEvent } from "../../types/chat";
import type { ChatState } from "./internal";
import {
  thinkingStates,
  setConversationStatus,
  estimateConversationContextTokens,
  latestContextWindowEstimate,
  latestTodoSnapshotFromMessages,
  hasActiveToolBlocks,
  resetLiveTokenTotals,
  incrementLiveUsage,
} from "./internal";
import {
  planApprovalFromChunk,
  attachPlanApprovalArtifact,
  toolApprovalFromChunk,
} from "./approval-helpers";
import {
  normalizeStreamChunk,
  withVisibleTerminalNotice,
  applyPromptContextChunk,
  attachContextMetadata,
} from "./chunk-handlers/chunk-normalize";
import {
  queueTextChunk,
  flushTextBuffer,
  applyImageChunks,
} from "./chunk-handlers/buffer";
import {
  applyLiveToolUsage,
  applyLiveTokenUsage,
} from "./chunk-handlers/usage";
import {
  appendReasoningChunk,
  closeActiveReasoning,
} from "./chunk-handlers/reasoning";
import {
  applyToolChunk,
} from "./chunk-handlers/tool-blocks";
import type { SetFn } from "./chunk-handlers/utils";

export type { SetFn } from "./chunk-handlers/utils";
export {
  isRecord,
  stringValue,
} from "./chunk-handlers/utils";
export {
  applyLiveToolUsage,
  applyLiveTokenUsage,
} from "./chunk-handlers/usage";
export {
  queueTextChunk,
  flushTextBuffer,
} from "./chunk-handlers/buffer";
export {
  appendReasoningChunk,
  closeActiveReasoning,
} from "./chunk-handlers/reasoning";
export {
  shouldCollapseToolBlock,
  toolTitle,
} from "./chunk-handlers/tool-blocks";
export {
  normalizeGeneratedImageUrls,
} from "./chunk-handlers/buffer";

export function handleChunk(
  rawChunk: StreamChunk,
  agentId: string,
  set: SetFn,
  get: () => ChatState,
  workspaceRoot?: string,
) {
  const chunk = normalizeStreamChunk(agentId, withVisibleTerminalNotice(rawChunk));
  if (chunk.error) {
    const message = chunk.error_detail?.message ?? chunk.error;
    const conversationId = String(chunk.conversation_id ?? get().conversationId ?? "");
    flushTextBuffer(agentId, set);
    thinkingStates.delete(agentId);
    set((state) => ({
      error: message,
      isStreaming: state.activeAgentId === agentId ? false : state.isStreaming,
      isFinalizing: state.activeAgentId === agentId ? false : state.isFinalizing,
      activeController: state.activeAgentId === agentId ? undefined : state.activeController,
      activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
      messages: state.messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    }));
    setConversationStatus(set, conversationId, "error");
    return;
  }

  if (chunk.event === "conversation" && chunk.conversation_id) {
    flushTextBuffer(agentId, set);
    set((state) => ({
      conversationId: chunk.conversation_id,
      conversationTitle: chunk.title || state.conversationTitle,
    }));
    setConversationStatus(set, chunk.conversation_id, "running");
    void useAppStore.getState().associateConversation(chunk.conversation_id, workspaceRoot);
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    return;
  }

  if (chunk.event === "prompt_context") {
    applyPromptContextChunk(chunk, agentId, set);
    return;
  }

  if (chunk.event === "plan_approval_requested") {
    incrementLiveUsage(set, "plans_created", 1);
    flushTextBuffer(agentId, set);
    thinkingStates.delete(agentId);
    const approval = planApprovalFromChunk(chunk);
    set((state) => ({
      isStreaming: state.activeAgentId === agentId ? false : state.isStreaming,
      isFinalizing: state.activeAgentId === agentId ? true : state.isFinalizing,
      activeController: state.activeAgentId === agentId ? undefined : state.activeController,
      activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
      pendingPlanApproval: approval,
      messages: state.messages.map((item) =>
        item.id === agentId ? attachPlanApprovalArtifact(closeActiveReasoning(item, false), approval) : item,
      ),
    }));
    setConversationStatus(set, chunk.conversation_id, "pending");
    return;
  }

  if (chunk.event === "plan_mode_changed") {
    if (chunk.plan_status === "approved" || chunk.plan_status === "cancelled") {
      set({ pendingPlanApproval: undefined });
    }
    return;
  }

  if (chunk.event === "conversation_saved") {
    resetLiveTokenTotals();
    flushTextBuffer(agentId, set);
    const suggestion =
      typeof chunk.next_step_suggestion === "string" && chunk.next_step_suggestion.trim()
        ? chunk.next_step_suggestion.trim()
        : undefined;
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    setConversationStatus(set, chunk.conversation_id ?? get().conversationId, "idle");
    set((state) => {
      const hasActiveTools = hasActiveToolBlocks(state, agentId);
      const shouldClearStreaming = state.activeAgentId === agentId && !hasActiveTools;
      const messages = state.messages.map((item) => {
        if (item.id !== agentId) return item;
        const withReasoning =
          chunk.reasoning_content && item.reasoning.trim().length === 0
            ? appendReasoningChunk(item, chunk.reasoning_content)
            : item;
        const withContext = attachContextMetadata(withReasoning, chunk);
        return closeActiveReasoning(withContext, false);
      });
      return {
        isStreaming: shouldClearStreaming ? false : state.isStreaming,
        isFinalizing: false,
        activeController: state.activeAgentId === agentId ? undefined : state.activeController,
        activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
        nextStepSuggestion: state.activeAgentId ? state.nextStepSuggestion : suggestion,
        conversationTitle: chunk.title || state.conversationTitle,
        liveSessionUsage: emptySessionUsage(),
        liveSubAgentIds: state.activeAgentId ? state.liveSubAgentIds : [],
        messages,
        contextTokenEstimate: estimateConversationContextTokens(messages),
        contextWindowEstimate: latestContextWindowEstimate(messages) ?? state.contextWindowEstimate,
      };
    });
    thinkingStates.delete(agentId);
    window.dispatchEvent(new CustomEvent("personagent:session-panel-changed"));
    return;
  }

  if (chunk.event === "next_step_suggestion") {
    const suggestion =
      typeof chunk.next_step_suggestion === "string" && chunk.next_step_suggestion.trim()
        ? chunk.next_step_suggestion.trim()
        : undefined;
    set({ nextStepSuggestion: suggestion });
    return;
  }

  if (isToolEvent(chunk)) {
    applyLiveToolUsage(chunk, set);
    flushTextBuffer(agentId, set);
    if (chunk.event === "permission_required" && chunk.approval_id) {
      set({
        pendingToolApproval: toolApprovalFromChunk(chunk),
        isStreaming: false,
        isFinalizing: false,
      });
      setConversationStatus(set, chunk.conversation_id ?? get().conversationId, "pending");
    }
    if (!isToolGroupEvent(chunk)) {
      applyToolChunk(chunk, agentId, set);
    }
    return;
  }

  if (chunk.images?.length) {
    flushTextBuffer(agentId, set);
    applyImageChunks(agentId, chunk.images, set);
  }

  const isToolPause = chunk.finish_reason === "tool_calls";
  if (isToolPause && !chunk.content && !chunk.reasoning_content) {
    flushTextBuffer(agentId, set);
    set((state) => ({
      messages: state.messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, true) : item)),
    }));
    return;
  }

  if (!chunk.content && !chunk.reasoning_content && !chunk.finish_reason) return;

  applyLiveTokenUsage(chunk, set);
  queueTextChunk(agentId, chunk, set);
}
