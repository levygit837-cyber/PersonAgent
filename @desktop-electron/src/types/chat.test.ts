import { describe, expect, it } from "vitest";
import { buildChatRequest, buildTeamRunStart, isToolEvent, reasoningTokenBudget } from "./chat";

describe("chat request contracts", () => {
  it("serializes reasoning presets and workspace tool context", () => {
    const request = buildChatRequest({
      message: "Read the repo",
      provider: "llama",
      model: "local-model",
      reasoningPreset: "xhigh",
      workspaceRoot: "/tmp/personagent",
    });

    expect(request.reasoning_level).toBe("xhigh");
    expect(request.prompt_mode).toBe("auto");
    expect(request.reasoning_budget_tokens).toBe(16382);
    expect(request.workspace_root).toBe("/tmp/personagent");
    expect(request.tool_context?.allowed_roots).toEqual(["/tmp/personagent"]);
  });

  it("keeps the explicit reasoning budget contract", () => {
    expect(reasoningTokenBudget("low")).toBe(2048);
    expect(reasoningTokenBudget("medium")).toBe(4082);
    expect(reasoningTokenBudget("high")).toBe(8192);
    expect(reasoningTokenBudget("xhigh")).toBe(16382);
    expect(reasoningTokenBudget("max")).toBe(32768);
  });

  it("maps Codex max reasoning to xhigh for the provider contract", () => {
    const request = buildChatRequest({
      message: "Use Codex",
      provider: "codex",
      model: "gpt-5.5",
      reasoningPreset: "max",
    });

    expect(request.reasoning_level).toBe("xhigh");
    expect(request.reasoning_budget_tokens).toBe(16382);
  });

  it("serializes Team Mode runs over the chat request contract", () => {
    const request = buildTeamRunStart({
      conversationId: "conversation-1",
      message: "Debate this",
      provider: "llama",
      model: "local-model",
      reasoningPreset: "low",
      workspaceRoot: "/tmp/personagent",
    });

    expect(request.type).toBe("team.run.start");
    expect(request.team_id).toBe("default-4");
    expect(request.conversation_id).toBe("conversation-1");
    expect(request.tool_context?.cwd).toBe("/tmp/personagent");
  });

  it("classifies tool stream events", () => {
    expect(isToolEvent({ event: "tool_result" })).toBe(true);
    expect(isToolEvent({ event: "conversation" })).toBe(false);
  });
});
