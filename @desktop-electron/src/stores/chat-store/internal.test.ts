import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      selectedWorkspace: "/default/workspace",
      provider: "llama",
      selectedModelId: "default-model",
      reasoningPreset: "medium",
      teamMode: false,
      setProvider: vi.fn(),
      setSelectedModelId: vi.fn(),
      setReasoningPreset: vi.fn(),
      setSection: vi.fn(),
    })),
  },
}));

import {
  thinkingStates,
  textFlushBuffers,
  STREAM_TEXT_FLUSH_MS,
  MAX_TEAM_AGENT_LOGS,
  bumpTeamAgentLogSequence,
  liveTokenTotals,
  resetLiveTokenTotals,
  worktreeSlug,
  parseLocalSlashCommand,
  normalizeProvider,
  inferProviderForModel,
  inferConversationStatus,
  previousUserMessageIndex,
  contextAttachmentsFromMessage,
  isContextAttachment,
  estimateTextTokens,
  estimateConversationContextTokens,
  isTodoToolBlock,
  isBrowserToolBlock,
  browserToolBlocksFromMessages,
  upsertBrowserToolBlock,
  numberValue,
  objectValue,
  estimateTokens,
  normalizeUsageTokens,
  commandHelpText,
  permissionsCommandText,
  conversationForkMessages,
  findAgentMessageIdForTool,
  latestContextWindowEstimate,
  isTodoToolName,
} from "./internal";
import type { ChatMessageUi } from "../../types/chat";
import type { PersistedMessage } from "../../types/chat";

function makeMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
  return {
    id: "msg-1",
    role: "agent",
    label: "PersonAgent",
    content: "",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Module-level constants
// ---------------------------------------------------------------------------

describe("module constants", () => {
  it("STREAM_TEXT_FLUSH_MS is 150", () => {
    expect(STREAM_TEXT_FLUSH_MS).toBe(150);
  });

  it("MAX_TEAM_AGENT_LOGS is 80", () => {
    expect(MAX_TEAM_AGENT_LOGS).toBe(80);
  });

  it("thinkingStates is a Map", () => {
    expect(thinkingStates).toBeInstanceOf(Map);
  });

  it("textFlushBuffers is a Map", () => {
    expect(textFlushBuffers).toBeInstanceOf(Map);
  });
});

// ---------------------------------------------------------------------------
// bumpTeamAgentLogSequence
// ---------------------------------------------------------------------------

describe("bumpTeamAgentLogSequence", () => {
  it("returns incrementing values", () => {
    const a = bumpTeamAgentLogSequence();
    const b = bumpTeamAgentLogSequence();
    expect(b).toBe(a + 1);
  });
});

// ---------------------------------------------------------------------------
// liveTokenTotals / resetLiveTokenTotals
// ---------------------------------------------------------------------------

describe("resetLiveTokenTotals", () => {
  it("resets all counters to 0", () => {
    liveTokenTotals.exactAgent = 100;
    liveTokenTotals.estimatedThinking = 50;
    resetLiveTokenTotals();
    expect(liveTokenTotals.exactAgent).toBe(0);
    expect(liveTokenTotals.exactThinking).toBe(0);
    expect(liveTokenTotals.estimatedAgent).toBe(0);
    expect(liveTokenTotals.estimatedThinking).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// worktreeSlug
// ---------------------------------------------------------------------------

describe("worktreeSlug", () => {
  it("generates slug from conversationId and messageId", () => {
    expect(worktreeSlug("conv-123", "msg-456")).toBe("conv-123-msg-456");
  });

  it("uses 'new' when conversationId is undefined", () => {
    expect(worktreeSlug(undefined, "msg-456")).toBe("new-msg-456");
  });

  it("replaces non-alphanumeric chars with hyphens", () => {
    expect(worktreeSlug("conv@#$123", "msg!!!456")).toBe("conv-123-msg-456");
  });

  it("truncates at 48 chars", () => {
    const long = "a".repeat(60);
    expect(worktreeSlug(long, "end").length).toBeLessThanOrEqual(48);
  });

  it("uses 'new' prefix for empty conversationId", () => {
    expect(worktreeSlug("", "")).toBe("new");
  });
});

// ---------------------------------------------------------------------------
// parseLocalSlashCommand
// ---------------------------------------------------------------------------

describe("parseLocalSlashCommand", () => {
  it("parses simple command", () => {
    expect(parseLocalSlashCommand("/help")).toEqual({ name: "help", args: [] });
  });

  it("parses command with args", () => {
    expect(parseLocalSlashCommand("/model llama big-model")).toEqual({
      name: "model",
      args: ["llama", "big-model"],
    });
  });

  it("returns null for non-command", () => {
    expect(parseLocalSlashCommand("hello")).toBeNull();
  });

  it("returns null for lone slash", () => {
    expect(parseLocalSlashCommand("/")).toBeNull();
  });

  it("lowercases command name", () => {
    expect(parseLocalSlashCommand("/HELP")?.name).toBe("help");
  });
});

// ---------------------------------------------------------------------------
// normalizeProvider / inferProviderForModel
// ---------------------------------------------------------------------------

describe("normalizeProvider", () => {
  it("returns matching provider", () => {
    expect(normalizeProvider("llama")).toBe("llama");
  });

  it("returns undefined for unknown", () => {
    expect(normalizeProvider("unknown")).toBeUndefined();
  });
});

describe("inferProviderForModel", () => {
  it("infers llama for local-model", () => {
    expect(inferProviderForModel("local-model")).toBe("llama");
  });

  it("infers vertex for gemini models", () => {
    expect(inferProviderForModel("gemini-pro")).toBe("vertex");
  });

  it("infers deepseek for deepseek-v4-xxx", () => {
    expect(inferProviderForModel("deepseek-v4-chat")).toBe("deepseek");
  });

  it("infers zenmux for deepseek/deepseek-v4-xxx", () => {
    expect(inferProviderForModel("deepseek/deepseek-v4-chat")).toBe("zenmux");
  });

  it("infers codex for gpt- models", () => {
    expect(inferProviderForModel("gpt-4")).toBe("codex");
  });

  it("returns undefined for unknown", () => {
    expect(inferProviderForModel("random-model")).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// inferConversationStatus
// ---------------------------------------------------------------------------

describe("inferConversationStatus", () => {
  it("returns idle for empty messages", () => {
    expect(inferConversationStatus([])).toBe("idle");
  });

  it("returns error when metadata has is_error", () => {
    const msgs: PersistedMessage[] = [
      { role: "assistant", content: "", metadata: { is_error: true } } as unknown as PersistedMessage,
    ];
    expect(inferConversationStatus(msgs)).toBe("error");
  });

  it("returns idle for normal messages", () => {
    const msgs: PersistedMessage[] = [
      { role: "user", content: "hello" } as unknown as PersistedMessage,
    ];
    expect(inferConversationStatus(msgs)).toBe("idle");
  });
});

// ---------------------------------------------------------------------------
// previousUserMessageIndex
// ---------------------------------------------------------------------------

describe("previousUserMessageIndex", () => {
  it("finds previous user message", () => {
    const msgs = [
      makeMessage({ id: "1", role: "user" }),
      makeMessage({ id: "2", role: "agent" }),
      makeMessage({ id: "3", role: "user" }),
    ];
    expect(previousUserMessageIndex(msgs as ChatMessageUi[], 3)).toBe(2);
    expect(previousUserMessageIndex(msgs as ChatMessageUi[], 2)).toBe(0);
  });

  it("returns -1 when none found", () => {
    const msgs = [makeMessage({ id: "1", role: "agent" })];
    expect(previousUserMessageIndex(msgs as ChatMessageUi[], 1)).toBe(-1);
  });
});

// ---------------------------------------------------------------------------
// contextAttachmentsFromMessage / isContextAttachment
// ---------------------------------------------------------------------------

describe("contextAttachmentsFromMessage", () => {
  it("extracts attachments from metadata", () => {
    const msg = makeMessage({
      metadata: { context_attachments: [{ type: "file", path: "/a.ts" }] },
    });
    expect(contextAttachmentsFromMessage(msg)).toHaveLength(1);
  });

  it("returns empty array when no metadata", () => {
    expect(contextAttachmentsFromMessage(makeMessage())).toEqual([]);
  });
});

describe("isContextAttachment", () => {
  it("returns true for objects with type", () => {
    expect(isContextAttachment({ type: "file" })).toBe(true);
  });

  it("returns false for primitives", () => {
    expect(isContextAttachment("string")).toBe(false);
    expect(isContextAttachment(null)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Token estimation
// ---------------------------------------------------------------------------

describe("estimateTextTokens", () => {
  it("returns 0 for empty string", () => {
    expect(estimateTextTokens("")).toBe(0);
  });

  it("estimates ~1 token per 4 chars", () => {
    expect(estimateTextTokens("abcdefgh")).toBe(2);
  });

  it("returns 0 for non-string", () => {
    expect(estimateTextTokens(42)).toBe(0);
  });
});

describe("estimateTokens", () => {
  it("returns 0 for empty string", () => {
    expect(estimateTokens("")).toBe(0);
  });

  it("estimates from string length", () => {
    expect(estimateTokens("hello world")).toBeGreaterThan(0);
  });
});

describe("estimateConversationContextTokens", () => {
  it("sums tokens across messages", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({ content: "short message" }),
      makeMessage({ content: "another message" }),
    ];
    const tokens = estimateConversationContextTokens(msgs);
    expect(tokens).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Tool block helpers
// ---------------------------------------------------------------------------

describe("isTodoToolBlock", () => {
  it("matches todo block", () => {
    expect(isTodoToolBlock({ name: "TodoCreate" })).toBe(true);
  });

  it("rejects non-todo block", () => {
    expect(isTodoToolBlock({ name: "BrowserClick" })).toBe(false);
  });
});

describe("isBrowserToolBlock", () => {
  it("matches browser block", () => {
    expect(isBrowserToolBlock({ name: "BrowserClick" })).toBe(true);
  });

  it("rejects non-browser block", () => {
    expect(isBrowserToolBlock({ name: "TodoCreate" })).toBe(false);
  });
});

describe("browserToolBlocksFromMessages", () => {
  it("collects browser blocks from agent messages", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({
        role: "agent",
        toolBlocks: [
          { id: "b1", name: "BrowserClick", content: "", path: "", status: "completed", data: {} } as any,
          { id: "b2", name: "TodoCreate", content: "", path: "", status: "completed", data: {} } as any,
        ],
      }),
    ];
    expect(browserToolBlocksFromMessages(msgs)).toHaveLength(1);
  });
});

describe("upsertBrowserToolBlock", () => {
  it("appends new block", () => {
    const block = { id: "b1", name: "BrowserClick" } as any;
    expect(upsertBrowserToolBlock([], block)).toHaveLength(1);
  });

  it("updates existing block", () => {
    const old = { id: "b1", name: "BrowserClick", status: "running" } as any;
    const updated = { id: "b1", name: "BrowserClick", status: "completed" } as any;
    const result = upsertBrowserToolBlock([old], updated);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe("completed");
  });
});

// ---------------------------------------------------------------------------
// numberValue / objectValue
// ---------------------------------------------------------------------------

describe("numberValue", () => {
  it("returns number as-is", () => {
    expect(numberValue(42)).toBe(42);
  });

  it("parses string numbers", () => {
    expect(numberValue("42")).toBe(42);
  });

  it("returns undefined for non-numbers", () => {
    expect(numberValue("abc")).toBeUndefined();
    expect(numberValue(null)).toBeUndefined();
  });
});

describe("objectValue", () => {
  it("returns object as-is", () => {
    expect(objectValue({ a: 1 })).toEqual({ a: 1 });
  });

  it("returns undefined for arrays", () => {
    expect(objectValue([1, 2])).toBeUndefined();
  });

  it("returns undefined for null", () => {
    expect(objectValue(null)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// normalizeUsageTokens
// ---------------------------------------------------------------------------

describe("normalizeUsageTokens", () => {
  it("returns empty for undefined", () => {
    expect(normalizeUsageTokens(undefined)).toEqual({});
  });

  it("extracts agent and thinking tokens", () => {
    const result = normalizeUsageTokens({
      completion_tokens: 100,
      reasoning_tokens: 20,
    });
    expect(result.agent).toBe(80);
    expect(result.thinking).toBe(20);
  });
});

// ---------------------------------------------------------------------------
// commandHelpText / permissionsCommandText
// ---------------------------------------------------------------------------

describe("commandHelpText", () => {
  it("contains local commands section", () => {
    expect(commandHelpText()).toContain("Local commands:");
  });

  it("lists /clear command", () => {
    expect(commandHelpText()).toContain("/clear");
  });
});

describe("permissionsCommandText", () => {
  it("describes tool permissions", () => {
    expect(permissionsCommandText()).toContain("Tool permissions");
  });
});

// ---------------------------------------------------------------------------
// conversationForkMessages
// ---------------------------------------------------------------------------

describe("conversationForkMessages", () => {
  it("converts user messages", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({ role: "user", content: "hello" }),
    ];
    const result = conversationForkMessages(msgs);
    expect(result).toHaveLength(1);
    expect(result[0].role).toBe("user");
    expect(result[0].content).toBe("hello");
  });

  it("converts tool messages", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({
        role: "tool" as any,
        content: "result",
        toolBlocks: [{ id: "tc1", name: "Read", content: "file content", status: "completed", path: "", data: {} } as any],
      }),
    ];
    const result = conversationForkMessages(msgs);
    expect(result).toHaveLength(1);
    expect(result[0].role).toBe("tool");
  });

  it("skips empty assistant messages", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({ role: "agent", content: "", reasoning: "" }),
    ];
    expect(conversationForkMessages(msgs)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// findAgentMessageIdForTool
// ---------------------------------------------------------------------------

describe("findAgentMessageIdForTool", () => {
  it("finds agent message containing tool call", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({
        id: "agent-1",
        role: "agent",
        toolBlocks: [{ id: "tc1", name: "Read" } as any],
      }),
    ];
    expect(findAgentMessageIdForTool(msgs, "tc1")).toBe("agent-1");
  });

  it("returns undefined when not found", () => {
    expect(findAgentMessageIdForTool([], "tc1")).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// latestContextWindowEstimate
// ---------------------------------------------------------------------------

describe("latestContextWindowEstimate", () => {
  it("returns latest context_window_tokens", () => {
    const msgs: ChatMessageUi[] = [
      makeMessage({ metadata: { context_window_tokens: 1000 } }),
      makeMessage({ metadata: { context_window_tokens: 2000 } }),
    ];
    expect(latestContextWindowEstimate(msgs)).toBe(2000);
  });

  it("returns undefined when no estimates", () => {
    expect(latestContextWindowEstimate([])).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// isTodoToolName
// ---------------------------------------------------------------------------

describe("isTodoToolName", () => {
  it("matches todo tool names", () => {
    expect(isTodoToolName("TodoCreate")).toBe(true);
    expect(isTodoToolName("todo_update")).toBe(true);
  });

  it("rejects non-todo names", () => {
    expect(isTodoToolName("BrowserClick")).toBe(false);
    expect(isTodoToolName(undefined)).toBe(false);
  });
});
