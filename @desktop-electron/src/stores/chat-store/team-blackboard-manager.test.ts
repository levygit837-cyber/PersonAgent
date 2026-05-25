import { describe, it, expect } from "vitest";
import {
  upsertTeamTool,
  toolTraceFromEvent,
  updateBlackboardFromSnapshot,
  updateBlackboardFromContract,
  updateBlackboardFromCoherency,
  updateBlackboardFromCoherencyObject,
  blackboardClaimFromEvent,
  claimsFromDelta,
  claimsFromValue,
  mergeClaims,
  coverageFromValue,
  upsertTeamVote,
  blockerTextFromEvent,
  decisionTextFromEvent,
  blockerListFromValue,
  textListFromValue,
  mergeTextItems,
} from "./team-blackboard-manager";
import type {
  TeamRunEvent,
  TeamBlackboardTraceUi,
  TeamToolTraceUi,
} from "../../types/chat";

function makeEvent(overrides: Partial<TeamRunEvent> = {}): TeamRunEvent {
  return {
    event: "blackboard_event",
    run_id: "run-1",
    round: 1,
    created_at: new Date().toISOString(),
    ...overrides,
  } as TeamRunEvent;
}

function makeToolTrace(overrides: Partial<TeamToolTraceUi> = {}): TeamToolTraceUi {
  return {
    id: "tool-1",
    phase: "tools",
    title: "Search",
    status: "completed",
    calls: [],
    results: [],
    proposals: [],
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

function makeBlackboard(
  overrides: Partial<TeamBlackboardTraceUi> = {},
): TeamBlackboardTraceUi {
  return {
    status: "running",
    actualPhase: "starting",
    nextAction: undefined,
    claims: [],
    evidence: [],
    decisions: [],
    blockers: [],
    coverage: [],
    tools: [],
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("team-blackboard-manager", () => {
  describe("upsertTeamTool", () => {
    it("adds new tool when not found", () => {
      const tool = makeToolTrace({ id: "t1" });
      const next = upsertTeamTool([], tool);
      expect(next).toHaveLength(1);
      expect(next[0].id).toBe("t1");
    });

    it("updates existing tool by id", () => {
      const existing = makeToolTrace({ id: "t1", title: "Old" });
      const update = makeToolTrace({ id: "t1", title: "New", status: "running" });
      const next = upsertTeamTool([existing], update);
      expect(next).toHaveLength(1);
      expect(next[0].title).toBe("New");
      expect(next[0].status).toBe("running");
    });

    it("preserves existing calls when update has empty calls", () => {
      const existing = makeToolTrace({ id: "t1", calls: [{ name: "grep", args: {} }] });
      const update = makeToolTrace({ id: "t1", calls: [] });
      const next = upsertTeamTool([existing], update);
      expect(next[0].calls).toHaveLength(1);
    });

    it("replaces calls when update has non-empty calls", () => {
      const existing = makeToolTrace({ id: "t1", calls: [{ name: "old", args: {} }] });
      const update = makeToolTrace({ id: "t1", calls: [{ name: "new", args: {} }] });
      const next = upsertTeamTool([existing], update);
      expect(next[0].calls).toHaveLength(1);
    });

    it("preserves existing results when update has empty results", () => {
      const existing = makeToolTrace({ id: "t1", results: [{ content: "x" }] });
      const update = makeToolTrace({ id: "t1", results: [] });
      const next = upsertTeamTool([existing], update);
      expect(next[0].results).toHaveLength(1);
    });

    it("preserves existing proposals when update has empty proposals", () => {
      const existing = makeToolTrace({ id: "t1", proposals: [{ agent_id: "a1", action: "approve" }] });
      const update = makeToolTrace({ id: "t1", proposals: [] });
      const next = upsertTeamTool([existing], update);
      expect(next[0].proposals).toHaveLength(1);
    });
  });

  describe("toolTraceFromEvent", () => {
    it('returns "blocked" status when proposals exist', () => {
      const trace = toolTraceFromEvent(makeEvent({ proposals: [{ id: 1 }], tool_phase: "search" }));
      expect(trace.status).toBe("blocked");
      expect(trace.summary).toContain("proposal waiting for coordination");
    });

    it('returns "completed" status when only results exist', () => {
      const trace = toolTraceFromEvent(makeEvent({ results: [{ id: 1 }], tool_phase: "search" }));
      expect(trace.status).toBe("completed");
      expect(trace.summary).toContain("result published");
    });

    it('returns "running" status when only calls exist', () => {
      const trace = toolTraceFromEvent(makeEvent({ calls: [{ name: "grep", args: {} }], tool_phase: "search" }));
      expect(trace.status).toBe("running");
    });

    it('returns "completed" when no calls/results/proposals', () => {
      const trace = toolTraceFromEvent(makeEvent({ tool_phase: "search" }));
      expect(trace.status).toBe("completed");
    });

    it("falls back to event.phase when tool_phase is missing", () => {
      const trace = toolTraceFromEvent(makeEvent({ phase: "debate" }));
      expect(trace.phase).toBe("debate");
    });

    it('defaults phase to "tools"', () => {
      const trace = toolTraceFromEvent(makeEvent({ phase: undefined, tool_phase: undefined }));
      expect(trace.phase).toBe("tools");
    });

    it("pluralizes proposal summary correctly", () => {
      const trace = toolTraceFromEvent(
        makeEvent({
          proposals: [{ id: 1 }, { id: 2 }],
          tool_phase: "search",
        }),
      );
      expect(trace.summary).toBe("2 proposals waiting for coordination");
    });
  });

  describe("updateBlackboardFromContract", () => {
    it("merges objective as a claim", () => {
      const bb = makeBlackboard();
      const event = makeEvent({
        event: "execution_contract",
        contract: { objective: "Test objective" },
        agent_name: "Coordinator",
      });
      const next = updateBlackboardFromContract(bb, event);
      expect(next.claims).toHaveLength(1);
      expect(next.claims[0].type).toBe("objective");
      expect(next.claims[0].text).toBe("Test objective");
    });

    it('sets nextAction to "Independent round"', () => {
      const bb = makeBlackboard();
      const next = updateBlackboardFromContract(bb, makeEvent({ event: "execution_contract" }));
      expect(next.nextAction).toBe("Independent round");
    });

    it("updates coverage from contract", () => {
      const bb = makeBlackboard();
      const event = makeEvent({
        event: "execution_contract",
        contract: {
          coverage_matrix: [{ id: "cc1", status: "done" }],
        },
      });
      const next = updateBlackboardFromContract(bb, event);
      expect(next.coverage).toHaveLength(1);
    });
  });

  describe("updateBlackboardFromCoherencyObject", () => {
    it("updates coherencyScore from average", () => {
      const bb = makeBlackboard();
      const next = updateBlackboardFromCoherencyObject(bb, { average: 0.85 });
      expect(next.coherencyScore).toBe(0.85);
    });

    it("updates lowCoherencyCount", () => {
      const bb = makeBlackboard();
      const next = updateBlackboardFromCoherencyObject(bb, { average: 0.5, low_count: 3 });
      expect(next.lowCoherencyCount).toBe(3);
    });

    it("returns blackboard unchanged for non-record input", () => {
      const bb = makeBlackboard({ coherencyScore: 123 });
      const next = updateBlackboardFromCoherencyObject(bb, "not-an-object");
      expect(next.coherencyScore).toBe(123);
    });
  });

  describe("updateBlackboardFromCoherency", () => {
    it("passes coherency_score as average", () => {
      const bb = makeBlackboard();
      const event = makeEvent({ event: "coherency_score", coherency_score: 0.95 });
      const next = updateBlackboardFromCoherency(bb, event);
      expect(next.coherencyScore).toBe(0.95);
    });
  });

  describe("blackboardClaimFromEvent", () => {
    it("extracts claim from payload.summary", () => {
      const claim = blackboardClaimFromEvent(
        makeEvent({
          payload: { summary: "Claim text" },
          event_type: "assertion",
        }),
      );
      expect(claim!.text).toBe("Claim text");
      expect(claim!.type).toBe("assertion");
    });

    it("falls back to payload.decision", () => {
      const claim = blackboardClaimFromEvent(
        makeEvent({ payload: { decision: "Decided" } }),
      );
      expect(claim!.text).toBe("Decided");
    });

    it('falls back to "claim" type when event_type and blocker absent', () => {
      const claim = blackboardClaimFromEvent(
        makeEvent({ payload: { summary: "x" } }),
      );
      expect(claim!.type).toBe("claim");
    });

    it('uses "blocker" type when payload.blocker exists', () => {
      const claim = blackboardClaimFromEvent(
        makeEvent({ payload: { blocker: "Critical issue" } }),
      );
      expect(claim!.type).toBe("blocker");
    });

    it("returns undefined when no text found", () => {
      const claim = blackboardClaimFromEvent(makeEvent({ payload: {} }));
      expect(claim).toBeUndefined();
    });
  });

  describe("claimsFromDelta", () => {
    it("returns empty array for non-record delta", () => {
      expect(claimsFromDelta(undefined)).toEqual([]);
      expect(claimsFromDelta("string")).toEqual([]);
    });

    it("extracts claims from delta.nodes", () => {
      const delta = {
        nodes: [
          { id: "n1", text: "Claim A", type: "claim" },
          { id: "n2", text: "Claim B", type: "evidence" },
        ],
      };
      const claims = claimsFromDelta(delta);
      expect(claims).toHaveLength(2);
      expect(claims[0].text).toBe("Claim A");
    });
  });

  describe("claimsFromValue", () => {
    it("returns empty array for non-array input", () => {
      expect(claimsFromValue(undefined)).toEqual([]);
      expect(claimsFromValue({})).toEqual([]);
    });

    it("filters out entries with empty text", () => {
      const value = [
        { id: "n1", text: "", type: "claim" },
        { id: "n2", text: "Valid", type: "claim" },
      ];
      const claims = claimsFromValue(value);
      expect(claims).toHaveLength(1);
      expect(claims[0].text).toBe("Valid");
    });

    it("maps numeric fields", () => {
      const value = [
        { id: "n1", text: "x", confidence: 0.8, coherency_score: 0.9, novelty_score: 0.5 },
      ];
      const claims = claimsFromValue(value);
      expect(claims[0].confidence).toBe(0.8);
      expect(claims[0].coherencyScore).toBe(0.9);
      expect(claims[0].noveltyScore).toBe(0.5);
    });
  });

  describe("mergeClaims", () => {
    it("returns existing when incoming is empty", () => {
      const existing = [{ id: "c1", type: "claim", text: "x", status: "active" }];
      expect(mergeClaims(existing, [])).toBe(existing);
    });

    it("updates claim by matching id", () => {
      const existing = [{ id: "c1", type: "claim", text: "old", status: "active" }];
      const incoming = [{ id: "c1", text: "new", type: "claim", status: "completed" }];
      const next = mergeClaims(existing, incoming);
      expect(next[0].text).toBe("new");
      expect(next[0].status).toBe("completed");
      expect(next[0].type).toBe("claim");
    });

    it("appends new claim when id not found", () => {
      const existing = [{ id: "c1", type: "claim", text: "x", status: "active" }];
      const incoming = [{ id: "c2", type: "evidence", text: "y", status: "active" }];
      const next = mergeClaims(existing, incoming);
      expect(next).toHaveLength(2);
    });
  });

  describe("coverageFromValue", () => {
    it("returns undefined for non-array input", () => {
      expect(coverageFromValue(undefined)).toBeUndefined();
    });

    it("maps array items to coverage traces", () => {
      const value = [
        { id: "cc1", question: "Q1", status: "done", owner_agent_id: "a1" },
      ];
      const traces = coverageFromValue(value);
      expect(traces![0].title).toBe("Q1");
      expect(traces![0].detail).toBe("done");
      expect(traces![0].ownerAgentId).toBe("a1");
    });
  });

  describe("upsertTeamVote", () => {
    it("adds new vote", () => {
      const event = makeEvent({
        event: "agent_vote",
        run_id: "r1",
        round: 2,
        agent_id: "a1",
        agent_name: "Agent",
        approve: true,
        confidence: 0.9,
      });
      const next = upsertTeamVote([], event);
      expect(next).toHaveLength(1);
      expect(next[0].kind).toBe("vote");
      expect(next[0].status).toBe("approved");
    });

    it("updates existing vote by id", () => {
      const event = makeEvent({
        event: "agent_vote",
        run_id: "r1",
        round: 2,
        agent_id: "a1",
        agent_name: "Agent",
        approve: false,
        blocker: "Issue",
      });
      const existing = upsertTeamVote([], event);
      const updated = upsertTeamVote(existing, {
        ...event,
        approve: true,
        blocker: undefined,
      });
      expect(updated).toHaveLength(1);
      expect(updated[0].status).toBe("approved");
    });
  });

  describe("blockerTextFromEvent", () => {
    it("extracts blocker from payload", () => {
      const result = blockerTextFromEvent(
        makeEvent({ payload: { blocker: "Critical" } }),
      );
      expect(result).toEqual(["Critical"]);
    });

    it("falls back to event.blocker", () => {
      const result = blockerTextFromEvent(makeEvent({ blocker: "Some issue" }));
      expect(result).toEqual(["Some issue"]);
    });

    it("returns empty array when no blocker", () => {
      expect(blockerTextFromEvent(makeEvent())).toEqual([]);
    });
  });

  describe("decisionTextFromEvent", () => {
    it("extracts decision from payload", () => {
      const result = decisionTextFromEvent(
        makeEvent({ payload: { decision: "Approved" } }),
      );
      expect(result).toEqual(["Approved"]);
    });

    it("returns empty array when no decision", () => {
      expect(decisionTextFromEvent(makeEvent())).toEqual([]);
    });
  });

  describe("mergeTextItems", () => {
    it("returns existing when incoming is empty", () => {
      expect(mergeTextItems(["a"], [])).toEqual(["a"]);
    });

    it("deduplicates across existing and incoming", () => {
      expect(mergeTextItems(["a", "b"], ["b", "c"])).toEqual(["a", "b", "c"]);
    });
  });

  describe("blockerListFromValue", () => {
    it("returns empty array for non-array input", () => {
      expect(blockerListFromValue(undefined)).toEqual([]);
    });

    it("extracts strings directly", () => {
      expect(blockerListFromValue(["blocker1"])).toEqual(["blocker1"]);
    });

    it("extracts blocker from payload.blocker in records", () => {
      const value = [{ payload: { blocker: "Critical" } }];
      expect(blockerListFromValue(value)).toEqual(["Critical"]);
    });
  });

  describe("textListFromValue", () => {
    it("returns empty array for non-array input", () => {
      expect(textListFromValue(null)).toEqual([]);
    });

    it("extracts strings directly", () => {
      expect(textListFromValue(["text1"])).toEqual(["text1"]);
    });

    it("extracts text from record items", () => {
      const value = [{ text: "Item A" }, { summary: "Item B" }];
      expect(textListFromValue(value)).toEqual(["Item A", "Item B"]);
    });
  });
});
