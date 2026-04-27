import { create } from "zustand";
import {
  approvePlan,
  approveTool,
  cancelPlan,
  continuePlan,
  getConversation,
  rejectTool,
  streamTeamChat,
  streamChatCompletion,
} from "../api/client";
import { createThinkingTagState, splitThinkingTags, type ThinkingTagState } from "../lib/reasoning";
import { useAppStore } from "./app-store";
import {
  buildChatRequest,
  buildTeamRunStart,
  emptySessionUsage,
  type ChatMessagePartUi,
  type ChatMessageUi,
  type GeneratedImage,
  type PersistedMessage,
  type PlanApprovalUi,
  type SessionUsage,
  type StreamChunk,
  type TeamRunEvent,
  type TeamTraceEventUi,
  type ToolApprovalUi,
  type ToolBlockStatus,
  type ToolBlockUi,
  isToolEvent,
  isToolGroupEvent,
  parseToolStatus,
} from "../types/chat";

const thinkingStates = new Map<string, ThinkingTagState>();
const textFlushBuffers = new Map<string, TextFlushBuffer>();
const teamDeltaFlushBuffers = new Map<string, TeamDeltaFlushBuffer>();
const STREAM_TEXT_FLUSH_MS = 50;
const liveTokenTotals = {
  exactAgent: 0,
  exactThinking: 0,
  estimatedAgent: 0,
  estimatedThinking: 0,
};

type TextFlushBuffer = {
  content: string;
  reasoning: string;
  finishReason?: string;
  timer?: ReturnType<typeof setTimeout>;
};

type TeamDeltaFlushBuffer = {
  agentId: string;
  event: TeamRunEvent;
  content: string;
  reasoning: string;
  timer?: ReturnType<typeof setTimeout>;
};

interface ChatState {
  messages: ChatMessageUi[];
  conversationId?: string;
  conversationTitle?: string;
  error?: string;
  isStreaming: boolean;
  isFinalizing: boolean;
  activeController?: AbortController;
  activeAgentId?: string;
  pendingPlanApproval?: PlanApprovalUi;
  pendingToolApproval?: ToolApprovalUi;
  nextStepSuggestion?: string;
  liveSessionUsage: SessionUsage;
  liveSubAgentIds: string[];
  loadConversation: (id: string) => Promise<void>;
  startNewConversation: () => void;
  sendMessage: (text: string, systemPrompt?: string) => Promise<void>;
  approvePendingPlan: (feedback?: string) => Promise<void>;
  continuePendingPlan: (feedback?: string) => Promise<void>;
  cancelPendingPlan: (feedback?: string) => Promise<void>;
  approvePendingTool: () => Promise<void>;
  rejectPendingTool: () => Promise<void>;
  stopStreaming: () => void;
  clearError: () => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  isFinalizing: false,
  liveSessionUsage: emptySessionUsage(),
  liveSubAgentIds: [],

  loadConversation: async (id) => {
    try {
      const detail = await getConversation(useAppStore.getState().baseUrl, id);
      set({
        conversationId: detail.id,
        conversationTitle: detail.title,
        messages: detail.messages
          .filter((message) => message.role !== "system")
          .map(messageFromPersisted),
        pendingPlanApproval: undefined,
        pendingToolApproval: undefined,
        nextStepSuggestion: undefined,
        liveSessionUsage: emptySessionUsage(),
        liveSubAgentIds: [],
        isFinalizing: false,
        error: undefined,
      });
      resetLiveTokenTotals();
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  startNewConversation: () => {
    get().stopStreaming();
    set({
      messages: [],
      conversationId: undefined,
      conversationTitle: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
      isFinalizing: false,
      error: undefined,
    });
    resetLiveTokenTotals();
  },

  sendMessage: async (text, systemPrompt) => {
    const message = text.trim();
    if (!message || get().isStreaming) return;

    const appState = useAppStore.getState();
    const userMessage: ChatMessageUi = {
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
    };
    const agentId = `${Date.now()}_agent`;
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
    set((state) => ({
      messages: [...state.messages, userMessage, agentMessage],
      isStreaming: true,
      isFinalizing: false,
      activeController: controller,
      activeAgentId: agentId,
      pendingPlanApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
      error: undefined,
    }));

    const requestInput = {
      conversationId: get().conversationId,
      message,
      provider: appState.provider,
      model: appState.selectedModelId,
      reasoningPreset: appState.reasoningPreset,
      workspaceRoot: appState.selectedWorkspace,
      systemPrompt,
    };
    const payload = buildChatRequest(requestInput);

    try {
      if (appState.teamMode) {
        for await (const event of streamTeamChat(appState.baseUrl, buildTeamRunStart(requestInput), controller.signal)) {
          handleTeamEvent(event, agentId, set, get);
        }
      } else {
        for await (const chunk of streamChatCompletion(appState.baseUrl, payload, controller.signal)) {
          handleChunk(chunk, agentId, set, get, appState.selectedWorkspace);
        }
      }
    } catch (error) {
      if (!controller.signal.aborted && isActiveGenerationState(get(), controller, agentId)) {
        set({ error: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      flushTeamDeltaBuffers(agentId, set);
      flushTextBuffer(agentId, set);
      thinkingStates.delete(agentId);
      set((state) => ({
        isStreaming: isActiveGenerationState(state, controller, agentId) ? false : state.isStreaming,
        isFinalizing: state.activeAgentId === agentId || !state.activeAgentId ? false : state.isFinalizing,
        activeController: state.activeController === controller ? undefined : state.activeController,
        activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
        messages: state.messages.map((item) =>
          item.id === agentId ? closeActiveReasoning(item, false) : item,
        ),
      }));
    }
  },

  approvePendingPlan: async (feedback) => {
    const pending = get().pendingPlanApproval;
    if (!pending || get().isStreaming) return;
    try {
      const response = await approvePlan(useAppStore.getState().baseUrl, {
        conversationId: pending.conversationId,
        approvalId: pending.approvalId,
        feedback,
      });
      set({ pendingPlanApproval: undefined, error: undefined });
      const injected = response.injected_message?.trim();
      if (injected) await get().sendMessage(injected);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  continuePendingPlan: async (feedback) => {
    const pending = get().pendingPlanApproval;
    if (!pending || get().isStreaming) return;
    try {
      const response = await continuePlan(useAppStore.getState().baseUrl, {
        conversationId: pending.conversationId,
        approvalId: pending.approvalId,
        feedback,
      });
      set({ pendingPlanApproval: undefined, error: undefined });
      const message = response.suggested_message?.trim();
      if (message) await get().sendMessage(message);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  cancelPendingPlan: async (feedback) => {
    const pending = get().pendingPlanApproval;
    if (!pending || get().isStreaming) return;
    try {
      await cancelPlan(useAppStore.getState().baseUrl, {
        conversationId: pending.conversationId,
        approvalId: pending.approvalId,
        feedback,
      });
      set({ pendingPlanApproval: undefined, error: undefined });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  approvePendingTool: async () => {
    const pending = get().pendingToolApproval;
    if (!pending || get().isStreaming) return;
    try {
      const response = await approveTool(useAppStore.getState().baseUrl, {
        conversationId: pending.conversationId,
        approvalId: pending.approvalId,
      });
      set({ pendingToolApproval: undefined, error: undefined });
      const injected = typeof response.injected_message === "string" ? response.injected_message.trim() : "";
      if (injected) await get().sendMessage(injected);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
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
      const injected = typeof response.injected_message === "string" ? response.injected_message.trim() : "";
      if (injected) await get().sendMessage(injected);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  stopStreaming: () => {
    const controller = get().activeController;
    controller?.abort();
    const agentId = get().activeAgentId;
    if (agentId) {
      flushTeamDeltaBuffers(agentId, set);
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

  clearError: () => set({ error: undefined }),
}));

function isActiveGenerationState(state: ChatState, controller: AbortController, agentId: string) {
  return state.activeController === controller || state.activeAgentId === agentId;
}

function resetLiveTokenTotals() {
  liveTokenTotals.exactAgent = 0;
  liveTokenTotals.exactThinking = 0;
  liveTokenTotals.estimatedAgent = 0;
  liveTokenTotals.estimatedThinking = 0;
}

type SessionUsageKey = keyof SessionUsage;

function incrementLiveUsage(
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
  key: SessionUsageKey,
  value: number,
  estimated = false,
) {
  set((state) => ({
    liveSessionUsage: {
      ...state.liveSessionUsage,
      [key]: {
        value: state.liveSessionUsage[key].value + Math.max(0, value),
        estimated: state.liveSessionUsage[key].estimated || estimated,
      },
    },
  }));
}

function applyLiveToolUsage(
  chunk: StreamChunk,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  if (chunk.event === "tool_call_started") {
    incrementLiveUsage(set, "tool_calls", 1);
    if (chunk.tool_name === "Skill") incrementLiveUsage(set, "skills_used_count", 1);
    if (chunk.tool_name?.startsWith("mcp__") || chunk.tool_data?.is_mcp === true) {
      incrementLiveUsage(set, "mcp_calls_count", 1);
    }
  }
  if (chunk.event === "tool_result" && chunk.tool_name === "TodoWrite") {
    const todos = chunk.tool_data?.todos;
    incrementLiveUsage(set, "todos_created", Array.isArray(todos) ? todos.length : 1);
  }
}

function applyLiveTokenUsage(
  chunk: Pick<StreamChunk, "content" | "reasoning_content" | "usage">,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  const exact = normalizeUsageTokens(chunk.usage);
  if (exact.agent !== undefined) {
    liveTokenTotals.exactAgent = exact.agent;
    liveTokenTotals.estimatedAgent = 0;
  } else if (chunk.content) {
    liveTokenTotals.estimatedAgent += estimateTokens(chunk.content);
  }
  if (exact.thinking !== undefined) {
    liveTokenTotals.exactThinking = exact.thinking;
    liveTokenTotals.estimatedThinking = 0;
  } else if (chunk.reasoning_content) {
    liveTokenTotals.estimatedThinking += estimateTokens(chunk.reasoning_content);
  }

  set((state) => ({
    liveSessionUsage: {
      ...state.liveSessionUsage,
      agent_output_tokens: {
        value: liveTokenTotals.exactAgent + liveTokenTotals.estimatedAgent,
        estimated: liveTokenTotals.estimatedAgent > 0,
      },
      thinking_output_tokens: {
        value: liveTokenTotals.exactThinking + liveTokenTotals.estimatedThinking,
        estimated: liveTokenTotals.estimatedThinking > 0,
      },
    },
  }));
}

function normalizeUsageTokens(usage?: Record<string, unknown>) {
  if (!usage) return {};
  const completionDetails = objectValue(usage.completion_tokens_details);
  const thinking =
    numberValue(usage.reasoning_tokens) ??
    numberValue(usage.thinking_tokens) ??
    numberValue(usage.thoughtsTokenCount) ??
    numberValue(usage.thoughts_token_count) ??
    numberValue(completionDetails?.reasoning_tokens);
  const rawAgent =
    numberValue(usage.candidatesTokenCount) ??
    numberValue(usage.candidates_token_count) ??
    numberValue(usage.output_tokens) ??
    numberValue(usage.completion_tokens);
  const agent =
    rawAgent !== undefined && thinking !== undefined && usage.completion_tokens !== undefined && usage.candidatesTokenCount === undefined
      ? Math.max(0, rawAgent - thinking)
      : rawAgent;
  return { agent, thinking };
}

function estimateTokens(value: string) {
  if (!value) return 0;
  return Math.max(1, Math.ceil(value.length / 4));
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function handleChunk(
  rawChunk: StreamChunk,
  agentId: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
  get: () => ChatState,
  workspaceRoot?: string,
) {
  const chunk = normalizeStreamChunk(agentId, rawChunk);
  if (chunk.error) {
    flushTextBuffer(agentId, set);
    thinkingStates.delete(agentId);
    set((state) => ({
      error: chunk.error,
      isStreaming: state.activeAgentId === agentId ? false : state.isStreaming,
      isFinalizing: state.activeAgentId === agentId ? false : state.isFinalizing,
      activeController: state.activeAgentId === agentId ? undefined : state.activeController,
      activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
      messages: state.messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    }));
    return;
  }

  if (chunk.event === "conversation" && chunk.conversation_id) {
    flushTextBuffer(agentId, set);
    set((state) => ({
      conversationId: chunk.conversation_id,
      conversationTitle: chunk.title || state.conversationTitle,
    }));
    void useAppStore.getState().associateConversation(chunk.conversation_id, workspaceRoot);
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    return;
  }

  if (chunk.event === "plan_approval_requested") {
    incrementLiveUsage(set, "plans_created", 1);
    flushTextBuffer(agentId, set);
    thinkingStates.delete(agentId);
    set((state) => ({
      isStreaming: state.activeAgentId === agentId ? false : state.isStreaming,
      isFinalizing: state.activeAgentId === agentId ? true : state.isFinalizing,
      activeController: state.activeAgentId === agentId ? undefined : state.activeController,
      activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
      pendingPlanApproval: planApprovalFromChunk(chunk),
      messages: state.messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    }));
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
    set((state) => ({
      isStreaming: state.activeAgentId === agentId ? false : state.isStreaming,
      isFinalizing: false,
      activeController: state.activeAgentId === agentId ? undefined : state.activeController,
      activeAgentId: state.activeAgentId === agentId ? undefined : state.activeAgentId,
      nextStepSuggestion: state.activeAgentId ? state.nextStepSuggestion : suggestion,
      conversationTitle: chunk.title || state.conversationTitle,
      liveSessionUsage: state.activeAgentId ? state.liveSessionUsage : emptySessionUsage(),
      liveSubAgentIds: state.activeAgentId ? state.liveSubAgentIds : [],
      messages: state.messages.map((item) => {
        if (item.id !== agentId) return item;
        const withReasoning =
          chunk.reasoning_content && item.reasoning.trim().length === 0
            ? appendReasoningChunk(item, chunk.reasoning_content)
            : item;
        return closeActiveReasoning(withReasoning, false);
      }),
    }));
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

function queueTextChunk(
  agentId: string,
  chunk: StreamChunk,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  const buffer = textFlushBuffers.get(agentId) ?? { content: "", reasoning: "" };
  buffer.content += chunk.content ?? "";
  buffer.reasoning += chunk.reasoning_content ?? "";
  if (chunk.finish_reason) buffer.finishReason = chunk.finish_reason;
  textFlushBuffers.set(agentId, buffer);

  if (chunk.finish_reason) {
    flushTextBuffer(agentId, set);
    return;
  }

  if (!buffer.timer) {
    buffer.timer = setTimeout(() => flushTextBuffer(agentId, set), STREAM_TEXT_FLUSH_MS);
  }
}

function flushTextBuffer(
  agentId: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  const buffer = textFlushBuffers.get(agentId);
  if (!buffer) return;
  if (buffer.timer) clearTimeout(buffer.timer);
  textFlushBuffers.delete(agentId);

  const content = buffer.content;
  const reasoning = buffer.reasoning;
  const finishReason = buffer.finishReason;
  if (!content && !reasoning && !finishReason) return;
  const isFinalFinish = Boolean(finishReason && finishReason !== "tool_calls");

  set((state) => ({
    isStreaming: isFinalFinish && state.activeAgentId === agentId ? false : state.isStreaming,
    isFinalizing: isFinalFinish && state.activeAgentId === agentId ? true : state.isFinalizing,
    activeController: isFinalFinish && state.activeAgentId === agentId ? undefined : state.activeController,
    activeAgentId: isFinalFinish && state.activeAgentId === agentId ? undefined : state.activeAgentId,
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      let next = item;
      if (reasoning) {
        next = appendReasoningChunk(next, reasoning);
      }
      if (content || finishReason) {
        next = closeActiveReasoning(next, true);
      }
      if (content) {
        next = {
          ...next,
          content: next.content + content,
          parts: appendContentPart(next.parts, next.id, content),
        };
      }
      if (isFinalFinish) thinkingStates.delete(agentId);
      return {
        ...next,
        isStreaming: !isFinalFinish,
        isReasoningStreaming:
          !isFinalFinish &&
          !content &&
          next.reasoningBlocks.some((block) => block.isStreaming),
      };
    }),
  }));
}

function planApprovalFromChunk(chunk: StreamChunk): PlanApprovalUi {
  return {
    conversationId: String(chunk.conversation_id ?? ""),
    approvalId: String(chunk.approval_id ?? ""),
    planId: String(chunk.plan_id ?? ""),
    planContent: String(chunk.plan_content ?? ""),
    planStatus: String(chunk.plan_status ?? "awaiting_approval"),
    feedback: chunk.feedback,
  };
}

function toolApprovalFromChunk(chunk: StreamChunk): ToolApprovalUi {
  return {
    conversationId: String(chunk.conversation_id ?? ""),
    approvalId: String(chunk.approval_id ?? ""),
    toolCallId: String(chunk.tool_call_id ?? chunk.tool_approval?.tool_call_id ?? ""),
    toolName: String(chunk.tool_name ?? chunk.tool_approval?.tool_name ?? "tool"),
    toolInput: chunk.tool_input ?? chunk.tool_approval?.arguments,
    message: chunk.tool_error ?? chunk.tool_result ?? chunk.tool_approval?.message,
  };
}

function handleTeamEvent(
  event: TeamRunEvent,
  agentId: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
  get: () => ChatState,
) {
  if (event.error) {
    flushTeamDeltaBuffers(agentId, set);
    flushTextBuffer(agentId, set);
    set({
      error: event.error,
      messages: get().messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    });
    return;
  }

  if (event.conversation_id) {
    set({ conversationId: event.conversation_id });
  }

  if (event.event === "agent_turn_started" && event.agent_id) {
    set((state) => {
      if (state.liveSubAgentIds.includes(String(event.agent_id))) return {};
      const ids = [...state.liveSubAgentIds, String(event.agent_id)];
      return {
        liveSubAgentIds: ids,
        liveSessionUsage: {
          ...state.liveSessionUsage,
          subagents_used: { value: ids.length, estimated: false },
        },
      };
    });
  }

  if (event.event === "agent_delta") {
    queueTeamDeltaEvent(agentId, event, set);
    return;
  }

  if (event.event === "final_delta") {
    applyLiveTokenUsage(
      {
        content: event.content,
        reasoning_content: event.reasoning_content,
      },
      set,
    );
    queueTextChunk(
      agentId,
      {
        content: event.content,
        reasoning_content: event.reasoning_content,
      },
      set,
    );
    return;
  }

  flushTeamDeltaBuffers(agentId, set);
  flushTextBuffer(agentId, set);

  if (event.event === "team_run_completed") {
    resetLiveTokenTotals();
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    window.dispatchEvent(new CustomEvent("personagent:session-panel-changed"));
  }

  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      return applyTeamEventToMessage(item, event);
    }),
    isStreaming: !isTerminalTeamEvent(event),
  }));
}

function queueTeamDeltaEvent(
  agentId: string,
  event: TeamRunEvent,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  const key = teamDeltaBufferKey(agentId, event);
  const buffer = teamDeltaFlushBuffers.get(key) ?? {
    agentId,
    event: { ...event, content: undefined, reasoning_content: undefined },
    content: "",
    reasoning: "",
  };
  buffer.content += event.content ?? "";
  buffer.reasoning += event.reasoning_content ?? "";
  teamDeltaFlushBuffers.set(key, buffer);
  if (!buffer.timer) {
    buffer.timer = setTimeout(() => flushTeamDeltaBuffer(key, set), STREAM_TEXT_FLUSH_MS);
  }
}

function flushTeamDeltaBuffers(
  agentId: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  for (const [key, buffer] of teamDeltaFlushBuffers) {
    if (buffer.agentId === agentId) flushTeamDeltaBuffer(key, set);
  }
}

function flushTeamDeltaBuffer(
  key: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  const buffer = teamDeltaFlushBuffers.get(key);
  if (!buffer) return;
  if (buffer.timer) clearTimeout(buffer.timer);
  teamDeltaFlushBuffers.delete(key);
  if (!buffer.content && !buffer.reasoning) return;
  const event: TeamRunEvent = {
    ...buffer.event,
    content: buffer.content || undefined,
    reasoning_content: buffer.reasoning || undefined,
  };
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== buffer.agentId) return item;
      return applyTeamEventToMessage(item, event);
    }),
  }));
}

function teamDeltaBufferKey(agentId: string, event: TeamRunEvent) {
  return `${agentId}:${event.run_id ?? ""}:${event.round ?? ""}:${event.agent_id ?? ""}`;
}

function applyTeamEventToMessage(message: ChatMessageUi, event: TeamRunEvent): ChatMessageUi {
  let next = message;
  if (event.reasoning_content && event.event !== "agent_turn_completed") {
    next = appendReasoningChunk(next, event.reasoning_content);
  }
  if (event.content || event.event !== "agent_delta") {
    next = closeActiveReasoning(next, true);
  }
  next = applyTeamTraceEvent(next, event);
  const isTerminal = isTerminalTeamEvent(event);
  return {
    ...next,
    label: "Team Mode",
    isStreaming: !isTerminal,
    isReasoningStreaming: false,
  };
}

function isTerminalTeamEvent(event: TeamRunEvent) {
  return (
    event.event === "team_run_completed" ||
    event.event === "team_consensus_failed" ||
    event.event === "team_run_cancelled"
  );
}

function applyTeamTraceEvent(message: ChatMessageUi, event: TeamRunEvent): ChatMessageUi {
  const events = [...message.teamEvents];
  const upsert = (trace: TeamTraceEventUi) => {
    const index = events.findIndex((item) => item.id === trace.id);
    if (index >= 0) {
      events[index] = { ...events[index], ...trace };
    } else {
      events.push(trace);
    }
  };

  if (event.event === "team_run_started") {
    upsert({
      id: `${event.run_id}-run`,
      kind: "run",
      title: event.team?.name ?? "Team Mode",
      detail: "Run started",
      status: "running",
    });
  }
  if (event.event === "round_started") {
    upsert({
      id: `${event.run_id}-round-${event.round}`,
      kind: "round",
      title: `Round ${event.round}`,
      detail: event.phase,
      status: "running",
      round: event.round,
    });
  }
  if (event.event === "debate_started") {
    upsert({
      id: `${event.run_id}-debate-${event.round}`,
      kind: "debate",
      title: `Debate round ${event.round}`,
      detail: "Blackboard review",
      status: "running",
      round: event.round,
    });
  }
  if (event.event === "agent_turn_started") {
    upsert({
      id: turnTraceId(event),
      kind: "turn",
      title: event.agent_name ?? event.agent_id ?? "Agent",
      detail: event.phase ?? event.agent_role,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "running",
      content: "",
    });
  }
  if (event.event === "agent_delta") {
    const id = turnTraceId(event);
    const existing = events.find((item) => item.id === id);
    const chunk = event.content || "";
    if (!chunk) return { ...message, teamEvents: events };
    upsert({
      id,
      kind: "turn",
      title: event.agent_name ?? existing?.title ?? event.agent_id ?? "Agent",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "running",
      content: `${existing?.content ?? ""}${chunk}`,
    });
  }
  if (event.event === "agent_turn_completed") {
    const id = turnTraceId(event);
    const existing = events.find((item) => item.id === id);
    const failed = event.status === "failed";
    upsert({
      id,
      kind: "turn",
      title: event.agent_name ?? existing?.title ?? event.agent_id ?? "Agent",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: failed ? "failed" : "completed",
      content: existing?.content || event.content || event.digest,
      detail: event.duration_ms != null ? `${event.duration_ms} ms` : existing?.detail,
    });
  }
  if (event.event === "blackboard_event") {
    const payload = (event.payload && typeof event.payload === "object" ? event.payload : {}) as Record<string, unknown>;
    const summary = typeof payload.summary === "string" ? payload.summary : "";
    const blocker = typeof payload.blocker === "string" ? payload.blocker : "";
    upsert({
      id: `${event.run_id}-blackboard-${event.sequence ?? events.length}`,
      kind: "blackboard",
      title: `${event.agent_name ?? "Agent"} published`,
      detail: `${event.phase ?? "blackboard"} #${event.sequence ?? ""}`.trim(),
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: event.event_type === "agent_blocker" ? "rejected" : "completed",
      content: blocker || summary,
    });
  }
	  if (event.event === "blackboard_snapshot") {
	    const snapshot = (event.snapshot && typeof event.snapshot === "object" ? event.snapshot : {}) as Record<string, unknown>;
	    const entryCount = typeof snapshot.entry_count === "number" ? snapshot.entry_count : undefined;
	    const latest = typeof snapshot.latest_sequence === "number" ? snapshot.latest_sequence : undefined;
    upsert({
      id: `${event.run_id}-blackboard-snapshot-${event.round}`,
      kind: "blackboard",
      title: "Blackboard snapshot",
      detail: entryCount != null ? `${entryCount} entries` : undefined,
      round: event.round,
      status: "completed",
	      content: latest != null ? `Latest sequence: ${latest}` : undefined,
	    });
	  }
	  if (event.event === "execution_contract") {
	    const contract = (event.contract && typeof event.contract === "object" ? event.contract : {}) as Record<string, unknown>;
	    const objective = typeof contract.objective === "string" ? contract.objective : undefined;
	    const coverage = Array.isArray(contract.coverage_matrix) ? contract.coverage_matrix.length : undefined;
	    upsert({
	      id: `${event.run_id}-execution-contract`,
	      kind: "coordinator",
	      title: "Execution contract",
	      detail: coverage != null ? `${coverage} coverage items` : undefined,
	      round: event.round,
	      agentId: event.agent_id,
	      agentName: event.agent_name,
	      status: "completed",
	      content: objective,
	    });
	  }
	  if (event.event === "claim_graph_delta") {
	    const delta = (event.delta && typeof event.delta === "object" ? event.delta : {}) as Record<string, unknown>;
	    const nodeCount = typeof delta.node_count === "number" ? delta.node_count : undefined;
	    const duplicates = Array.isArray(delta.duplicates) ? delta.duplicates.length : 0;
	    upsert({
	      id: `${event.run_id}-claim-delta-${event.sequence ?? events.length}`,
	      kind: "blackboard",
	      title: "Claim graph delta",
	      detail: nodeCount != null ? `${nodeCount} nodes` : undefined,
	      round: event.round,
	      agentId: event.agent_id,
	      agentName: event.agent_name,
	      status: duplicates > 0 ? "rejected" : "completed",
	      content: duplicates > 0 ? `${duplicates} duplicate claim${duplicates === 1 ? "" : "s"} collapsed` : undefined,
	    });
	  }
	  if (event.event === "coverage_matrix") {
	    const done = event.coverage_complete ?? 0;
	    const total = event.coverage_total ?? event.coverage_matrix?.length ?? 0;
	    upsert({
	      id: `${event.run_id}-coverage-${event.round}`,
	      kind: "blackboard",
	      title: "Coverage matrix",
	      detail: `${done}/${total} covered`,
	      round: event.round,
	      status: total > 0 && done >= total ? "completed" : "running",
	    });
	  }
	  if (event.event === "coherency_score") {
	    upsert({
	      id: `${event.run_id}-coherency-${event.round}-${event.agent_id}`,
	      kind: "blackboard",
	      title: `${event.agent_name ?? "Agent"} coherency`,
	      detail: event.coherency_score != null ? `${Math.round(event.coherency_score * 100)}%` : undefined,
	      round: event.round,
	      agentId: event.agent_id,
	      agentName: event.agent_name,
	      status: (event.coherency_score ?? 1) < 0.45 ? "rejected" : "completed",
	    });
	  }
	  if (event.event === "tool_phase") {
	    const proposalCount = event.proposals?.length ?? 0;
	    const resultCount = event.results?.length ?? 0;
	    upsert({
	      id: `${event.run_id}-tool-${event.round}-${event.agent_id}-${event.tool_phase}`,
	      kind: "tool",
	      title: `${event.agent_name ?? "Agent"} tools`,
	      detail: event.tool_phase,
	      round: event.round,
	      agentId: event.agent_id,
	      agentName: event.agent_name,
	      status: proposalCount > 0 ? "rejected" : "completed",
	      content:
	        proposalCount > 0
	          ? `${proposalCount} proposal${proposalCount === 1 ? "" : "s"} waiting for coordination`
	          : resultCount > 0
	            ? `${resultCount} result${resultCount === 1 ? "" : "s"} published`
	            : undefined,
	    });
	  }
	  if (event.event === "debate_skipped") {
	    upsert({
	      id: `${event.run_id}-debate-skipped-${event.round}`,
	      kind: "coordinator",
	      title: `Debate skipped round ${event.round}`,
	      detail: event.reason,
	      round: event.round,
	      status: "completed",
	      content:
	        event.coverage_complete != null && event.coverage_total != null
	          ? `${event.coverage_complete}/${event.coverage_total} covered`
	          : undefined,
	    });
	  }
	  if (event.event === "adaptive_vote") {
	    upsert({
	      id: `${event.run_id}-adaptive-vote-${event.round}`,
	      kind: "vote",
	      title: `Adaptive vote round ${event.round}`,
	      detail: event.triggers?.join(", "),
	      round: event.round,
	      status: "running",
	    });
	  }
	  if (event.event === "vote_started") {
	    upsert({
      id: `${event.run_id}-vote-${event.round}`,
      kind: "vote",
      title: `Vote after round ${event.round}`,
      round: event.round,
      status: "running",
    });
  }
  if (event.event === "agent_vote") {
    events.push({
      id: `${event.run_id}-vote-${event.round}-${event.agent_id}`,
      kind: "vote",
      title: `${event.agent_name ?? "Agent"} ${event.approve ? "approved" : "blocked"}`,
      detail: event.blocker || event.final_points || `${Math.round((event.confidence ?? 0) * 100)}% confidence`,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: event.approve ? "approved" : "rejected",
    });
  }
  if (event.event === "consensus_reached") {
    upsert({
      id: `${event.run_id}-consensus`,
      kind: "consensus",
      title: "Consensus reached",
      detail: `${event.consensus?.approvals ?? 0}/${event.consensus?.required ?? 0} approvals`,
      status: "completed",
    });
  }
  if (event.event === "coordinator_planning_started") {
    upsert({
      id: `${event.run_id}-coordinator-planning-${event.round}`,
      kind: "coordinator",
      title: `${event.agent_name ?? "Coordinator"} planning`,
      detail: "Debate focus",
      status: "running",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
	  if (event.event === "coordinator_planning_completed") {
    const guidance = (event.guidance && typeof event.guidance === "object" ? event.guidance : {}) as Record<string, unknown>;
    const summary = typeof guidance.summary === "string" ? guidance.summary : undefined;
    upsert({
      id: `${event.run_id}-coordinator-planning-${event.round}`,
      kind: "coordinator",
      title: `${event.agent_name ?? "Coordinator"} planning`,
      detail: event.duration_ms != null ? `${event.duration_ms} ms` : "Focus assigned",
      status: "completed",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      content: summary,
    });
	  }
	  if (event.event === "coordinator_redirect") {
	    upsert({
	      id: `${event.run_id}-redirect-${event.round}-${event.agent_id}`,
	      kind: "coordinator",
	      title: "Coordinator redirect",
	      detail: event.agent_id,
	      round: event.round,
	      agentId: event.agent_id,
	      status: "completed",
	      content: event.redirect,
	    });
	  }
  if (event.event === "coordinator_started") {
    upsert({
      id: `${event.run_id}-coordinator`,
      kind: "coordinator",
      title: event.agent_name ?? "Coordinator",
      detail: "Final synthesis",
      status: "running",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
  if (event.event === "coordinator_completed") {
    upsert({
      id: `${event.run_id}-coordinator`,
      kind: "coordinator",
      title: event.agent_name ?? "Coordinator",
      detail: event.duration_ms != null ? `${event.duration_ms} ms` : "Final report ready",
      status: "completed",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
  if (event.event === "team_consensus_failed") {
    upsert({
      id: `${event.run_id}-failed`,
      kind: "failed",
      title: "Consensus failed",
      detail: event.reason,
      status: "failed",
    });
  }
  if (event.event === "team_run_cancelled") {
    upsert({
      id: `${event.run_id}-cancelled`,
      kind: "cancelled",
      title: "Team run cancelled",
      status: "cancelled",
    });
  }
  if (event.event === "team_run_completed") {
    upsert({
      id: `${event.run_id}-run`,
      kind: "run",
      title: "Team Mode",
      detail: "Run completed",
      status: "completed",
    });
  }

  return { ...message, teamEvents: events };
}

function turnTraceId(event: TeamRunEvent) {
  return `${event.run_id}-round-${event.round}-${event.agent_id}`;
}

function applyToolChunk(
  chunk: StreamChunk,
  agentId: string,
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  if (!chunk.tool_call_id) return;
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      const message = closeActiveReasoning(item, true);
      const blocks = [...message.toolBlocks];
      const parts = [...message.parts];
      const existingIndex = blocks.findIndex((block) => block.id === chunk.tool_call_id);
      const existing = existingIndex >= 0 ? blocks[existingIndex] : undefined;
      const next = toolBlockFromChunk(chunk, existing);
      if (existingIndex >= 0) {
        blocks[existingIndex] = next;
      } else {
        blocks.push(next);
      }
      if (!parts.some((part) => part.toolBlockId === next.id)) {
        parts.push({
          kind: "tool",
          id: `tool-${next.id}`,
          toolBlockId: next.id,
        });
      }
      return { ...message, toolBlocks: blocks, parts };
    }),
  }));
}

function appendContentPart(parts: ChatMessagePartUi[], messageId: string, chunk: string) {
  const next = [...parts];
  const last = next.at(-1);
  if (last?.kind === "content") {
    next[next.length - 1] = { ...last, content: `${last.content ?? ""}${chunk}` };
    return next;
  }
  next.push({
    kind: "content",
    id: `${messageId}-content-${next.length}`,
    content: chunk,
  });
  return next;
}

function appendImageParts(parts: ChatMessagePartUi[], messageId: string, images: GeneratedImage[]) {
  const next = [...parts];
  for (const image of images) {
    next.push({
      kind: "image",
      id: `${messageId}-image-${next.length}`,
      image,
    });
  }
  return next;
}

function applyImageChunks(
  agentId: string,
  images: GeneratedImage[],
  set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void,
) {
  if (images.length === 0) return;
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      const next = closeActiveReasoning(item, true);
      return {
        ...next,
        parts: appendImageParts(next.parts, next.id, images),
      };
    }),
  }));
}

function normalizeStreamChunk(agentId: string, chunk: StreamChunk): StreamChunk {
  const state = thinkingStates.get(agentId) ?? createThinkingTagState();
  thinkingStates.set(agentId, state);

  const shouldFlush = Boolean(chunk.finish_reason || chunk.event === "conversation_saved");
  const split = splitThinkingTags(chunk.content ?? "", state, shouldFlush);
  const reasoning = `${chunk.reasoning_content ?? ""}${split.reasoning}`;
  const hasVisibleContent = split.content.length > 0;
  return {
    ...chunk,
    content: split.content,
    reasoning_content: reasoning || undefined,
    is_thinking: Boolean(chunk.is_thinking && !hasVisibleContent),
  };
}

function appendReasoningChunk(message: ChatMessageUi, chunk: string): ChatMessageUi {
  const blocks = [...message.reasoningBlocks];
  const parts = [...message.parts];
  let activeIndex = -1;
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (blocks[index].isStreaming) {
      activeIndex = index;
      break;
    }
  }
  const activeBlock = activeIndex >= 0 ? blocks[activeIndex] : undefined;
  const canAppend =
    activeBlock &&
    parts.at(-1)?.kind === "reasoning" &&
    parts.at(-1)?.reasoningBlockId === activeBlock.id;

  if (canAppend && activeBlock) {
    blocks[activeIndex] = {
      ...activeBlock,
      content: activeBlock.content + chunk,
      isStreaming: true,
    };
  } else {
    const id = `${message.id}-reasoning-${blocks.length}`;
    blocks.push({ id, content: chunk, isStreaming: true });
    parts.push({ kind: "reasoning", id: `part-${id}`, reasoningBlockId: id });
  }

  return {
    ...message,
    reasoning: message.reasoning + chunk,
    reasoningBlocks: blocks,
    parts,
    isReasoningStreaming: true,
  };
}

function closeActiveReasoning(message: ChatMessageUi, keepStreaming: boolean): ChatMessageUi {
  const blocks = message.reasoningBlocks.map((block) => ({ ...block, isStreaming: false }));
  return {
    ...message,
    reasoningBlocks: blocks,
    isReasoningStreaming: false,
    isStreaming: keepStreaming,
  };
}

function toolBlockFromChunk(chunk: StreamChunk, existing?: ToolBlockUi): ToolBlockUi {
  const status = parseToolStatus(chunk.tool_status);
  const name = chunk.tool_name ?? existing?.name ?? "tool";
  const data = mergeToolData(existing?.data, normalizeToolInput(name, chunk.tool_input), chunk.tool_data);
  const path =
    stringValue(data?.display_path) ??
    stringValue(data?.path) ??
    stringValue(data?.url) ??
    stringValue(chunk.tool_input?.path);
  const content =
    stringValue(data?.content) ??
    chunk.tool_result ??
    chunk.tool_error ??
    existing?.content ??
    "";
  return {
    id: chunk.tool_call_id ?? existing?.id ?? "",
    name,
    status,
    title: toolTitle(name, path),
    message: toolMessage(chunk, existing, status),
    content,
    path,
    data,
    isCollapsed: shouldCollapseToolBlock(name, status),
  };
}

function normalizeToolInput(name: string, input?: Record<string, unknown>) {
  if (name !== "Write" || !input) return input;
  const writtenContent = input.content;
  if (typeof writtenContent !== "string") return input;
  return {
    ...input,
    written_content: writtenContent,
  };
}

function mergeToolData(
  existing?: Record<string, unknown>,
  input?: Record<string, unknown>,
  result?: Record<string, unknown>,
) {
  const merged = { ...(existing ?? {}), ...(input ?? {}), ...(result ?? {}) };
  return Object.keys(merged).length ? merged : undefined;
}

function toolMessage(chunk: StreamChunk, existing: ToolBlockUi | undefined, status: ToolBlockStatus) {
  if (chunk.tool_message) return chunk.tool_message;
  if (status === "queued" || status === "running") return existing?.message ?? "";
  return "";
}

function shouldCollapseToolBlock(name: string, status: ToolBlockStatus) {
  if (status !== "completed") return false;
  return new Set([
    "Read",
    "read_file",
    "shell",
    "Glob",
    "Grep",
    "search_files",
    "LSP",
    "WebFetch",
    "Task",
    "TaskCreate",
    "TaskGet",
    "TaskUpdate",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TodoWrite",
    "Write",
  ]).has(name);
}

function toolTitle(name: string, path?: string) {
  if (name === "Read" || name === "read_file") return path ? `Read ${path}` : "Reading file";
  if (name === "Grep" || name === "search_files") return "Grep";
  if (name === "Glob") return "Glob";
  if (name === "shell") return "Shell command";
  if (name === "WebFetch") return path ? `Fetch ${path}` : "WebFetch";
  if (name === "LSP") return "LSP";
  if (name === "TodoWrite") return "TodoWrite";
  if (name.startsWith("Task")) return name;
  return name;
}

function messageFromPersisted(message: PersistedMessage): ChatMessageUi {
  const role = message.role === "user" ? "user" : message.role === "tool" ? "tool" : "agent";
  const timestamp = message.timestamp ?? String(Date.now());
  if (role === "tool") {
    const metadata = message.metadata ?? {};
    const data = isRecord(metadata.data) ? metadata.data : undefined;
    const name = stringValue(metadata.tool_name) ?? "tool";
    const status = parseToolStatus(stringValue(metadata.status));
    const path = stringValue(data?.display_path) ?? stringValue(data?.path);
    const block: ToolBlockUi = {
      id: message.tool_call_id ?? timestamp,
      name,
      status,
      title: toolTitle(name, path),
      message: "",
      content: stringValue(data?.content) ?? message.content,
      path,
      data,
      isCollapsed: shouldCollapseToolBlock(name, status),
    };
    return {
      id: timestamp,
      role,
      label: "Tool",
      content: "",
      reasoning: "",
      reasoningBlocks: [],
      toolBlocks: [block],
      teamEvents: [],
      parts: [{ kind: "tool", id: `tool-${block.id}`, toolBlockId: block.id }],
      isStreaming: false,
      isReasoningStreaming: false,
    };
  }

  const reasoning = message.reasoning_content ?? "";
  const images = imageListFromMetadata(message.metadata?.images);
  const reasoningBlock =
    reasoning.trim().length > 0
      ? { id: `reasoning-${timestamp}`, content: reasoning, isStreaming: false }
      : undefined;
  return {
    id: timestamp,
    role,
    label: role === "user" ? "You" : "PersonAgent",
    content: message.content,
    reasoning,
    reasoningBlocks: reasoningBlock ? [reasoningBlock] : [],
    toolBlocks: [],
    teamEvents: [],
    parts: [
      ...(reasoningBlock
        ? [{ kind: "reasoning" as const, id: `part-${reasoningBlock.id}`, reasoningBlockId: reasoningBlock.id }]
        : []),
      ...(message.content
        ? [{ kind: "content" as const, id: `content-${timestamp}`, content: message.content }]
        : []),
      ...images.map((image, index) => ({
        kind: "image" as const,
        id: `image-${timestamp}-${index}`,
        image,
      })),
    ],
    isStreaming: false,
    isReasoningStreaming: false,
  };
}

function imageListFromMetadata(value: unknown): GeneratedImage[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isGeneratedImage);
}

function isGeneratedImage(value: unknown): value is GeneratedImage {
  if (!isRecord(value)) return false;
  return typeof value.mime_type === "string" && typeof value.data === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}
