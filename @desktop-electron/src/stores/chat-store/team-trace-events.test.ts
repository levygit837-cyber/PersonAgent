import { describe, it, expect } from "vitest";
import { applyTeamTraceEvent, turnTraceId } from "./team-trace-events";
import type { ChatMessageUi, TeamRunEvent } from "../../types/chat";

function makeEvent(overrides: Partial<TeamRunEvent> = {}): TeamRunEvent {
  return {
    event: "team_run_started",
    run_id: "run-1",
    round: 1,
    created_at: new Date().toISOString(),
    team: {
      id: "team-1", name: "Test Team", agents: [], execution_order: [], max_rounds: null, vote_every_rounds: 1, consensus_threshold: 0.6,
    },
    ...overrides,
  } as TeamRunEvent;
}

function makeMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
  return {
    id: "msg-1",
    role: "agent",
    content: "",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
    ...overrides,
  } as ChatMessageUi;
}

describe("team-trace-events", () => {
  describe("turnTraceId", () => {
    it("builds id from run_id, round, and agent_id", () => {
      expect(
        turnTraceId(
          makeEvent({ run_id: "r1", round: 3, agent_id: "a2" }),
        ),
      ).toBe("r1-round-3-a2");
    });
  });

  describe("applyTeamTraceEvent", () => {
    it("returns message with teamEvents untouched for unhandled event", () => {
      const msg = makeMessage({
        teamEvents: [
          { id: "ev-1", kind: "run", title: "Run", status: "running" },
        ],
      });
      const next = applyTeamTraceEvent(msg, makeEvent({ event: "final_delta" }));
      expect(next.teamEvents).toHaveLength(1);
    });

    it("upserts team_run_started event", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "team_run_started",
          run_id: "r1",
          team: { id: "t1", name: "Test Team", agents: [], execution_order: [], max_rounds: null, vote_every_rounds: 1, consensus_threshold: 0.6 },
        }),
      );
      expect(next.teamEvents).toHaveLength(1);
      expect(next.teamEvents[0].kind).toBe("run");
      expect(next.teamEvents[0].title).toBe("Test Team");
      expect(next.teamEvents[0].status).toBe("running");
    });

    it("upserts round_started event", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "round_started",
          run_id: "r1",
          round: 3,
          phase: "debate",
        }),
      );
      expect(next.teamEvents[0].kind).toBe("round");
      expect(next.teamEvents[0].title).toBe("Round 3");
      expect(next.teamEvents[0].detail).toBe("debate");
    });

    it("upserts debate_started event", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({ event: "debate_started", run_id: "r1", round: 2 }),
      );
      expect(next.teamEvents[0].kind).toBe("debate");
    });

    it("upserts agent_turn_started trace", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "agent_turn_started",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          phase: "writing",
        }),
      );
      expect(next.teamEvents[0].kind).toBe("turn");
      expect(next.teamEvents[0].title).toBe("Writer");
      expect(next.teamEvents[0].status).toBe("running");
    });

    it("appends content on agent_delta with existing trace", () => {
      const msg = makeMessage({
        teamEvents: [
          {
            id: "r1-round-1-a1",
            kind: "turn",
            title: "Writer",
            status: "running",
            content: "Hello",
          },
        ],
      });
      const next = applyTeamTraceEvent(
        msg,
        makeEvent({
          event: "agent_delta",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          content: " world",
        }),
      );
      expect(next.teamEvents[0].content).toBe("Hello world");
    });

    it("returns unchanged on agent_delta with empty content", () => {
      const msg = makeMessage();
      const next = applyTeamTraceEvent(
        msg,
        makeEvent({
          event: "agent_delta",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          content: "",
        }),
      );
      expect(next.teamEvents).toHaveLength(0);
    });

    it("upserts agent_turn_completed with failed status", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "agent_turn_completed",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          status: "failed",
          duration_ms: 1500,
        }),
      );
      expect(next.teamEvents[0].status).toBe("failed");
      expect(next.teamEvents[0].detail).toBe("1500 ms");
    });

    it("preserves existing detail when no duration_ms on completed", () => {
      const msg = makeMessage({
        teamEvents: [
          {
            id: "r1-round-1-a1",
            kind: "turn",
            title: "Writer",
            status: "running",
            content: "",
            detail: "old detail",
          },
        ],
      });
      const next = applyTeamTraceEvent(
        msg,
        makeEvent({
          event: "agent_turn_completed",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
        }),
      );
      expect(next.teamEvents[0].detail).toBe("old detail");
    });

    it("upserts blackboard_event with blocker content", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "blackboard_event",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          phase: "debate",
          sequence: 5,
          payload: { blocker: "Critical issue" },
        }),
      );
      expect(next.teamEvents[0].kind).toBe("blackboard");
      expect(next.teamEvents[0].content).toBe("Critical issue");
    });

    it("upserts blackboard_snapshot with entry count", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "blackboard_snapshot",
          run_id: "r1",
          round: 2,
          snapshot: { entry_count: 42 },
        }),
      );
      expect(next.teamEvents[0].title).toBe("Blackboard snapshot");
      expect(next.teamEvents[0].detail).toBe("42 entries");
    });

    it("upserts execution_contract with objective", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "execution_contract",
          run_id: "r1",
          agent_id: "coord-1",
          agent_name: "Coordinator",
          contract: { objective: "Build X" },
        }),
      );
      expect(next.teamEvents[0].kind).toBe("coordinator");
      expect(next.teamEvents[0].content).toBe("Build X");
    });

    it("upserts claim_graph_delta with duplicates", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "claim_graph_delta",
          run_id: "r1",
          agent_id: "a1",
          agent_name: "Writer",
          delta: { duplicates: [1, 2, 3] },
        }),
      );
      expect(next.teamEvents[0].status).toBe("rejected");
      expect(next.teamEvents[0].content).toBe(
        "3 duplicate claims collapsed",
      );
    });

    it("upserts coverage_matrix with done/total", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coverage_matrix",
          run_id: "r1",
          round: 1,
          coverage_complete: 8,
          coverage_total: 10,
        }),
      );
      expect(next.teamEvents[0].detail).toBe("8/10 covered");
    });

    it("upserts coherency_score with rejected status below 0.45", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coherency_score",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          coherency_score: 0.3,
        }),
      );
      expect(next.teamEvents[0].status).toBe("rejected");
    });

    it("upserts tool_phase with proposal count", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "tool_phase",
          run_id: "r1",
          round: 1,
          agent_id: "a1",
          agent_name: "Writer",
          tool_phase: "search",
          proposals: [{ id: 1 }, { id: 2 }],
        }),
      );
      expect(next.teamEvents[0].kind).toBe("tool");
      expect(next.teamEvents[0].status).toBe("rejected");
    });

    it("upserts debate_skipped with coverage info", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "debate_skipped",
          run_id: "r1",
          round: 3,
          reason: "Blackboard empty",
          coverage_complete: 5,
          coverage_total: 10,
        }),
      );
      expect(next.teamEvents[0].content).toBe("5/10 covered");
    });

    it("upserts adaptive_vote with triggers", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "adaptive_vote",
          run_id: "r1",
          round: 4,
          triggers: ["low_coherency", "blocked_claims"],
        }),
      );
      expect(next.teamEvents[0].kind).toBe("vote");
      expect(next.teamEvents[0].detail).toBe(
        "low_coherency, blocked_claims",
      );
    });

    it("upserts vote_started", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "vote_started",
          run_id: "r1",
          round: 5,
        }),
      );
      expect(next.teamEvents[0].status).toBe("running");
    });

    it("pushes agent_vote with approved status", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "agent_vote",
          run_id: "r1",
          round: 5,
          agent_id: "a1",
          agent_name: "Writer",
          approve: true,
          confidence: 0.95,
        }),
      );
      expect(next.teamEvents[0].status).toBe("approved");
    });

    it("upserts consensus_reached", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "consensus_reached",
          run_id: "r1",
          consensus: { approvals: 3, required: 4, threshold: 0.6 },
        }),
      );
      expect(next.teamEvents[0].kind).toBe("consensus");
      expect(next.teamEvents[0].detail).toBe("3/4 approvals");
    });

    it("upserts coordinator_planning_completed with duration", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coordinator_planning_completed",
          run_id: "r1",
          round: 1,
          agent_id: "coord-1",
          agent_name: "Coordinator",
          duration_ms: 2500,
          guidance: { summary: "Focus on claims" },
        }),
      );
      expect(next.teamEvents[0].status).toBe("completed");
      expect(next.teamEvents[0].content).toBe("Focus on claims");
    });

    it("upserts coordinator_redirect", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coordinator_redirect",
          run_id: "r1",
          round: 1,
          agent_id: "a2",
          redirect: "Try again",
        }),
      );
      expect(next.teamEvents[0].kind).toBe("coordinator");
      expect(next.teamEvents[0].content).toBe("Try again");
    });

    it("upserts coordinator_started", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coordinator_started",
          run_id: "r1",
          round: 1,
          agent_id: "coord-1",
          agent_name: "Coordinator",
        }),
      );
      expect(next.teamEvents[0].kind).toBe("coordinator");
      expect(next.teamEvents[0].status).toBe("running");
    });

    it("upserts coordinator_completed", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "coordinator_completed",
          run_id: "r1",
          round: 1,
          agent_id: "coord-1",
          agent_name: "Coordinator",
          duration_ms: 3000,
        }),
      );
      expect(next.teamEvents[0].status).toBe("completed");
      expect(next.teamEvents[0].detail).toBe("3000 ms");
    });

    it("upserts team_consensus_failed with reason", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({
          event: "team_consensus_failed",
          run_id: "r1",
          reason: "No consensus",
        }),
      );
      expect(next.teamEvents[0].kind).toBe("failed");
      expect(next.teamEvents[0].detail).toBe("No consensus");
    });

    it("upserts team_run_cancelled", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({ event: "team_run_cancelled", run_id: "r1" }),
      );
      expect(next.teamEvents[0].status).toBe("cancelled");
    });

    it("upserts team_run_completed", () => {
      const next = applyTeamTraceEvent(
        makeMessage(),
        makeEvent({ event: "team_run_completed", run_id: "r1" }),
      );
      expect(next.teamEvents[0].kind).toBe("run");
      expect(next.teamEvents[0].status).toBe("completed");
    });

    it("updates existing trace by id rather than duplicating", () => {
      const msg = makeMessage({
        teamEvents: [
          {
            id: "r1-run",
            kind: "run",
            title: "Old",
            detail: "Running",
            status: "running",
          },
        ],
      });
      const next = applyTeamTraceEvent(
        msg,
        makeEvent({ event: "team_run_completed", run_id: "r1" }),
      );
      expect(next.teamEvents).toHaveLength(1);
      expect(next.teamEvents[0].status).toBe("completed");
    });
  });
});
