/**
 * Unit tests for use-session-panel-state.ts (Slice 2).
 *
 * Tests the pure `mergeUsage` function directly. The hook itself is
 * integration-tested via the existing `session-panel.test.tsx` suite.
 */

import { describe, expect, it } from "vitest";
import type { SessionUsage } from "../../../types/chat";
import { emptySessionUsage } from "../../../types/chat";
import { mergeUsage } from "./use-session-panel-state";

function makeUsage(overrides: Partial<Record<keyof SessionUsage, { value: number; estimated: boolean }>>): SessionUsage {
  return { ...emptySessionUsage(), ...overrides };
}

describe("mergeUsage", () => {
  it("returns live values when snapshot is undefined", () => {
    const live = makeUsage({
      tool_calls: { value: 5, estimated: false },
      agent_output_tokens: { value: 100, estimated: false },
    });
    const result = mergeUsage(undefined, live);
    expect(result.tool_calls.value).toBe(5);
    expect(result.agent_output_tokens.value).toBe(100);
  });

  it("adds snapshot and live for additive metrics", () => {
    const snapshot = makeUsage({
      tool_calls: { value: 3, estimated: false },
      agent_output_tokens: { value: 200, estimated: false },
    });
    const live = makeUsage({
      tool_calls: { value: 2, estimated: false },
      agent_output_tokens: { value: 50, estimated: true },
    });
    const result = mergeUsage(snapshot, live);
    expect(result.tool_calls.value).toBe(5);
    expect(result.agent_output_tokens.value).toBe(250);
    expect(result.agent_output_tokens.estimated).toBe(true);
  });

  it("takes max for context_tokens", () => {
    const snapshot = makeUsage({
      context_tokens: { value: 1000, estimated: false },
    });
    const live = makeUsage({
      context_tokens: { value: 800, estimated: true },
    });
    const result = mergeUsage(snapshot, live);
    expect(result.context_tokens.value).toBe(1000);
    expect(result.context_tokens.estimated).toBe(true);
  });

  it("takes live max when live context_tokens is higher", () => {
    const snapshot = makeUsage({
      context_tokens: { value: 500, estimated: false },
    });
    const live = makeUsage({
      context_tokens: { value: 1200, estimated: false },
    });
    const result = mergeUsage(snapshot, live);
    expect(result.context_tokens.value).toBe(1200);
  });

  it("returns zero-filled usage when both are empty", () => {
    const result = mergeUsage(emptySessionUsage(), emptySessionUsage());
    expect(result.tool_calls.value).toBe(0);
    expect(result.context_tokens.value).toBe(0);
    expect(result.plans_created.value).toBe(0);
  });

  it("propagates estimated flag from either side", () => {
    const snapshot = makeUsage({
      plans_created: { value: 1, estimated: true },
    });
    const live = makeUsage({
      plans_created: { value: 2, estimated: false },
    });
    const result = mergeUsage(snapshot, live);
    expect(result.plans_created.value).toBe(3);
    expect(result.plans_created.estimated).toBe(true);
  });

  it("handles all SessionUsage keys correctly", () => {
    const snapshot = makeUsage({
      skills_used_count: { value: 3, estimated: false },
      mcp_calls_count: { value: 1, estimated: false },
      todos_created: { value: 2, estimated: false },
      subagents_used: { value: 1, estimated: false },
    });
    const live = makeUsage({
      skills_used_count: { value: 1, estimated: false },
      mcp_calls_count: { value: 2, estimated: false },
      todos_created: { value: 0, estimated: false },
      subagents_used: { value: 0, estimated: false },
    });
    const result = mergeUsage(snapshot, live);
    expect(result.skills_used_count.value).toBe(4);
    expect(result.mcp_calls_count.value).toBe(3);
    expect(result.todos_created.value).toBe(2);
    expect(result.subagents_used.value).toBe(1);
  });

  it("treats undefined snapshot metric values as zero", () => {
    const result = mergeUsage(undefined, emptySessionUsage());
    for (const key of Object.keys(result) as Array<keyof SessionUsage>) {
      expect(result[key].value).toBe(0);
      expect(result[key].estimated).toBe(false);
    }
  });
});
