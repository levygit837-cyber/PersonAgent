import type { ChatMessageUi, StreamChunk } from "../../../types/chat";
import { createThinkingTagState, splitThinkingTags } from "../../../lib/reasoning";
import { thinkingStates, numberValue } from "../internal";
import { isRecord } from "./utils";

export function normalizeStreamChunk(agentId: string, chunk: StreamChunk): StreamChunk {
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

export function applyPromptContextChunk(
  chunk: StreamChunk,
  agentId: string,
  set: import("./utils").SetFn,
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

export function attachContextMetadata(message: ChatMessageUi, chunk: StreamChunk): ChatMessageUi {
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

export { withVisibleTerminalNotice };
