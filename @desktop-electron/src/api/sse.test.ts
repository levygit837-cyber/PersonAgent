import { describe, expect, it } from "vitest";
import { PersonAgentApiError, extractApiErrorEnvelope } from "./errors";
import { parseSsePayloads } from "./sse";

describe("parseSsePayloads", () => {
  it("parses json payloads and preserves incomplete buffers", () => {
    const result = parseSsePayloads('data: {"content":"hello"}\n\ndata: {"content"');
    expect(result.payloads).toEqual([{ content: "hello" }]);
    expect(result.rest).toBe('data: {"content"');
  });

  it("parses done control chunks", () => {
    const result = parseSsePayloads("data: [DONE]\n\n");
    expect(result.payloads).toEqual([{ __done: true }]);
  });

  it("extracts structured API error envelopes with legacy detail fallback", () => {
    const envelope = extractApiErrorEnvelope(
      {
        detail: "Conversation not found",
        error: {
          code: "conversation.not_found",
          category: "conversation",
          message: "Conversation not found",
          status: 404,
          retryable: false,
        },
      },
      404,
      "Not Found",
    );
    const error = new PersonAgentApiError(envelope);

    expect(error.message).toBe("Conversation not found");
    expect(error.envelope.code).toBe("conversation.not_found");
    expect(error.retryable).toBe(false);
  });
});
