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

export const localSlashCommands = new Set([
  "clear",
  "model",
  "effort",
  "skills",
  "permissions",
  "usage",
  "status",
  "help",
]);

export const modelProviders: ModelProvider[] = ["llama", "nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"];
export const reasoningPresetValues: ReasoningPreset[] = ["low", "medium", "high", "xhigh", "max"];

export function handleLocalSlashCommand(
  message: string,
  set: ChatSet,
  get: () => ChatState,
) {
  const parsed = parseLocalSlashCommand(message);
  if (!parsed || !localSlashCommands.has(parsed.name)) return false;

  if (parsed.name === "clear") {
    get().startNewConversation();
    return true;
  }

  const app = useAppStore.getState();
  let response = "";
  if (parsed.name === "help") {
    response = commandHelpText();
  } else if (parsed.name === "skills") {
    app.setSection("skills");
    response = "Opened the Skills workspace. Use `/skill-name` in chat to invoke an enabled user skill.";
  } else if (parsed.name === "model") {
    response = applyModelCommand(parsed.args, app);
  } else if (parsed.name === "effort") {
    response = applyEffortCommand(parsed.args, app);
  } else if (parsed.name === "permissions") {
    response = permissionsCommandText();
  } else if (parsed.name === "usage") {
    response = usageCommandText(get().liveSessionUsage);
  } else if (parsed.name === "status") {
    response = statusCommandText(get(), app);
  }

  appendLocalCommandResult(set, response || `Command /${parsed.name} completed.`);
  return true;
}

export function parseLocalSlashCommand(message: string) {
  const trimmed = message.trim();
  if (!trimmed.startsWith("/") || trimmed === "/") return null;
  const [head, ...rest] = trimmed.slice(1).split(/\s+/);
  if (!head) return null;
  return { name: head.toLowerCase(), args: rest };
}

export function appendLocalCommandResult(set: ChatSet, content: string) {
  const now = Date.now();
  const agentId = `${now}_command_result`;
  const agentMessage: ChatMessageUi = {
    id: agentId,
    role: "agent",
    label: "PersonAgent",
    content,
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [{ kind: "content", id: `content-${agentId}`, content }],
    isStreaming: false,
    isReasoningStreaming: false,
    metadata: {
      local_command_result: true,
    },
  };
  set((state) => ({
    messages: [...state.messages, agentMessage],
    error: undefined,
    pendingPlanApproval: undefined,
    pendingToolApproval: undefined,
  }));
}

export function applyModelCommand(args: string[], app: ReturnType<typeof useAppStore.getState>) {
  if (args.length === 0) {
    return [
      `Current model: ${app.provider}/${app.selectedModelId}`,
      "Usage: `/model <model-id>`, `/model <provider> <model-id>`, or `/model <provider>:<model-id>`.",
    ].join("\n");
  }

  const raw = args.join(" ").trim();
  const colonMatch = raw.match(/^([a-z]+):(.+)$/i);
  let provider: ModelProvider | undefined;
  let modelId = raw;
  if (colonMatch) {
    const candidate = normalizeProvider(colonMatch[1]);
    if (candidate) {
      provider = candidate;
      modelId = colonMatch[2].trim();
    }
  } else {
    const first = normalizeProvider(args[0]);
    if (first) {
      provider = first;
      modelId = args.slice(1).join(" ").trim();
    }
  }

  if (!modelId) {
    if (!provider) return "No model or provider was provided.";
    app.setProvider(provider);
    return `Provider changed to ${provider}. Current model: ${useAppStore.getState().selectedModelId}`;
  }

  const nextProvider = provider ?? inferProviderForModel(modelId) ?? app.provider;
  app.setProvider(nextProvider);
  useAppStore.getState().setSelectedModelId(modelId);
  return `Model changed to ${nextProvider}/${modelId}.`;
}

export function applyEffortCommand(args: string[], app: ReturnType<typeof useAppStore.getState>) {
  const requested = (args[0] || "").toLowerCase();
  if (!requested) {
    return `Current reasoning effort: ${app.reasoningPreset}\nUsage: /effort low|medium|high|xhigh|max`;
  }
  if (!reasoningPresetValues.includes(requested as ReasoningPreset)) {
    return `Unknown reasoning effort: ${requested}. Use low, medium, high, xhigh, or max.`;
  }
  app.setReasoningPreset(requested as ReasoningPreset);
  return `Reasoning effort changed to ${requested}.`;
}

export function normalizeProvider(value?: string): ModelProvider | undefined {
  const normalized = (value || "").toLowerCase();
  return modelProviders.find((provider) => provider === normalized);
}

export function inferProviderForModel(modelId: string): ModelProvider | undefined {
  const normalized = modelId.toLowerCase();
  if (normalized === "local-model") return "llama";
  if (normalized.startsWith("deepseek/deepseek-v4-")) return "zenmux";
  if (normalized.startsWith("deepseek-v4-")) return "deepseek";
  if (normalized.startsWith("gpt-") || normalized.startsWith("o")) return "codex";
  if (normalized.includes("gemini")) return "vertex";
  if (normalized.includes("kimi")) return "kimi";
  if (normalized.includes("nvidia") || normalized.includes("nemotron")) return "nvidia";
  return undefined;
}

export function commandHelpText() {
  return [
    "Local commands:",
    "/clear - clear the current chat UI state.",
    "/model [provider:]<model-id> - show or change the selected model.",
    "/effort <low|medium|high|xhigh|max> - show or change reasoning effort.",
    "/skills - open the Skills workspace.",
    "/permissions - show the current tool permission behavior.",
    "/usage - show live session usage counters.",
    "/status - show local chat/workspace/model status.",
    "",
    "Model-visible commands:",
    "/plan, /memory, /mcp, /context, /compact, /diff, /files, /branch, /doctor, Markdown commands, and enabled skills are sent to the model with hidden command context.",
  ].join("\n");
}

export function permissionsCommandText() {
  return [
    "Tool permissions are enforced by the runtime.",
    "Read-only tools can run directly when allowed. Risky tools pause on a permission_required event and resume only after approval.",
    "Command frontmatter can still narrow allowed tools for that turn.",
  ].join("\n");
}

export function usageCommandText(usage: SessionUsage) {
  return [
    "Live session usage:",
    `Context tokens: ${usageLabel(usage.context_tokens)}`,
    `Agent output tokens: ${usageLabel(usage.agent_output_tokens)}`,
    `Thinking tokens: ${usageLabel(usage.thinking_output_tokens)}`,
    `Tool calls: ${usageLabel(usage.tool_calls)}`,
    `Skills used: ${usageLabel(usage.skills_used_count)}`,
    `MCP calls: ${usageLabel(usage.mcp_calls_count)}`,
    `Plans created: ${usageLabel(usage.plans_created)}`,
    `Todos created: ${usageLabel(usage.todos_created)}`,
    `Subagents used: ${usageLabel(usage.subagents_used)}`,
  ].join("\n");
}

export function statusCommandText(state: ChatState, app: ReturnType<typeof useAppStore.getState>) {
  return [
    "Local status:",
    `Workspace: ${getEffectiveWorkspaceRoot(state) || "(none)"}`,
    `Model: ${app.provider}/${app.selectedModelId}`,
    `Reasoning effort: ${app.reasoningPreset}`,
    `Conversation: ${state.conversationId || "(new)"}`,
    `Team Mode: ${app.teamMode ? "on" : "off"}`,
    `Messages loaded: ${state.messages.length}`,
    `Composer attachments: ${state.composerAnnotations.length}`,
  ].join("\n");
}

export function usageLabel(metric: SessionUsage[keyof SessionUsage]) {
  return `${metric.value}${metric.estimated ? " estimated" : ""}`;
}

// ---------------------------------------------------------------------------
// Generation / streaming helpers
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

export function latestContextWindowEstimate(messages: ChatMessageUi[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const value = numberValue(messages[index].metadata?.context_window_tokens);
    if (value !== undefined && value > 0) return value;
  }
  return undefined;
}

export function estimateConversationContextTokens(messages: ChatMessageUi[]) {
  return messages.reduce((total, message) => total + estimateMessageContextTokens(message), 0);
}

function estimateMessageContextTokens(message: ChatMessageUi) {
  const roleTokens = estimateTextTokens(message.role) + 4;
  const contentTokens = estimateTextTokens(message.content);
  const reasoningTokens = estimateTextTokens(message.reasoning);
  const toolTokens = message.toolBlocks.reduce(
    (sum, block) =>
      sum +
      estimateTextTokens(block.name) +
      estimateTextTokens(block.path) +
      estimateTextTokens(block.content) +
      estimateUnknownTokens(block.data),
    0,
  );
  const attachmentTokens = contextAttachmentsFromMessage(message).reduce(
    (sum, item) => sum + estimateAttachmentTokens(item),
    0,
  );
  return roleTokens + contentTokens + reasoningTokens + toolTokens + attachmentTokens;
}

function estimateAttachmentTokens(attachment: ContextAttachment) {
  const explicitText =
    estimateTextTokens(attachment.text) +
    estimateTextTokens(attachment.content) +
    estimateTextTokens(attachment.content_preview) +
    estimateTextTokens(attachment.quote);
  const charCount = numberValue(attachment.content_char_count);
  return explicitText || (charCount ? Math.max(1, Math.ceil(charCount / 4)) : estimateUnknownTokens(attachment));
}

function estimateUnknownTokens(value: unknown) {
  if (value === undefined || value === null) return 0;
  if (typeof value === "string") return estimateTextTokens(value);
  if (typeof value === "number" || typeof value === "boolean") return estimateTextTokens(String(value));
  try {
    return estimateTextTokens(JSON.stringify(value));
  } catch {
    return 0;
  }
}

export function estimateTextTokens(value: unknown) {
  if (typeof value !== "string" || value.length === 0) return 0;
  return Math.max(1, Math.ceil(value.length / 4));
}

// ---------------------------------------------------------------------------
// Misc pure helpers
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

export function resetLiveTokenTotals() {
  liveTokenTotals.exactAgent = 0;
  liveTokenTotals.exactThinking = 0;
  liveTokenTotals.estimatedAgent = 0;
  liveTokenTotals.estimatedThinking = 0;
}

export function incrementLiveUsage(
  set: (partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void,
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

export function isTodoToolName(name?: string) {
  return Boolean(name && name.toLowerCase().startsWith("todo"));
}

export function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

export function estimateTokens(value: string) {
  if (!value) return 0;
  return Math.max(1, Math.ceil(value.length / 4));
}

export function normalizeUsageTokens(usage?: Record<string, unknown>) {
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
