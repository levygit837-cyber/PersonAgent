import type { StreamChunk } from "../../../types/chat";
import {
  isTodoToolName,
  incrementLiveUsage,
  normalizeUsageTokens,
  estimateTokens,
  liveTokenTotals,
} from "../internal";
import type { SetFn } from "./utils";

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
