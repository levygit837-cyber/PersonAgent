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
  type ChatMessagePartUi,
  type ChatMessageUi,
  type GeneratedImage,
  type PersistedMessage,
  type PlanApprovalUi,
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
  error?: string;
  isStreaming: boolean;
  activeController?: AbortController;
  activeAgentId?: string;
  pendingPlanApproval?: PlanApprovalUi;
  pendingToolApproval?: ToolApprovalUi;
  nextStepSuggestion?: string;
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

  loadConversation: async (id) => {
    try {
      const detail = await getConversation(useAppStore.getState().baseUrl, id);
      set({
        conversationId: detail.id,
        messages: detail.messages
          .filter((message) => message.role !== "system")
          .map(messageFromPersisted),
        pendingPlanApproval: undefined,
        pendingToolApproval: undefined,
        nextStepSuggestion: undefined,
        error: undefined,
      });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) });
    }
  },

  startNewConversation: () => {
    get().stopStreaming();
    set({
      messages: [],
      conversationId: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      error: undefined,
    });
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
    set((state) => ({
      messages: [...state.messages, userMessage, agentMessage],
      isStreaming: true,
      activeController: controller,
      activeAgentId: agentId,
      pendingPlanApproval: undefined,
      nextStepSuggestion: undefined,
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
      if (!controller.signal.aborted) {
        set({ error: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      flushTeamDeltaBuffers(agentId, set);
      flushTextBuffer(agentId, set);
      thinkingStates.delete(agentId);
      set((state) => ({
        isStreaming: false,
        activeController: undefined,
        activeAgentId: undefined,
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
      activeController: undefined,
      activeAgentId: undefined,
      messages: state.messages.map((item) =>
        item.id === agentId ? closeActiveReasoning(item, false) : item,
      ),
    }));
  },

  clearError: () => set({ error: undefined }),
}));

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
    set({
      error: chunk.error,
      messages: get().messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    });
    return;
  }

  if (chunk.event === "conversation" && chunk.conversation_id) {
    flushTextBuffer(agentId, set);
    set({ conversationId: chunk.conversation_id });
    void useAppStore.getState().associateConversation(chunk.conversation_id, workspaceRoot);
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    return;
  }

  if (chunk.event === "plan_approval_requested") {
    flushTextBuffer(agentId, set);
    thinkingStates.delete(agentId);
    set((state) => ({
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
    flushTextBuffer(agentId, set);
    const suggestion =
      typeof chunk.next_step_suggestion === "string" && chunk.next_step_suggestion.trim()
        ? chunk.next_step_suggestion.trim()
        : undefined;
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    set((state) => ({
      nextStepSuggestion: suggestion,
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
    flushTextBuffer(agentId, set);
    if (chunk.event === "permission_required" && chunk.approval_id) {
      set({ pendingToolApproval: toolApprovalFromChunk(chunk) });
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

  set((state) => ({
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
      const isFinalFinish = Boolean(finishReason && finishReason !== "tool_calls");
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

  if (event.event === "agent_delta") {
    queueTeamDeltaEvent(agentId, event, set);
    return;
  }

  if (event.event === "final_delta") {
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
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
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
      status: "running",
      round: event.round,
    });
  }
  if (event.event === "agent_turn_started") {
    upsert({
      id: turnTraceId(event),
      kind: "turn",
      title: event.agent_name ?? event.agent_id ?? "Agent",
      detail: event.agent_role,
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
    upsert({
      id,
      kind: "turn",
      title: event.agent_name ?? existing?.title ?? event.agent_id ?? "Agent",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "completed",
      content: existing?.content || event.content || event.digest,
      detail: event.duration_ms != null ? `${event.duration_ms} ms` : existing?.detail,
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
