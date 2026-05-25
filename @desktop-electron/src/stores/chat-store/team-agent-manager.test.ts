import { describe, it, expect, vi } from "vitest";
import {
  upsertTeamAgent,
  mergeAgentLogs,
  isStreamingAgentTextLog,
  isEmptyStreamingAgentLog,
  hasOpenStreamingAgentLog,
  findMergeableAgentLogIndex,
  isSameTeamTurnLog,
  teamAgentLogFromEvent,
  durationSummary,
  type TeamAgentPatch,
} from "./team-agent-manager";
import type {
  TeamRunUi,
  TeamRunEvent,
  TeamAgentTraceUi,
  TeamAgentLogUi,
  TeamClaimTraceUi,
  TeamToolTraceUi,
} from "../../types/chat";

vi.mock("./internal", () => {
  let seq = 0;
  return {
    MAX_TEAM_AGENT_LOGS: 80,
    bumpTeamAgentLogSequence: vi.fn(() => ++seq),
  };
});

function mergeClaims(
  existing: TeamClaimTraceUi[],
  incoming: TeamClaimTraceUi[],
): TeamClaimTraceUi[] {
  if (incoming.length === 0) return existing;
  const claims = [...existing];
  for (const claim of incoming) {
    const index = claims.findIndex((item) => item.id === claim.id);
    if (index >= 0) claims[index] = { ...claims[index], ...claim };
    else claims.push(claim);
  }
  return claims.slice(-24);
}

function upsertTeamTool(
  tools: TeamToolTraceUi[],
  tool: TeamToolTraceUi,
): TeamToolTraceUi[] {
  const index = tools.findIndex((item) => item.id === tool.id);
  if (index < 0) return [...tools, tool];
  const next = [...tools];
  next[index] = { ...next[index], ...tool };
  return next;
}

function makeEvent(overrides: Partial<TeamRunEvent> = {}): TeamRunEvent {
  return {
    event: "agent_turn_started",
    run_id: "run-1",
    round: 1,
    agent_id: "a1",
    agent_name: "Agent 1",
    agent_role: "writer",
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

function makeAgent(
  overrides: Partial<TeamAgentTraceUi> = {},
): TeamAgentTraceUi {
  return {
    agentId: "a1",
    agentName: "Agent 1",
    agentRole: "writer",
    status: "idle",
    thinking: "",
    output: "",
    logs: [],
    claims: [],
    tools: [],
    ...overrides,
  };
}

function makeLog(
  overrides: Partial<TeamAgentLogUi> = {},
): TeamAgentLogUi {
  return {
    id: "log-1",
    kind: "status",
    title: "Started",
    round: 1,
    phase: "debate",
    ...overrides,
  };
}

describe("team-agent-manager", () => {
  describe("upsertTeamAgent", () => {
    it("returns run unchanged when no agentId can be determined", () => {
      const run = makeRun();
      const event = makeEvent({ agent_id: undefined });
      const next = upsertTeamAgent(run, event, {}, mergeClaims, upsertTeamTool);
      expect(next).toBe(run);
    });

    it("creates a new agent when not found in run", () => {
      const run = makeRun();
      const event = makeEvent({ agent_id: "new-agent", agent_name: "New" });
      const next = upsertTeamAgent(
        run,
        event,
        { status: "running" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents).toHaveLength(1);
      expect(next.agents[0].agentId).toBe("new-agent");
      expect(next.agents[0].status).toBe("running");
    });

    it("defaults new agent name to 'Coordinator' when isCoordinator", () => {
      const run = makeRun();
      const event = makeEvent({ agent_id: "coord", agent_name: undefined });
      const next = upsertTeamAgent(
        run,
        event,
        { isCoordinator: true, status: "running" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].agentName).toBe("Coordinator");
    });

    it("updates existing agent without duplicating", () => {
      const existing = makeAgent({ agentId: "a1", status: "idle" });
      const run = makeRun({ agents: [existing] });
      const event = makeEvent({ agent_id: "a1", agent_name: "Updated" });
      const next = upsertTeamAgent(
        run,
        event,
        { status: "completed", phase: "debate" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents).toHaveLength(1);
      expect(next.agents[0].agentName).toBe("Updated");
      expect(next.agents[0].status).toBe("completed");
      expect(next.agents[0].phase).toBe("debate");
    });

    it("appends thinking via thinkingAppend", () => {
      const existing = makeAgent({ agentId: "a1", thinking: "Hello" });
      const run = makeRun({ agents: [existing] });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { thinkingAppend: " world" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].thinking).toBe("Hello world");
    });

    it("appends output via outputAppend", () => {
      const existing = makeAgent({ agentId: "a1", output: "Result" });
      const run = makeRun({ agents: [existing] });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { outputAppend: " complete" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].output).toBe("Result complete");
    });

    it("replaces thinking when patch.thinking is set", () => {
      const existing = makeAgent({ agentId: "a1", thinking: "Old" });
      const run = makeRun({ agents: [existing] });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { thinking: "New" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].thinking).toBe("New");
    });

    it("merges claims via collaborator", () => {
      const existing = makeAgent({
        agentId: "a1",
        claims: [{ id: "c1", type: "claim", text: "existing", status: "active" }],
      });
      const run = makeRun({ agents: [existing] });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        {
          claims: [{ id: "c2", type: "claim", text: "new", status: "active" }],
        },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].claims).toHaveLength(2);
    });

    it("merges single claim via claim patch", () => {
      const existing = makeAgent({
        agentId: "a1",
        claims: [{ id: "c1", type: "claim", text: "existing", status: "active" }],
      });
      const run = makeRun({ agents: [existing] });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { claim: { id: "c2", type: "blocker", text: "new", status: "active" } },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].claims).toHaveLength(2);
    });

    it("upserts tool via collaborator", () => {
      const existing = makeAgent({
        agentId: "a1",
        tools: [{ id: "tool-1", phase: "tools", title: "Search", status: "completed", calls: [], results: [], proposals: [], createdAt: "" }],
      });
      const run = makeRun({ agents: [existing] });
      const newTool: TeamToolTraceUi = {
        id: "tool-2",
        phase: "tools",
        title: "Grep",
        status: "running",
        calls: [],
        results: [],
        proposals: [],
        createdAt: "",
      };
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { tool: newTool },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].tools).toHaveLength(2);
    });

    it("merges logs via mergeAgentLogs", () => {
      const existing = makeAgent({ agentId: "a1", logs: [] });
      const run = makeRun({ agents: [existing] });
      const log = makeLog({ kind: "status", title: "Started", content: "go" });
      const next = upsertTeamAgent(
        run,
        makeEvent(),
        { logs: [log] },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].logs).toHaveLength(1);
    });

    it("cleans up temporary patch keys from agent", () => {
      const run = makeRun();
      const next = upsertTeamAgent(
        run,
        makeEvent({ agent_id: "a1" }),
        {
          thinkingAppend: "extra",
          outputAppend: "more",
          log: makeLog(),
        },
        mergeClaims,
        upsertTeamTool,
      );
      const agent = next.agents[0] as TeamAgentPatch & TeamAgentTraceUi;
      expect((agent as TeamAgentPatch).thinkingAppend).toBeUndefined();
      expect((agent as TeamAgentPatch).outputAppend).toBeUndefined();
    });

    it("uses event agent_id over patch agentId for identity", () => {
      const existing = makeAgent({ agentId: "a1", agentName: "A1" });
      const run = makeRun({ agents: [existing] });
      const event = makeEvent({ agent_id: "a1", agent_name: "Updated A1" });
      const next = upsertTeamAgent(
        run,
        event,
        { agentId: "a2", status: "running" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents).toHaveLength(1);
      expect(next.agents[0].agentId).toBe("a1");
    });

    it("falls back to patch.agentId when event has no agent_id", () => {
      const run = makeRun();
      const event = makeEvent({ agent_id: undefined });
      const next = upsertTeamAgent(
        run,
        event,
        { agentId: "a2", status: "running" },
        mergeClaims,
        upsertTeamTool,
      );
      expect(next.agents[0].agentId).toBe("a2");
    });
  });

  describe("mergeAgentLogs", () => {
    it("returns existing when incoming is empty", () => {
      const existing = [makeLog()];
      const result = mergeAgentLogs(existing, []);
      expect(result).toBe(existing);
    });

    it("appends new log when no merge possible", () => {
      const existing = [makeLog({ kind: "status" })];
      const incoming = [makeLog({ kind: "status", title: "Different" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result).toHaveLength(2);
    });

    it("merges streaming text log with matching running log", () => {
      const existing = [makeLog({ kind: "thinking", status: "running", content: "Hello", round: 1, phase: "debate" })];
      const incoming = [makeLog({ kind: "thinking", status: "running", content: " world", round: 1, phase: "debate" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result).toHaveLength(1);
      expect(result[0].content).toBe("Hello world");
    });

    it("skips empty streaming logs when no open stream exists", () => {
      const existing = [makeLog({ kind: "status", status: "completed" })];
      const incoming = [makeLog({ kind: "thinking", status: "running", content: "" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result).toHaveLength(1);
    });

    it("does not skip empty streaming log when open stream exists", () => {
      const existing = [makeLog({ kind: "thinking", status: "running", content: "Hello" })];
      const incoming = [makeLog({ kind: "thinking", status: "running", content: "" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result).toHaveLength(1);
    });

    it("deduplicates identical consecutive logs", () => {
      const log = makeLog({ kind: "status", title: "Same", content: "x", status: "completed" });
      const existing = [log];
      const incoming = [makeLog({ kind: "status", title: "Same", content: "x", status: "completed" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result).toHaveLength(1);
    });

    it("caps logs at MAX_TEAM_AGENT_LOGS", () => {
      const existing: TeamAgentLogUi[] = [];
      for (let i = 0; i < 90; i++) {
        existing.push(makeLog({ id: `log-${i}`, kind: "status", title: `Log ${i}` }));
      }
      const incoming = [makeLog({ id: "log-new", kind: "status", title: "New" })];
      const result = mergeAgentLogs(existing, incoming);
      expect(result.length).toBeLessThanOrEqual(80);
    });
  });

  describe("isStreamingAgentTextLog", () => {
    it("returns true for thinking with running status", () => {
      expect(isStreamingAgentTextLog(makeLog({ kind: "thinking", status: "running" }))).toBe(true);
    });

    it("returns true for response with running status", () => {
      expect(isStreamingAgentTextLog(makeLog({ kind: "response", status: "running" }))).toBe(true);
    });

    it("returns false for non-running thinking", () => {
      expect(isStreamingAgentTextLog(makeLog({ kind: "thinking", status: "completed" }))).toBe(false);
    });

    it("returns false for non-text kinds", () => {
      expect(isStreamingAgentTextLog(makeLog({ kind: "status", status: "running" }))).toBe(false);
    });
  });

  describe("isEmptyStreamingAgentLog", () => {
    it("returns true for empty streaming text log", () => {
      expect(
        isEmptyStreamingAgentLog(
          makeLog({ kind: "thinking", status: "running", content: "" }),
        ),
      ).toBe(true);
    });

    it("returns false for non-empty streaming text log", () => {
      expect(
        isEmptyStreamingAgentLog(
          makeLog({ kind: "thinking", status: "running", content: "hello" }),
        ),
      ).toBe(false);
    });

    it("returns false for non-streaming log", () => {
      expect(
        isEmptyStreamingAgentLog(
          makeLog({ kind: "status", status: "completed", content: "" }),
        ),
      ).toBe(false);
    });
  });

  describe("hasOpenStreamingAgentLog", () => {
    it("returns true when mergeable index exists", () => {
      const logs = [makeLog({ kind: "thinking", status: "running", content: "x", round: 1, phase: "debate" })];
      const incoming = makeLog({ kind: "thinking", status: "running", content: "y", round: 1, phase: "debate" });
      expect(hasOpenStreamingAgentLog(logs, incoming)).toBe(true);
    });

    it("returns false when no mergeable index", () => {
      const logs = [makeLog({ kind: "status", status: "completed" })];
      const incoming = makeLog({ kind: "thinking", status: "running", content: "y", round: 1, phase: "debate" });
      expect(hasOpenStreamingAgentLog(logs, incoming)).toBe(false);
    });
  });

  describe("findMergeableAgentLogIndex", () => {
    it("returns index of matching running log of same kind", () => {
      const logs = [
        makeLog({ kind: "status", status: "completed", round: 1, phase: "debate" }),
        makeLog({ kind: "thinking", status: "running", round: 1, phase: "debate" }),
      ];
      const incoming = makeLog({ kind: "thinking", status: "running", round: 1, phase: "debate" });
      expect(findMergeableAgentLogIndex(logs, incoming)).toBe(1);
    });

    it("returns -1 for non-streaming incoming", () => {
      const logs = [makeLog({ kind: "thinking", status: "running", round: 1, phase: "debate" })];
      const incoming = makeLog({ kind: "status", status: "completed", round: 1, phase: "debate" });
      expect(findMergeableAgentLogIndex(logs, incoming)).toBe(-1);
    });

    it("returns -1 when turn does not match", () => {
      const logs = [makeLog({ kind: "thinking", status: "running", round: 1, phase: "debate" })];
      const incoming = makeLog({ kind: "thinking", status: "running", round: 2, phase: "debate" });
      expect(findMergeableAgentLogIndex(logs, incoming)).toBe(-1);
    });

    it("stops searching at non-matching turn boundary", () => {
      const logs = [
        makeLog({ kind: "thinking", status: "running", round: 1, phase: "debate" }),
        makeLog({ kind: "thinking", status: "running", round: 2, phase: "vote" }),
      ];
      const incoming = makeLog({ kind: "thinking", status: "running", round: 2, phase: "vote" });
      expect(findMergeableAgentLogIndex(logs, incoming)).toBe(1);
    });
  });

  describe("isSameTeamTurnLog", () => {
    it("returns true for matching round and phase", () => {
      expect(
        isSameTeamTurnLog(
          makeLog({ round: 2, phase: "debate" }),
          makeLog({ round: 2, phase: "debate" }),
        ),
      ).toBe(true);
    });

    it("returns false for different round", () => {
      expect(
        isSameTeamTurnLog(
          makeLog({ round: 1, phase: "debate" }),
          makeLog({ round: 2, phase: "debate" }),
        ),
      ).toBe(false);
    });

    it("returns false for different phase", () => {
      expect(
        isSameTeamTurnLog(
          makeLog({ round: 1, phase: "debate" }),
          makeLog({ round: 1, phase: "vote" }),
        ),
      ).toBe(false);
    });
  });

  describe("teamAgentLogFromEvent", () => {
    it("creates a log with all fields populated", () => {
      const event = makeEvent({ run_id: "r1", agent_id: "a1", event: "agent_turn_started", round: 3, phase: "debate" });
      const log = teamAgentLogFromEvent(event, "status", "Started", "Details", "running", "tool-1");
      expect(log.kind).toBe("status");
      expect(log.title).toBe("Started");
      expect(log.content).toBe("Details");
      expect(log.status).toBe("running");
      expect(log.round).toBe(3);
      expect(log.phase).toBe("debate");
      expect(log.toolId).toBe("tool-1");
    });

    it("uses fallback values when event fields are missing", () => {
      const event = makeEvent({ run_id: undefined, agent_id: undefined, event: "agent_turn_started", round: undefined, phase: undefined });
      const log = teamAgentLogFromEvent(event, "status", "Started");
      expect(log.id).toContain("team-agent-agent_turn_started");
    });

    it("generates unique IDs via sequence bump", () => {
      const event = makeEvent({ run_id: "r1", agent_id: "a1" });
      const log1 = teamAgentLogFromEvent(event, "status", "A");
      const log2 = teamAgentLogFromEvent(event, "status", "B");
      expect(log1.id).not.toBe(log2.id);
    });
  });

  describe("durationSummary", () => {
    it("returns undefined when both duration and first token are null/undefined", () => {
      expect(durationSummary(makeEvent({ duration_ms: undefined, first_token_ms: undefined }))).toBeUndefined();
    });

    it("returns duration-only string", () => {
      expect(durationSummary(makeEvent({ duration_ms: 1500, first_token_ms: undefined }))).toBe("1500 ms total");
    });

    it("returns first token only string", () => {
      expect(durationSummary(makeEvent({ duration_ms: undefined, first_token_ms: 300 }))).toBe("300 ms first token");
    });

    it("returns combined duration and first token", () => {
      expect(durationSummary(makeEvent({ duration_ms: 2000, first_token_ms: 400 }))).toBe("2000 ms total | 400 ms first token");
    });
  });
});
