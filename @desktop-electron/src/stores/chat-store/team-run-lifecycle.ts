import type {
  TeamRunUi,
  TeamRunEvent,
  TeamCompactStatus,
  TeamBlackboardTraceUi,
  TeamToolTraceUi,
} from "../../types/chat";

export function createTeamRun(event: TeamRunEvent): TeamRunUi {
  const status = runStatusForEvent(event, "running");
  return {
    runId: event.run_id,
    title: event.team?.name ?? "Team Mode",
    status,
    round: event.round,
    actualPhase: phaseLabel(event.phase) ?? phaseForEvent(event) ?? "starting",
    agents: [],
    blackboard: createBlackboardTrace(event, status),
    votes: [],
    startedAt: event.started_at,
    completedAt: event.completed_at,
  };
}

export function createBlackboardTrace(
  event: TeamRunEvent,
  status: TeamCompactStatus,
): TeamBlackboardTraceUi {
  return {
    status,
    actualPhase: phaseLabel(event.phase) ?? phaseForEvent(event) ?? "starting",
    nextAction: nextActionForEvent(event),
    claims: [],
    evidence: [],
    decisions: [],
    blockers: [],
    coverage: [],
    tools: [],
    updatedAt: event.created_at,
  };
}

export function cloneTeamRun(run: TeamRunUi): TeamRunUi {
  return {
    ...run,
    agents: run.agents.map((agent) => ({
      ...agent,
      logs: [...(agent.logs ?? [])],
      claims: [...agent.claims],
      tools: agent.tools.map((tool) => cloneToolTrace(tool)),
    })),
    blackboard: {
      ...run.blackboard,
      claims: [...run.blackboard.claims],
      evidence: [...run.blackboard.evidence],
      decisions: [...run.blackboard.decisions],
      blockers: [...run.blackboard.blockers],
      coverage: [...run.blackboard.coverage],
      tools: run.blackboard.tools.map((tool) => cloneToolTrace(tool)),
    },
    votes: [...run.votes],
  };
}

export function cloneToolTrace(tool: TeamToolTraceUi): TeamToolTraceUi {
  return {
    ...tool,
    calls: [...tool.calls],
    results: [...tool.results],
    proposals: [...tool.proposals],
  };
}

export function seedTeamAgents(run: TeamRunUi, event: TeamRunEvent): TeamRunUi {
  const configs = event.team?.agents ?? [];
  let next = run;
  for (const agent of configs) {
    if (next.agents.some((item) => item.agentId === agent.id)) continue;
    next = {
      ...next,
      agents: [
        ...next.agents,
        {
          agentId: agent.id,
          agentName: agent.name,
          agentRole: agent.role,
          status: "idle",
          thinking: "",
          output: "",
          logs: [],
          claims: [],
          tools: [],
        },
      ],
    };
  }
  return next;
}

export function runStatusForEvent(
  event: TeamRunEvent,
  current: TeamCompactStatus,
): TeamCompactStatus {
  if (event.event === "team_run_completed") return "completed";
  if (event.event === "team_consensus_failed") return "failed";
  if (event.event === "team_run_cancelled") return "cancelled";
  if (event.event === "error" && !event.agent_id) return "failed";
  if (event.event === "team_run_started") return "running";
  return current === "idle" ? "running" : current;
}

export function blackboardStatusForEvent(
  event: TeamRunEvent,
  runStatus: TeamCompactStatus,
  current: TeamCompactStatus,
): TeamCompactStatus {
  if (
    runStatus === "completed" ||
    runStatus === "failed" ||
    runStatus === "cancelled"
  ) {
    return runStatus;
  }
  if (
    event.event === "blackboard_event" ||
    event.event === "blackboard_snapshot" ||
    event.event === "claim_graph_delta" ||
    event.event === "coverage_matrix" ||
    event.event === "coherency_score" ||
    event.event === "tool_phase"
  ) {
    return "running";
  }
  return current === "idle" ? "running" : current;
}

export function isTerminalTeamEvent(event: TeamRunEvent): boolean {
  return (
    event.event === "team_run_completed" ||
    event.event === "team_consensus_failed" ||
    event.event === "team_run_cancelled" ||
    (event.event === "error" && !event.agent_id)
  );
}

export function phaseForEvent(event: TeamRunEvent) {
  if (
    event.event === "coordinator_started" ||
    event.event === "coordinator_completed"
  )
    return "coordinator";
  if (
    event.event === "coordinator_planning_started" ||
    event.event === "coordinator_planning_completed"
  )
    return "coordinator planning";
  if (event.event === "debate_started" || event.event === "debate_skipped")
    return "debate";
  if (
    event.event === "adaptive_vote" ||
    event.event === "vote_started" ||
    event.event === "agent_vote"
  )
    return "vote";
  if (
    event.event === "blackboard_event" ||
    event.event === "blackboard_snapshot" ||
    event.event === "claim_graph_delta"
  )
    return "blackboard";
  return undefined;
}

export function phaseLabel(phase?: string) {
  if (!phase) return undefined;
  return phase.replace(/_/g, " ");
}

export function toolPhaseLabel(phase: string) {
  return phase.replace(/_/g, " ");
}

export function nextActionForEvent(event: TeamRunEvent) {
  if (event.event === "execution_contract") return "Independent round";
  if (event.event === "round_started")
    return phaseLabel(event.phase) ?? "Agent round";
  if (event.event === "debate_started") return "Debate";
  if (event.event === "debate_skipped") return "Vote or coordinator";
  if (event.event === "adaptive_vote" || event.event === "vote_started")
    return "Vote";
  if (event.event === "coordinator_started") return "Coordinator";
  if (event.event === "team_run_completed") return "Completed";
  if (event.event === "team_consensus_failed") return "Review blockers";
  if (event.event === "team_run_cancelled") return "Cancelled";
  return undefined;
}
