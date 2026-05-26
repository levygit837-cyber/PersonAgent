import type { ThinkingTagState } from "../../lib/reasoning";
import { todoItems } from "../../lib/todos";
import { useAppStore } from "../app-store";
import type { ConversationForkMessagePayload } from "../../api/client";
import type {
  ChatMessageUi,
  ConversationStatus,
  ContextAttachment,
  ModelProvider,
  PersistedMessage,
  PlanApprovalUi,
  ReasoningPreset,
  SessionUsage,
  TodoDockSnapshotUi,
  ToolApprovalUi,
  ToolBlockStatus,
  ToolBlockUi,
} from "../../types/chat";

// ---------------------------------------------------------------------------
// Module-level mutable state
// ---------------------------------------------------------------------------

export const thinkingStates = new Map<string, ThinkingTagState>();
export const textFlushBuffers = new Map<string, TextFlushBuffer>();
export const STREAM_TEXT_FLUSH_MS = 150;
export const MAX_TEAM_AGENT_LOGS = 80;
export let teamAgentLogSequence = 0;
export function bumpTeamAgentLogSequence() {
  return ++teamAgentLogSequence;
}
export const liveTokenTotals = {
  exactAgent: 0,
  exactThinking: 0,
  estimatedAgent: 0,
  estimatedThinking: 0,
};

export type TextFlushBuffer = {
  content: string;
  reasoning: string;
  finishReason?: string;
  timer?: ReturnType<typeof setTimeout>;
};

// ---------------------------------------------------------------------------
// Store helper types (used by slices and internal functions)
// ---------------------------------------------------------------------------

export type ChatSet = (
  partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
) => void;

export type ChatGet = () => ChatState;

export type SessionUsageKey = keyof SessionUsage;

export interface SendMessageOptions {
  contextAttachments?: ContextAttachment[];
  displayAttachments?: ContextAttachment[];
  hideUserMessage?: boolean;
  planModeRequested?: boolean;
  permissionMode?: string;
}

export interface ChatState {
  workspaceRoot?: string | null;
  messages: ChatMessageUi[];
  composerAnnotations: ComposerAnnotation[];
  conversationId?: string;
  conversationTitle?: string;
  error?: string;
  isStreaming: boolean;
  isFinalizing: boolean;
  isProcessingPlanDecision: boolean;
  loadingConversationId?: string;
  conversationStatuses: Record<string, ConversationStatus>;
  activeController?: AbortController;
  activeAgentId?: string;
  pendingPlanApproval?: PlanApprovalUi;
  composerPlanMode: boolean;
  pendingToolApproval?: ToolApprovalUi;
  nextStepSuggestion?: string;
  liveSessionUsage: SessionUsage;
  liveSubAgentIds: string[];
  latestTodoSnapshot?: TodoDockSnapshotUi;
  contextTokenEstimate: number;
  contextWindowEstimate?: number;
  browserToolBlocks: ToolBlockUi[];
  setWorkspaceRoot: (workspaceRoot?: string | null) => void;
  addComposerAnnotation: (annotation: ComposerAnnotation) => void;
  removeComposerAnnotation: (id: number) => void;
  clearComposerAnnotations: () => void;
  setComposerPlanMode: (active: boolean) => void;
  loadConversation: (id: string, workspaceRoot?: string | null) => Promise<void>;
  startNewConversation: () => void;
  sendMessage: (text: string, systemPrompt?: string, options?: SendMessageOptions) => Promise<void>;
  approvePendingPlan: (feedback?: string) => Promise<void>;
  continuePendingPlan: (feedback?: string) => Promise<void>;
  cancelPendingPlan: (feedback?: string) => Promise<void>;
  approvePendingTool: () => Promise<void>;
  rejectPendingTool: () => Promise<void>;
  setAgentFeedback: (messageId: string, feedback: "positive" | "negative") => void;
  setReasoningBlockExpanded: (messageId: string, blockId: string, expanded: boolean) => void;
  regenerateAgentMessage: (messageId: string) => Promise<void>;
  rewindUserMessage: (messageId: string, content: string) => Promise<void>;
  branchAgentMessage: (messageId: string) => Promise<void>;
  stopStreaming: () => void;
  clearError: () => void;
}

export interface ComposerAnnotation {
  id: number;
  source?: "file" | "browser";
  fileName: string;
  filePath: string;
  displayPath: string;
  startLine: number;
  endLine: number;
  text: string;
  selectedLines: string;
  language: string;
  browserUrl?: string;
  browserTitle?: string;
  browserNodeId?: string;
  browserSelector?: string;
  browserRole?: string;
  browserQuote?: string;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function getEffectiveWorkspaceRoot(state: ChatState) {
  return state.workspaceRoot?.trim() || useAppStore.getState().selectedWorkspace?.trim() || undefined;
}

export function setConversationStatus(
  set: ChatSet,
  conversationId: string | undefined | null,
  status: ConversationStatus,
) {
  if (!conversationId) return;
  set((state) => ({
    conversationStatuses: {
      ...state.conversationStatuses,
      [conversationId]: status,
    },
  }));
  window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
}

export function inferConversationStatus(messages: PersistedMessage[]): ConversationStatus {
  const metadata = messages
    .map((message) => message.metadata)
    .filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object"));

  if (metadata.some((item) => item.is_error === true || item.status === "error" || item.status === "failed")) {
    return "error";
  }
  return "idle";
}

export function conversationForkMessages(messages: ChatMessageUi[]): ConversationForkMessagePayload[] {
  const payload: ConversationForkMessagePayload[] = [];
  for (const message of messages) {
    if (message.role === "user") {
      payload.push({
        role: "user",
        content: message.content,
        metadata: message.metadata,
      });
      continue;
    }

    if (message.role === "tool") {
      const block = message.toolBlocks[0];
      payload.push({
        role: "tool",
        content: block?.content || message.content,
        tool_call_id: block?.id,
        metadata: {
          ...(message.metadata ?? {}),
          tool_name: block?.name,
          status: block?.status,
          data: block?.data,
        },
      });
      continue;
    }

    const metadata = {
      ...(message.metadata ?? {}),
      ...(message.reasoning.trim() ? { reasoning_content: message.reasoning } : {}),
    };
    if (message.content.trim() || message.reasoning.trim()) {
      payload.push({
        role: "assistant",
        content: message.content,
        metadata,
      });
    }
  }
  return payload;
}

export function previousUserMessageIndex(messages: ChatMessageUi[], beforeIndex: number) {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") return index;
  }
  return -1;
}

export function contextAttachmentsFromMessage(message: ChatMessageUi): ContextAttachment[] {
  const raw = message.metadata?.context_attachments;
  if (!Array.isArray(raw)) return [];
  return raw.filter(isContextAttachment);
}

export function isContextAttachment(value: unknown): value is ContextAttachment {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) && typeof (value as { type?: unknown }).type === "string");
}

export function setAgentMessageActionState(
  set: ChatSet,
  messageId: string,
  metadata: Record<string, unknown>,
) {
  set((state) => ({
    messages: state.messages.map((message) =>
      message.id === messageId
        ? {
            ...message,
            metadata: {
              ...(message.metadata ?? {}),
              ...metadata,
            },
          }
        : message,
    ),
  }));
}

export function worktreeSlug(conversationId: string | undefined, messageId: string) {
  const source = `${conversationId || "new"}-${messageId}`.toLowerCase();
  return source.replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "message";
}

// ---------------------------------------------------------------------------
// Slash-command helpers
// ---------------------------------------------------------------------------


export function isActiveGenerationState(state: ChatState, controller: AbortController, agentId: string) {
  return state.activeController === controller || state.activeAgentId === agentId;
}

export function hasActiveToolBlocks(state: ChatState, agentId: string): boolean {
  const agentMessage = state.messages.find((m) => m.id === agentId);
  if (!agentMessage) return false;
  return agentMessage.toolBlocks.some(
    (block) => block.status === "running" || block.status === "queued"
  );
}

// ---------------------------------------------------------------------------
// Todo snapshot helpers
// ---------------------------------------------------------------------------

export function latestTodoSnapshotFromMessages(messages: ChatMessageUi[], activeAgentId?: string): TodoDockSnapshotUi | undefined {
  const preferred = activeAgentId ? messages.find((message) => message.id === activeAgentId) : undefined;
  const message = preferred ?? latestAgentMessageWithTodo(messages);
  return message ? latestTodoSnapshotFromMessage(message) : undefined;
}

function latestAgentMessageWithTodo(messages: ChatMessageUi[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "agent" && message.toolBlocks.some(isTodoToolBlock)) return message;
  }
  return undefined;
}

export function latestTodoSnapshotFromMessage(message: ChatMessageUi): TodoDockSnapshotUi | undefined {
  const blocks = message.toolBlocks.filter(isTodoToolBlock);
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    const todos = todoItems(block);
    if (todos.length === 0) continue;
    return {
      key: `${block.id}:${todos.map((todo) => `${todo.id}:${todo.status}:${todo.content}`).join("|")}`,
      toolName: block.name,
      updateCount: blocks.length,
      status: todoSnapshotStatus(blocks),
      todos,
    };
  }
  return undefined;
}

function todoSnapshotStatus(blocks: ToolBlockUi[]): ToolBlockStatus {
  if (blocks.some((block) => block.status === "error" || block.status === "permission_required")) return "error";
  if (blocks.some((block) => block.status === "running" || block.status === "queued")) return "running";
  return "completed";
}

export function isTodoToolBlock(block: Pick<ToolBlockUi, "name">) {
  return block.name.toLowerCase().startsWith("todo");
}

// ---------------------------------------------------------------------------
// Browser tool block helpers
// ---------------------------------------------------------------------------

export function browserToolBlocksFromMessages(messages: ChatMessageUi[]) {
  const blocks: ToolBlockUi[] = [];
  for (const message of messages) {
    if (message.role !== "agent") continue;
    for (const block of message.toolBlocks) {
      if (isBrowserToolBlock(block)) blocks.push(block);
    }
  }
  return blocks.slice(-80);
}

export function upsertBrowserToolBlock(blocks: ToolBlockUi[], block: ToolBlockUi) {
  const existingIndex = blocks.findIndex((item) => item.id === block.id);
  const next = existingIndex >= 0 ? [...blocks] : [...blocks, block];
  if (existingIndex >= 0) next[existingIndex] = block;
  return next.slice(-80);
}

export function isBrowserToolBlock(block: Pick<ToolBlockUi, "name">) {
  return block.name.startsWith("Browser");
}

// ---------------------------------------------------------------------------
// Context-window estimation helpers
// ---------------------------------------------------------------------------


export function findAgentMessageIdForTool(messages: ChatMessageUi[], toolCallId: string) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "agent" && message.toolBlocks.some((block) => block.id === toolCallId)) {
      return message.id;
    }
  }
  return undefined;
}

// Re-export extracted modules
export * from "./chat-internal/commands";
export * from "./chat-internal/tokens";
