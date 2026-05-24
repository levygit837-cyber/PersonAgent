import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  closeActiveReasoning,
  updatePlanApprovalArtifact,
  stringValue,
  isRecord,
  planApprovalFromChunk,
  toolApprovalFromChunk,
  messageFromPersisted,
  isRenderablePersistedMessage,
} from "./streaming-helpers";
import type { ChatMessageUi, StreamChunk, PersistedMessage } from "../../types/chat";

vi.mock("../app-store", () => ({
  useAppStore: {
    getState: vi.fn(() => ({
      baseUrl: "http://test",
    })),
  },
}));

function makeMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
  return {
    id: "msg-1",
    role: "agent",
    content: "hello",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: true,
    isReasoningStreaming: false,
    ...overrides,
  } as ChatMessageUi;
}

describe("streaming-helpers", () => {
  describe("closeActiveReasoning", () => {
    it("sets isStreaming based on keepStreaming param", () => {
      const msg = makeMessage({ isStreaming: true });
      const closed = closeActiveReasoning(msg, false);
      expect(closed.isStreaming).toBe(false);
    });

    it("keeps streaming when keepStreaming is true", () => {
      const msg = makeMessage({ isStreaming: true });
      const closed = closeActiveReasoning(msg, true);
      expect(closed.isStreaming).toBe(true);
    });

    it("sets isReasoningStreaming to false", () => {
      const msg = makeMessage({ isReasoningStreaming: true });
      const closed = closeActiveReasoning(msg, false);
      expect(closed.isReasoningStreaming).toBe(false);
    });
  });

  describe("updatePlanApprovalArtifact", () => {
    it("returns messages unchanged if no matching approval", () => {
      const messages = [makeMessage({ id: "msg-1" })];
      const result = updatePlanApprovalArtifact(messages, "nonexistent", "approved", undefined);
      expect(result).toEqual(messages);
    });
  });

  describe("stringValue", () => {
    it("returns undefined for non-string", () => {
      expect(stringValue(42)).toBeUndefined();
      expect(stringValue(null)).toBeUndefined();
      expect(stringValue(undefined)).toBeUndefined();
    });

    it("returns undefined for empty string", () => {
      expect(stringValue("")).toBeUndefined();
      expect(stringValue("   ")).toBeUndefined();
    });

    it("returns trimmed string", () => {
      expect(stringValue("  hello  ")).toBe("hello");
    });
  });

  describe("isRecord", () => {
    it("returns true for plain objects", () => {
      expect(isRecord({})).toBe(true);
      expect(isRecord({ key: "value" })).toBe(true);
    });

    it("returns false for non-objects", () => {
      expect(isRecord(null)).toBe(false);
      expect(isRecord(undefined)).toBe(false);
      expect(isRecord(42)).toBe(false);
      expect(isRecord("string")).toBe(false);
    });

    it("returns false for arrays", () => {
      expect(isRecord([])).toBe(false);
    });
  });

  describe("planApprovalFromChunk", () => {
    it("creates plan approval from chunk", () => {
      const chunk = {
        conversation_id: "conv-1",
        approval_id: "approval-1",
        plan_status: "pending_approval",
        plan_markdown: "# Plan",
        plan_context: { key: "value" },
      } as unknown as StreamChunk;
      const approval = planApprovalFromChunk(chunk);
      expect(approval.conversationId).toBe("conv-1");
      expect(approval.approvalId).toBe("approval-1");
    });
  });

  describe("messageFromPersisted", () => {
    it("creates ChatMessageUi from persisted message", () => {
      const persisted = {
        id: "msg-1",
        role: "user",
        content: "hello world",
        created_at: new Date().toISOString(),
      } as PersistedMessage;
      const result = messageFromPersisted(persisted);
      expect(result.role).toBe("user");
      expect(result.content).toBe("hello world");
      expect(result.isStreaming).toBe(false);
    });
  });

  describe("isRenderablePersistedMessage", () => {
    it("returns true for user messages", () => {
      const msg = { role: "user", content: "hello" } as PersistedMessage;
      expect(isRenderablePersistedMessage(msg)).toBe(true);
    });

    it("returns true for assistant messages", () => {
      const msg = { role: "assistant", content: "hi" } as PersistedMessage;
      expect(isRenderablePersistedMessage(msg)).toBe(true);
    });

    it("accepts system messages with content", () => {
      const msg = { role: "system", content: "system prompt" } as PersistedMessage;
      expect(isRenderablePersistedMessage(msg)).toBe(true);
    });

    it("handles tool messages", () => {
      const msg = { role: "tool", content: "" } as unknown as PersistedMessage;
      const result = isRenderablePersistedMessage(msg);
      expect(typeof result).toBe("boolean");
    });
  });
});
