import { describe, it, expect } from "vitest";
import {
  createTeamRun,
  createBlackboardTrace,
  cloneTeamRun,
  cloneToolTrace,
  seedTeamAgents,
  runStatusForEvent,
  blackboardStatusForEvent,
  isTerminalTeamEvent,
  phaseForEvent,
  phaseLabel,
  toolPhaseLabel,
  nextActionForEvent,
} from "./team-run-lifecycle";
import type {
  TeamRunEvent,
  TeamRunUi,
  TeamToolTraceUi,
  TeamConfig,
  TeamAgent,
} from "../../types/chat";

function makeTeamConfig(overrides: Partial<TeamConfig> = {}): TeamConfig {
  return {
    id: "team-1",
    name: "Test Team",
    agents: [],
    execution_order: [],
    max_rounds: null,
    vote_every_rounds: 1,
    consensus_threshold: 0.6,
    ...overrides,
  };
}

function makeTeamAgent(overrides: Partial<TeamAgent> = {}): TeamAgent {
  return {
    id: "a1",
    name: "Agent 1",
    role: "writer",
    system_prompt: "",
    temperature: 0.7,
    max_tokens: 4096,
    tools_enabled: true,
    ...overrides,
  };
}

function makeEvent(overrides: Partial<TeamRunEvent> = {}): TeamRunEvent {
  return {
    event: "team_run_started",
    run_id: "run-1",
    round: 1,
    team: makeTeamConfig(),
    created_at: new Date().toISOString(),
    ...overrides,
  } as TeamRunEvent;
}

function makeRun(overrides: Partial<TeamRunUi> = {}): TeamRunUi {
  return {
    runId: "run-1",
    title: "Test Team",
    status: "running",
    round: 1,
    actualPhase: "starting",
    agents: [],
    blackboard: {
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
    },
    votes: [],
    startedAt: new Date().toISOString(),
    ...overrides,
  };
}

function makeToolTrace(overrides: Partial<TeamToolTraceUi> = {}): TeamToolTraceUi {
  return {
    id: "tool-1",
    phase: "tools",
    title: "Search",
    status: "completed",
    calls: [{ name: "grep", args: {} }],
    results: [{ content: "found" }],
    proposals: [],
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("team-run-lifecycle", () => {
  describe("createTeamRun", () => {
    it("creates a run with default values", () => {
      const run = createTeamRun(makeEvent({ event: "team_run_started" }));
      expect(run.title).toBe("Test Team");
      expect(run.status).toBe("running");
      expect(run.agents).toEqual([]);
      expect(run.votes).toEqual([]);
    });

    it("falls back to 'Team Mode' title when no team name", () => {
      const run = createTeamRun(makeEvent({ team: undefined }));
      expect(run.title).toBe("Team Mode");
    });

    it("initializes blackboard with correct status", () => {
      const run = createTeamRun(makeEvent());
      expect(run.blackboard.status).toBe("running");
      expect(run.blackboard.claims).toEqual([]);
    });

    it("uses run_id from event", () => {
      const run = createTeamRun(makeEvent({ run_id: "custom-id" }));
      expect(run.runId).toBe("custom-id");
    });

    it("sets actualPhase from event phase", () => {
      const run = createTeamRun(makeEvent({ phase: "debate" }));
      expect(run.actualPhase).toBe("debate");
    });

    it("defaults actualPhase to 'starting' when no phase", () => {
      const run = createTeamRun(makeEvent({ phase: undefined }));
      expect(run.actualPhase).toBe("starting");
    });
  });

  describe("createBlackboardTrace", () => {
    it("creates trace with all empty collections", () => {
      const trace = createBlackboardTrace(makeEvent(), "running");
      expect(trace.status).toBe("running");
      expect(trace.claims).toEqual([]);
      expect(trace.evidence).toEqual([]);
      expect(trace.decisions).toEqual([]);
      expect(trace.blockers).toEqual([]);
      expect(trace.coverage).toEqual([]);
      expect(trace.tools).toEqual([]);
    });

    it("sets status to the provided value", () => {
      const trace = createBlackboardTrace(makeEvent(), "completed");
      expect(trace.status).toBe("completed");
    });

    it("sets nextAction for execution_contract event", () => {
      const trace = createBlackboardTrace(
        makeEvent({ event: "execution_contract" }),
        "running",
      );
      expect(trace.nextAction).toBe("Independent round");
    });

    it("sets nextAction for round_started event", () => {
      const trace = createBlackboardTrace(
        makeEvent({ event: "round_started", phase: "debate" }),
        "running",
      );
      expect(trace.nextAction).toBe("debate");
    });
  });

  describe("cloneTeamRun", () => {
    it("deep-clones agents array", () => {
      const run = makeRun({
        agents: [
          {
            agentId: "a1",
            agentName: "Agent 1",
            agentRole: "writer",
            status: "running",
            thinking: "x",
            output: "",
            logs: [],
            claims: [],
            tools: [],
          },
        ],
      });
      const clone = cloneTeamRun(run);
      clone.agents[0].agentName = "Modified";
      expect(run.agents[0].agentName).toBe("Agent 1");
    });

    it("deep-clones blackboard claims array", () => {
      const run = makeRun({
        blackboard: {
          ...makeRun().blackboard,
          claims: [
            { id: "c1", type: "claim", text: "test", status: "active" },
          ],
        },
      });
      const clone = cloneTeamRun(run);
      clone.blackboard.claims.push({
        id: "c2",
        type: "claim",
        text: "extra",
        status: "active",
      });
      expect(run.blackboard.claims).toHaveLength(1);
      expect(clone.blackboard.claims).toHaveLength(2);
    });

    it("deep-clones votes", () => {
      const run = makeRun({
        votes: [
          { id: "v1", kind: "vote", title: "Vote", status: "approved" },
        ],
      });
      const clone = cloneTeamRun(run);
      clone.votes.push({
        id: "v2",
        kind: "vote",
        title: "Extra",
        status: "approved",
      });
      expect(run.votes).toHaveLength(1);
    });

    it("deep-clones blackboard tools", () => {
      const tool = makeToolTrace();
      const run = makeRun({
        blackboard: { ...makeRun().blackboard, tools: [tool] },
      });
      const clone = cloneTeamRun(run);
      clone.blackboard.tools[0].calls.push({ name: "new", args: {} });
      expect(run.blackboard.tools[0].calls).toHaveLength(1);
    });
  });

  describe("cloneToolTrace", () => {
    it("deep-clones calls array", () => {
      const tool = makeToolTrace();
      const clone = cloneToolTrace(tool);
      clone.calls.push({ name: "extra", args: {} });
      expect(tool.calls).toHaveLength(1);
    });

    it("deep-clones results array", () => {
      const tool = makeToolTrace();
      const clone = cloneToolTrace(tool);
      clone.results.push({ content: "extra" });
      expect(tool.results).toHaveLength(1);
      expect(clone.results).toHaveLength(2);
    });

    it("deep-clones proposals array", () => {
      const tool = makeToolTrace({
        proposals: [{ agent_id: "a1", action: "approve" }],
      });
      const clone = cloneToolTrace(tool);
      clone.proposals.push({ agent_id: "a2", action: "block" });
      expect(tool.proposals).toHaveLength(1);
    });
  });

  describe("seedTeamAgents", () => {
    it("adds new agents from event team config", () => {
      const agent1 = makeTeamAgent();
      const agent2 = makeTeamAgent({ id: "a2", name: "Agent 2", role: "reviewer" });
      const event = makeEvent({
        team: makeTeamConfig({ agents: [agent1, agent2] }),
      });
      const run = seedTeamAgents(makeRun(), event);
      expect(run.agents).toHaveLength(2);
      expect(run.agents[0].agentId).toBe("a1");
      expect(run.agents[1].agentId).toBe("a2");
    });

    it("does not duplicate existing agents", () => {
      const run = makeRun({
        agents: [
          {
            agentId: "a1",
            agentName: "Existing",
            agentRole: "writer",
            status: "idle",
            thinking: "",
            output: "",
            logs: [],
            claims: [],
            tools: [],
          },
        ],
      });
      const event = makeEvent({
        team: makeTeamConfig({ agents: [makeTeamAgent()] }),
      });
      const next = seedTeamAgents(run, event);
      expect(next.agents).toHaveLength(1);
    });

    it("returns run unchanged when team has no agents", () => {
      const run = makeRun();
      const event = makeEvent({
        team: makeTeamConfig({ agents: [] }),
      });
      const next = seedTeamAgents(run, event);
      expect(next.agents).toEqual([]);
    });

    it("returns run unchanged when team is undefined", () => {
      const run = makeRun();
      const event = makeEvent({ team: undefined });
      const next = seedTeamAgents(run, event);
      expect(next).toBe(run);
    });
  });

  describe("runStatusForEvent", () => {
    it('returns "completed" for team_run_completed', () => {
      expect(
        runStatusForEvent(
          makeEvent({ event: "team_run_completed" }),
          "running",
        ),
      ).toBe("completed");
    });

    it('returns "failed" for team_consensus_failed', () => {
      expect(
        runStatusForEvent(
          makeEvent({ event: "team_consensus_failed" }),
          "running",
        ),
      ).toBe("failed");
    });

    it('returns "cancelled" for team_run_cancelled', () => {
      expect(
        runStatusForEvent(
          makeEvent({ event: "team_run_cancelled" }),
          "running",
        ),
      ).toBe("cancelled");
    });

    it('returns "failed" for error event without agent_id', () => {
      expect(
        runStatusForEvent(makeEvent({ event: "error" }), "running"),
      ).toBe("failed");
    });

    it('returns "running" for team_run_started', () => {
      expect(
        runStatusForEvent(
          makeEvent({ event: "team_run_started" }),
          "idle",
        ),
      ).toBe("running");
    });

    it("preserves non-idle current status for unknown events", () => {
      const event = makeEvent({ event: "agent_delta" });
      expect(runStatusForEvent(event, "completed")).toBe("completed");
    });

    it("promotes idle to running for unknown events", () => {
      const event = makeEvent({ event: "agent_delta" });
      expect(runStatusForEvent(event, "idle")).toBe("running");
    });

    it("does not override error status for team_run_started", () => {
      expect(
        runStatusForEvent(
          makeEvent({ event: "team_run_started" }),
          "failed",
        ),
      ).toBe("running");
    });
  });

  describe("blackboardStatusForEvent", () => {
    it("returns runStatus when completed", () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "blackboard_event" }),
          "completed",
          "running",
        ),
      ).toBe("completed");
    });

    it("returns runStatus when failed", () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "blackboard_event" }),
          "failed",
          "running",
        ),
      ).toBe("failed");
    });

    it("returns runStatus when cancelled", () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "blackboard_event" }),
          "cancelled",
          "running",
        ),
      ).toBe("cancelled");
    });

    it('returns "running" for blackboard-related events', () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "blackboard_event" }),
          "running",
          "idle",
        ),
      ).toBe("running");
    });

    it("promotes idle to running for generic events", () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "round_started" }),
          "running",
          "idle",
        ),
      ).toBe("running");
    });

    it("preserves running status", () => {
      expect(
        blackboardStatusForEvent(
          makeEvent({ event: "round_started" }),
          "running",
          "running",
        ),
      ).toBe("running");
    });
  });

  describe("isTerminalTeamEvent", () => {
    it("returns true for team_run_completed", () => {
      expect(
        isTerminalTeamEvent(makeEvent({ event: "team_run_completed" })),
      ).toBe(true);
    });

    it("returns true for team_consensus_failed", () => {
      expect(
        isTerminalTeamEvent(makeEvent({ event: "team_consensus_failed" })),
      ).toBe(true);
    });

    it("returns true for team_run_cancelled", () => {
      expect(
        isTerminalTeamEvent(makeEvent({ event: "team_run_cancelled" })),
      ).toBe(true);
    });

    it("returns true for error without agent_id", () => {
      expect(isTerminalTeamEvent(makeEvent({ event: "error" }))).toBe(true);
    });

    it("returns false for error with agent_id", () => {
      expect(
        isTerminalTeamEvent(makeEvent({ event: "error", agent_id: "a1" })),
      ).toBe(false);
    });

    it("returns false for running events", () => {
      expect(
        isTerminalTeamEvent(makeEvent({ event: "agent_delta" })),
      ).toBe(false);
    });
  });

  describe("phaseForEvent", () => {
    it('returns "coordinator" for coordinator_started', () => {
      expect(
        phaseForEvent(makeEvent({ event: "coordinator_started" })),
      ).toBe("coordinator");
    });

    it('returns "coordinator planning" for coordinator_planning_started', () => {
      expect(
        phaseForEvent(
          makeEvent({ event: "coordinator_planning_started" }),
        ),
      ).toBe("coordinator planning");
    });

    it('returns "debate" for debate_started', () => {
      expect(
        phaseForEvent(makeEvent({ event: "debate_started" })),
      ).toBe("debate");
    });

    it('returns "vote" for agent_vote', () => {
      expect(phaseForEvent(makeEvent({ event: "agent_vote" }))).toBe("vote");
    });

    it('returns "blackboard" for blackboard_snapshot', () => {
      expect(
        phaseForEvent(makeEvent({ event: "blackboard_snapshot" })),
      ).toBe("blackboard");
    });

    it("returns undefined for unknown event", () => {
      const event = makeEvent({ event: "agent_delta" });
      expect(phaseForEvent(event)).toBeUndefined();
    });
  });

  describe("phaseLabel", () => {
    it("replaces underscores with spaces", () => {
      expect(phaseLabel("coordinator_planning")).toBe(
        "coordinator planning",
      );
    });

    it("returns undefined for undefined input", () => {
      expect(phaseLabel(undefined)).toBeUndefined();
    });

    it("returns string unchanged when no underscores", () => {
      expect(phaseLabel("debate")).toBe("debate");
    });
  });

  describe("toolPhaseLabel", () => {
    it("replaces underscores with spaces", () => {
      expect(toolPhaseLabel("tool_phase_value")).toBe("tool phase value");
    });
  });

  describe("nextActionForEvent", () => {
    it('returns "Independent round" for execution_contract', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "execution_contract" })),
      ).toBe("Independent round");
    });

    it("returns phase label for round_started", () => {
      expect(
        nextActionForEvent(
          makeEvent({ event: "round_started", phase: "debate" }),
        ),
      ).toBe("debate");
    });

    it('returns "Agent round" fallback for round_started without phase', () => {
      expect(
        nextActionForEvent(
          makeEvent({ event: "round_started", phase: undefined }),
        ),
      ).toBe("Agent round");
    });

    it('returns "Debate" for debate_started', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "debate_started" })),
      ).toBe("Debate");
    });

    it('returns "Vote" for vote_started', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "vote_started" })),
      ).toBe("Vote");
    });

    it('returns "Coordinator" for coordinator_started', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "coordinator_started" })),
      ).toBe("Coordinator");
    });

    it('returns "Completed" for team_run_completed', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "team_run_completed" })),
      ).toBe("Completed");
    });

    it('returns "Review blockers" for team_consensus_failed', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "team_consensus_failed" })),
      ).toBe("Review blockers");
    });

    it('returns "Cancelled" for team_run_cancelled', () => {
      expect(
        nextActionForEvent(makeEvent({ event: "team_run_cancelled" })),
      ).toBe("Cancelled");
    });

    it("returns undefined for unknown events", () => {
      const event = makeEvent({ event: "agent_delta" });
      expect(nextActionForEvent(event)).toBeUndefined();
    });
  });
});
