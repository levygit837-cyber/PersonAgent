import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAppStore } from "./app-store";
import { useChatStore } from "./chat-store";
import { emptySessionUsage, type TeamRunEvent } from "../types/chat";

const apiMocks = vi.hoisted(() => ({
  streamTeamChat: vi.fn(),
  streamChatCompletion: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    streamTeamChat: apiMocks.streamTeamChat,
    streamChatCompletion: apiMocks.streamChatCompletion,
  };
});

describe("Team Mode compact chat store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiMocks.streamTeamChat.mockReset();
    apiMocks.streamChatCompletion.mockReset();
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      provider: "llama",
      selectedModelId: "local-model",
      reasoningPreset: "low",
      selectedWorkspace: "/workspace",
      teamMode: true,
    });
    useChatStore.setState({
      messages: [],
      conversationId: undefined,
      conversationTitle: undefined,
      error: undefined,
      isStreaming: false,
      isFinalizing: false,
      activeController: undefined,
      activeAgentId: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
    });
  });

  it("keeps streamed agent thinking inside the agent card and final_delta as the visible answer", async () => {
    apiMocks.streamTeamChat.mockImplementation(() =>
      eventStream([
        {
          event: "team_run_started",
          run_id: "run-1",
          team: {
            id: "team",
            name: "Team Mode",
            agents: [teamAgent("analyst", "Analyst", "requirements")],
            execution_order: ["analyst"],
            max_rounds: 1,
            vote_every_rounds: 2,
            consensus_threshold: 0.75,
          },
        },
        {
          event: "agent_turn_started",
          run_id: "run-1",
          round: 1,
          phase: "independent_round",
          agent_id: "analyst",
          agent_name: "Analyst",
          agent_role: "requirements",
        },
        {
          event: "agent_delta",
          run_id: "run-1",
          round: 1,
          phase: "independent_round",
          agent_id: "analyst",
          agent_name: "Analyst",
          content: "partial output",
          reasoning_content: "private thinking",
        },
        {
          event: "agent_delta",
          run_id: "run-1",
          round: 1,
          phase: "independent_round",
          agent_id: "analyst",
          agent_name: "Analyst",
          content: " more output",
          reasoning_content: " next thought",
        },
        {
          event: "agent_turn_completed",
          run_id: "run-1",
          round: 1,
          phase: "independent_round",
          agent_id: "analyst",
          agent_name: "Analyst",
          content: "final agent output",
          reasoning_content: "private thinking complete",
          digest: "agent digest",
          status: "completed",
        },
        {
          event: "final_delta",
          run_id: "run-1",
          content: "Coordinator final answer",
        },
        {
          event: "team_run_completed",
          run_id: "run-1",
          completed_at: "2026-04-27T12:00:00Z",
        },
      ]),
    );

    await useChatStore.getState().sendMessage("Run team");

    const agentMessage = useChatStore.getState().messages.find((message) => message.role === "agent");
    expect(agentMessage?.reasoning).toBe("");
    expect(agentMessage?.reasoningBlocks).toHaveLength(0);
    expect(agentMessage?.content).toBe("Coordinator final answer");
    expect(agentMessage?.teamRun?.agents[0]?.thinking).toBe("private thinking complete");
    expect(agentMessage?.teamRun?.agents[0]?.output).toBe("final agent output");
    const textLogs = agentMessage?.teamRun?.agents[0]?.logs.filter((log) => log.kind === "thinking" || log.kind === "response");
    expect(textLogs).toEqual([
      expect.objectContaining({ kind: "thinking", content: "private thinking next thought" }),
      expect.objectContaining({ kind: "response", content: "partial output more output" }),
    ]);
    expect(agentMessage?.teamRun?.agents[0]?.status).toBe("completed");
    expect(agentMessage?.teamRun?.status).toBe("completed");
  });

  it("tracks blackboard snapshots and tool phases by agent id", async () => {
    apiMocks.streamTeamChat.mockImplementation(() =>
      eventStream([
        { event: "team_run_started", run_id: "run-2" },
        {
          event: "agent_turn_started",
          run_id: "run-2",
          round: 1,
          phase: "read_tools",
          agent_id: "builder",
          agent_name: "Builder",
        },
        {
          event: "tool_phase",
          run_id: "run-2",
          round: 1,
          phase: "read_tools",
          tool_phase: "read_tools",
          agent_id: "builder",
          agent_name: "Builder",
          calls: [{ name: "Read" }],
        },
        {
          event: "tool_phase",
          run_id: "run-2",
          round: 1,
          phase: "read_tools",
          tool_phase: "read_tools",
          agent_id: "builder",
          agent_name: "Builder",
          results: [{ output: "file content" }],
        },
        {
          event: "blackboard_snapshot",
          run_id: "run-2",
          round: 1,
          phase: "blackboard_publish",
          snapshot: {
            entry_count: 1,
            latest_sequence: 1,
            claim_graph: {
              nodes: [
                {
                  id: "claim-1",
                  type: "evidence",
                  text: "Read tool returned file content.",
                  agent_id: "builder",
                  agent_name: "Builder",
                  coherency_score: 0.9,
                },
              ],
            },
            evidence: ["Read tool returned file content."],
            coverage_matrix: [{ id: "cov-1", question: "Tool audit", status: "covered" }],
            coherency: { average: 0.9, low_count: 0 },
          },
        },
        { event: "team_run_completed", run_id: "run-2" },
      ]),
    );

    await useChatStore.getState().sendMessage("Use tools");

    const teamRun = useChatStore.getState().messages.find((message) => message.role === "agent")?.teamRun;
    const builder = teamRun?.agents.find((agent) => agent.agentId === "builder");
    expect(builder?.tools[0]?.status).toBe("completed");
    expect(builder?.tools[0]?.results[0]?.output).toBe("file content");
    expect(builder?.logs.some((log) => log.kind === "tool" && log.content === "1 result published")).toBe(true);
    expect(teamRun?.blackboard.claims[0]?.text).toBe("Read tool returned file content.");
    expect(teamRun?.blackboard.coverage[0]?.status).toBe("covered");
    expect(teamRun?.blackboard.coherencyScore).toBe(0.9);
  });

  it("marks agent-scoped errors without turning them into global chat errors", async () => {
    apiMocks.streamTeamChat.mockImplementation(() =>
      eventStream([
        { event: "team_run_started", run_id: "run-3" },
        {
          event: "agent_turn_started",
          run_id: "run-3",
          round: 1,
          phase: "independent_round",
          agent_id: "critic",
          agent_name: "Critic",
        },
        {
          event: "error",
          run_id: "run-3",
          round: 1,
          phase: "independent_round",
          agent_id: "critic",
          agent_name: "Critic",
          error: "Agent timed out",
        },
      ]),
    );

    await useChatStore.getState().sendMessage("Handle an agent failure");

    const state = useChatStore.getState();
    const critic = state.messages.find((message) => message.role === "agent")?.teamRun?.agents[0];
    expect(state.error).toBeUndefined();
    expect(critic?.status).toBe("failed");
    expect(critic?.error).toBe("Agent timed out");
    expect(critic?.logs.some((log) => log.kind === "error" && log.content === "Agent timed out")).toBe(true);
  });
});

async function* eventStream(events: TeamRunEvent[]) {
  for (const event of events) {
    yield event;
  }
}

function teamAgent(id: string, name: string, role: string) {
  return {
    id,
    name,
    role,
    system_prompt: `${name} prompt`,
    temperature: 0.2,
    max_tokens: 1024,
    tools_enabled: true,
  };
}
