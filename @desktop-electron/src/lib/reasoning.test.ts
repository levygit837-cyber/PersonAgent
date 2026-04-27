import { describe, expect, it } from "vitest";
import { createThinkingTagState, splitCompleteThinkingText, splitThinkingTags } from "./reasoning";

describe("reasoning parser", () => {
  it("splits complete think tags from visible content", () => {
    expect(splitCompleteThinkingText("<think>internal</think>Final answer")).toEqual({
      content: "Final answer",
      reasoning: "internal",
    });
  });

  it("keeps split tag prefixes pending across stream chunks", () => {
    const state = createThinkingTagState();

    expect(splitThinkingTags("<thi", state)).toEqual({ content: "", reasoning: "" });
    expect(splitThinkingTags("nk>hidden</think>visible", state, true)).toEqual({
      content: "visible",
      reasoning: "hidden",
    });
  });

  it("supports additional reasoning tag names used by hosted models", () => {
    expect(splitCompleteThinkingText("<thinking>internal</thinking>Final answer")).toEqual({
      content: "Final answer",
      reasoning: "internal",
    });
  });

  it("handles Qwen-style text when the opening think tag was injected by the prompt", () => {
    expect(splitCompleteThinkingText("Let me inspect this.</think>\n\nFinal answer")).toEqual({
      content: "\n\nFinal answer",
      reasoning: "Let me inspect this.",
    });
  });
});
