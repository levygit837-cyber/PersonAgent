import { useAppStore } from "../app-store";
import {
  emptySessionUsage,
  type ChatMessagePartUi,
  type ChatMessageUi,
  type GeneratedImage,
  type StreamChunk,
  type ToolBlockStatus,
  type ToolBlockUi,
  isToolEvent,
  isToolGroupEvent,
  parseToolStatus,
} from "../../types/chat";
import { createThinkingTagState, splitThinkingTags } from "../../lib/reasoning";
import type { ChatState } from "./internal";
import {
  thinkingStates,
  textFlushBuffers,
  STREAM_TEXT_FLUSH_MS,
  setConversationStatus,
  estimateConversationContextTokens,
  latestContextWindowEstimate,
  latestTodoSnapshotFromMessages,
  latestTodoSnapshotFromMessage,
  upsertBrowserToolBlock,
  isTodoToolBlock,
  isTodoToolName,
  isBrowserToolBlock,
  resetLiveTokenTotals,
  incrementLiveUsage,
  normalizeUsageTokens,
  estimateTokens,
  liveTokenTotals,
  hasActiveToolBlocks,
  numberValue,
} from "./internal";
import {
  planApprovalFromChunk,
  attachPlanApprovalArtifact,
  toolApprovalFromChunk,
} from "./approval-helpers";

type SetFn = (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}

export function applyLiveToolUsage(
  chunk: StreamChunk,
  set: SetFn,
) {
  if (chunk.event === "tool_call_started") {
    incrementLiveUsage(set, "tool_calls", 1);
    if (chunk.tool_name === "Skill") incrementLiveUsage(set, "skills_used_count", 1);
    if (chunk.tool_name?.startsWith("mcp__") || chunk.tool_data?.is_mcp === true) {
      incrementLiveUsage(set, "mcp_calls_count", 1);
    }
  }
  if (chunk.event === "tool_result" && isTodoToolName(chunk.tool_name)) {
    const todos = chunk.tool_data?.todos;
    incrementLiveUsage(set, "todos_created", Array.isArray(todos) ? todos.length : 1);
  }
}

export function applyLiveTokenUsage(
  chunk: Pick<StreamChunk, "content" | "reasoning_content" | "usage">,
  set: SetFn,
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

function applyPromptContextChunk(
  chunk: StreamChunk,
  agentId: string,
  set: SetFn,
) {
  const metadata = contextMetadataFromChunk(chunk);
  const contextTokens =
    numberValue(metadata.context_tokens_after_turn_estimated) ??
    numberValue(metadata.context_tokens_estimated) ??
    numberValue(metadata.prompt_tokens_estimated);
  set((state) => ({
    liveSessionUsage:
      contextTokens === undefined
        ? state.liveSessionUsage
        : {
            ...state.liveSessionUsage,
            context_tokens: {
              value: contextTokens,
              estimated: true,
            },
          },
    contextTokenEstimate: contextTokens ?? state.contextTokenEstimate,
    contextWindowEstimate: numberValue(metadata.context_window_tokens) ?? state.contextWindowEstimate,
    messages: state.messages.map((item) =>
      item.id === agentId ? attachContextMetadata(item, chunk) : item,
    ),
  }));
}

function withVisibleTerminalNotice(chunk: StreamChunk): StreamChunk {
  if (chunk.content || chunk.reasoning_content) return chunk;
  if (chunk.event === "tool_iterations_exceeded") {
    const iterations = typeof chunk.tool_iterations === "number" ? chunk.tool_iterations : undefined;
    return {
      ...chunk,
      content: iterations
        ? `Tool execution stopped after ${iterations} iterations before the model produced a final answer.`
        : "Tool execution stopped before the model produced a final answer.",
      finish_reason: chunk.finish_reason ?? "tool_iterations_exceeded",
    };
  }
  if (chunk.event === "empty_model_response") {
    return {
      ...chunk,
      content: "The model stopped after tool execution without producing a visible final answer.",
      finish_reason: chunk.finish_reason ?? "empty_model_response",
    };
  }
  return chunk;
}

const contextMetadataKeys = [
  "context_tokens_estimated",
  "context_tokens_after_turn_estimated",
  "context_window_tokens",
  "context_compacted",
  "prompt_tokens_estimated",
  "memory_trace",
] as const;

function attachContextMetadata(message: ChatMessageUi, chunk: StreamChunk): ChatMessageUi {
  const metadata = contextMetadataFromChunk(chunk);
  if (Object.keys(metadata).length === 0) return message;
  return {
    ...message,
    metadata: {
      ...(message.metadata ?? {}),
      ...metadata,
    },
  };
}

function contextMetadataFromChunk(chunk: StreamChunk): Record<string, unknown> {
  const metadata: Record<string, unknown> = {};
  const topLevel = chunk as Record<string, unknown>;
  const nested = isRecord(chunk.metadata) ? chunk.metadata : {};
  for (const key of contextMetadataKeys) {
    const value = topLevel[key] ?? nested[key];
    if (value !== undefined && value !== null) metadata[key] = value;
  }
  return metadata;
}

export function queueTextChunk(
  agentId: string,
  chunk: StreamChunk,
  set: SetFn,
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

export function flushTextBuffer(
  agentId: string,
  set: SetFn,
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

function applyToolChunk(
  chunk: StreamChunk,
  agentId: string,
  set: SetFn,
) {
  if (!chunk.tool_call_id) return;
  set((state) => {
    let updatedAgentMessage: ChatMessageUi | undefined;
    let updatedBlock: ToolBlockUi | undefined;
    const messages = state.messages.map((item) => {
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
      updatedBlock = next;
      updatedAgentMessage = { ...message, toolBlocks: blocks, parts };
      return updatedAgentMessage;
    });
    return {
      messages,
      latestTodoSnapshot: updatedAgentMessage
        ? latestTodoSnapshotFromMessage(updatedAgentMessage) ??
          (updatedAgentMessage.toolBlocks.some(isTodoToolBlock) ? undefined : state.latestTodoSnapshot)
        : state.latestTodoSnapshot,
      browserToolBlocks: updatedBlock && isBrowserToolBlock(updatedBlock)
        ? upsertBrowserToolBlock(state.browserToolBlocks, updatedBlock)
        : state.browserToolBlocks,
    };
  });
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
  set: SetFn,
) {
  if (images.length === 0) return;
  const normalizedImages = normalizeGeneratedImageUrls(images);
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      const next = closeActiveReasoning(item, true);
      return {
        ...next,
        parts: appendImageParts(next.parts, next.id, normalizedImages),
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

export function appendReasoningChunk(message: ChatMessageUi, chunk: string): ChatMessageUi {
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
    const previousUserExpanded = blocks[blocks.length - 1]?.userExpanded;
    blocks.push({ id, content: chunk, isStreaming: true, userExpanded: previousUserExpanded });
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

export function closeActiveReasoning(message: ChatMessageUi, keepStreaming: boolean): ChatMessageUi {
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

export function shouldCollapseToolBlock(name: string, status: ToolBlockStatus) {
  if (status !== "completed") return false;
  if (isTodoToolName(name)) return false;
  return new Set([
    "Read",
    "read_file",
    "shell",
    "Glob",
    "Grep",
    "search_files",
    "LSP",
    "WebFetch",
    "BrowserSearch",
    "BrowserOpen",
    "BrowserListTabs",
    "BrowserExtractContent",
    "BrowserReadContentChunk",
    "BrowserGetHtml",
    "BrowserGetElementMap",
    "BrowserClick",
    "BrowserType",
    "BrowserScreenshot",
    "BrowserCloseTab",
    "BrowserReadConsole",
    "BrowserScript",
    "BrowserScroll",
    "BrowserReload",
    "BrowserHistory",
    "BrowserSwitchTab",
    "BrowserWait",
    "BrowserAct",
    "Task",
    "TaskCreate",
    "TaskGet",
    "TaskUpdate",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "Write",
    "Edit",
  ]).has(name);
}

export function toolTitle(name: string, path?: string) {
  if (name === "Read" || name === "read_file") return path ? `Read ${path}` : "Reading file";
  if (name === "Grep" || name === "search_files") return "Grep";
  if (name === "Glob") return "Glob";
  if (name === "shell") return "Shell command";
  if (name === "WebFetch") return path ? `Fetch ${path}` : "WebFetch";
  if (name === "BrowserSearch") return "BrowserSearch";
  if (name === "BrowserOpen") return path ? `Open ${path}` : "BrowserOpen";
  if (name === "BrowserListTabs") return "BrowserListTabs";
  if (name === "BrowserExtractContent") return path ? `Extract ${path}` : "BrowserExtractContent";
  if (name === "BrowserReadContentChunk") return "BrowserReadContentChunk";
  if (name === "BrowserGetHtml") return path ? `HTML ${path}` : "BrowserGetHtml";
  if (name === "LSP") return "LSP";
  if (isTodoToolName(name)) return name;
  if (name.startsWith("Task")) return name;
  return name;
}

export function normalizeGeneratedImageUrls(images: GeneratedImage[]) {
  const baseUrl = useAppStore.getState().baseUrl.replace(/\/+$/, "");
  return images.map((image) => {
    if (!image.url || /^https?:\/\//i.test(image.url) || image.url.startsWith("data:") || image.url.startsWith("blob:")) {
      return image;
    }
    const url = image.url.startsWith("/") ? `${baseUrl}${image.url}` : `${baseUrl}/${image.url}`;
    return { ...image, url };
  });
}
