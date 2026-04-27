import { describe, expect, it } from "vitest";
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
});
