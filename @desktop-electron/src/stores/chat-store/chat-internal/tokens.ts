import type { ChatMessageUi, ContextAttachment, SessionUsage } from "../../../types/chat";
import { contextAttachmentsFromMessage } from "../internal";
import { liveTokenTotals } from "../internal";
import type { ChatSet, ChatState, SessionUsageKey } from "../internal";

export function resetLiveTokenTotals() {
  liveTokenTotals.exactAgent = 0;
  liveTokenTotals.exactThinking = 0;
  liveTokenTotals.estimatedAgent = 0;
  liveTokenTotals.estimatedThinking = 0;
}

export function incrementLiveUsage(
  set: ChatSet,
  key: SessionUsageKey,
  value: number,
  estimated = false,
) {
  set((state: ChatState) => ({
    liveSessionUsage: {
      ...state.liveSessionUsage,
      [key]: {
        value: state.liveSessionUsage[key].value + Math.max(0, value),
        estimated: state.liveSessionUsage[key].estimated || estimated,
      },
    },
  }));
}

export function latestContextWindowEstimate(messages: ChatMessageUi[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const value = numberValue(messages[index].metadata?.context_window_tokens);
    if (value !== undefined && value > 0) return value;
  }
  return undefined;
}

export function estimateConversationContextTokens(messages: ChatMessageUi[]) {
  return messages.reduce(
    (total, message) => total + estimateMessageContextTokens(message),
    0,
  );
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
  return (
    explicitText ||
    (charCount ? Math.max(1, Math.ceil(charCount / 4)) : estimateUnknownTokens(attachment))
  );
}

function estimateUnknownTokens(value: unknown) {
  if (value === undefined || value === null) return 0;
  if (typeof value === "string") return estimateTextTokens(value);
  if (typeof value === "number" || typeof value === "boolean")
    return estimateTextTokens(String(value));
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
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
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
    rawAgent !== undefined &&
    thinking !== undefined &&
    usage.completion_tokens !== undefined &&
    usage.candidatesTokenCount === undefined
      ? Math.max(0, rawAgent - thinking)
      : rawAgent;
  return { agent, thinking };
}
