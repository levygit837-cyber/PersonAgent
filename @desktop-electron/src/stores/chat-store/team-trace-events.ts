import type {
  ChatMessageUi,
  TeamRunEvent,
  TeamTraceEventUi,
} from "../../types/chat";

export function applyTeamTraceEvent(
  message: ChatMessageUi,
  event: TeamRunEvent,
): ChatMessageUi {
  const events = [...message.teamEvents];
  const upsert = (trace: TeamTraceEventUi) => {
    const index = events.findIndex((item) => item.id === trace.id);
    if (index >= 0) {
      events[index] = { ...events[index], ...trace };
    } else {
      events.push(trace);
    }
  };

  if (event.event === "team_run_started") {
    upsert({
      id: `${event.run_id}-run`,
      kind: "run",
      title: event.team?.name ?? "Team Mode",
      detail: "Run started",
      status: "running",
    });
  }
  if (event.event === "round_started") {
    upsert({
      id: `${event.run_id}-round-${event.round}`,
      kind: "round",
      title: `Round ${event.round}`,
      detail: event.phase,
      status: "running",
      round: event.round,
    });
  }
  if (event.event === "debate_started") {
    upsert({
      id: `${event.run_id}-debate-${event.round}`,
      kind: "debate",
      title: `Debate round ${event.round}`,
      detail: "Blackboard review",
      status: "running",
      round: event.round,
    });
  }
  if (event.event === "agent_turn_started") {
    upsert({
      id: turnTraceId(event),
      kind: "turn",
      title: event.agent_name ?? event.agent_id ?? "Agent",
      detail: event.phase ?? event.agent_role,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "running",
      content: "",
    });
  }
  if (event.event === "agent_delta") {
    const id = turnTraceId(event);
    const existing = events.find((item) => item.id === id);
    const chunk = event.content || "";
    if (!chunk) return { ...message, teamEvents: events };
    upsert({
      id,
      kind: "turn",
      title:
        event.agent_name ?? existing?.title ?? event.agent_id ?? "Agent",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "running",
      content: `${existing?.content ?? ""}${chunk}`,
    });
  }
  if (event.event === "agent_turn_completed") {
    const id = turnTraceId(event);
    const existing = events.find((item) => item.id === id);
    const failed = event.status === "failed";
    upsert({
      id,
      kind: "turn",
      title:
        event.agent_name ?? existing?.title ?? event.agent_id ?? "Agent",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: failed ? "failed" : "completed",
      content: existing?.content || event.content || event.digest,
      detail:
        event.duration_ms != null
          ? `${event.duration_ms} ms`
          : existing?.detail,
    });
  }
  if (event.event === "blackboard_event") {
    const payload = (
      event.payload && typeof event.payload === "object"
        ? event.payload
        : {}
    ) as Record<string, unknown>;
    const summary =
      typeof payload.summary === "string" ? payload.summary : "";
    const blocker =
      typeof payload.blocker === "string" ? payload.blocker : "";
    upsert({
      id: `${event.run_id}-blackboard-${event.sequence ?? events.length}`,
      kind: "blackboard",
      title: `${event.agent_name ?? "Agent"} published`,
      detail:
        `${event.phase ?? "blackboard"} #${event.sequence ?? ""}`.trim(),
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status:
        event.event_type === "agent_blocker" ? "rejected" : "completed",
      content: blocker || summary,
    });
  }
  if (event.event === "blackboard_snapshot") {
    const snapshot = (
      event.snapshot && typeof event.snapshot === "object"
        ? event.snapshot
        : {}
    ) as Record<string, unknown>;
    const entryCount =
      typeof snapshot.entry_count === "number"
        ? snapshot.entry_count
        : undefined;
    const latest =
      typeof snapshot.latest_sequence === "number"
        ? snapshot.latest_sequence
        : undefined;
    upsert({
      id: `${event.run_id}-blackboard-snapshot-${event.round}`,
      kind: "blackboard",
      title: "Blackboard snapshot",
      detail: entryCount != null ? `${entryCount} entries` : undefined,
      round: event.round,
      status: "completed",
      content:
        latest != null ? `Latest sequence: ${latest}` : undefined,
    });
  }
  if (event.event === "execution_contract") {
    const contract = (
      event.contract && typeof event.contract === "object"
        ? event.contract
        : {}
    ) as Record<string, unknown>;
    const objective =
      typeof contract.objective === "string"
        ? contract.objective
        : undefined;
    const coverage = Array.isArray(contract.coverage_matrix)
      ? contract.coverage_matrix.length
      : undefined;
    upsert({
      id: `${event.run_id}-execution-contract`,
      kind: "coordinator",
      title: "Execution contract",
      detail:
        coverage != null ? `${coverage} coverage items` : undefined,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: "completed",
      content: objective,
    });
  }
  if (event.event === "claim_graph_delta") {
    const delta = (
      event.delta && typeof event.delta === "object" ? event.delta : {}
    ) as Record<string, unknown>;
    const nodeCount =
      typeof delta.node_count === "number"
        ? delta.node_count
        : undefined;
    const duplicates = Array.isArray(delta.duplicates)
      ? delta.duplicates.length
      : 0;
    upsert({
      id: `${event.run_id}-claim-delta-${event.sequence ?? events.length}`,
      kind: "blackboard",
      title: "Claim graph delta",
      detail: nodeCount != null ? `${nodeCount} nodes` : undefined,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: duplicates > 0 ? "rejected" : "completed",
      content:
        duplicates > 0
          ? `${duplicates} duplicate claim${duplicates === 1 ? "" : "s"} collapsed`
          : undefined,
    });
  }
  if (event.event === "coverage_matrix") {
    const done = event.coverage_complete ?? 0;
    const total =
      event.coverage_total ?? event.coverage_matrix?.length ?? 0;
    upsert({
      id: `${event.run_id}-coverage-${event.round}`,
      kind: "blackboard",
      title: "Coverage matrix",
      detail: `${done}/${total} covered`,
      round: event.round,
      status: total > 0 && done >= total ? "completed" : "running",
    });
  }
  if (event.event === "coherency_score") {
    upsert({
      id: `${event.run_id}-coherency-${event.round}-${event.agent_id}`,
      kind: "blackboard",
      title: `${event.agent_name ?? "Agent"} coherency`,
      detail:
        event.coherency_score != null
          ? `${Math.round(event.coherency_score * 100)}%`
          : undefined,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status:
        (event.coherency_score ?? 1) < 0.45 ? "rejected" : "completed",
    });
  }
  if (event.event === "tool_phase") {
    const proposalCount = event.proposals?.length ?? 0;
    const resultCount = event.results?.length ?? 0;
    upsert({
      id: `${event.run_id}-tool-${event.round}-${event.agent_id}-${event.tool_phase}`,
      kind: "tool",
      title: `${event.agent_name ?? "Agent"} tools`,
      detail: event.tool_phase,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: proposalCount > 0 ? "rejected" : "completed",
      content:
        proposalCount > 0
          ? `${proposalCount} proposal${proposalCount === 1 ? "" : "s"} waiting for coordination`
          : resultCount > 0
            ? `${resultCount} result${resultCount === 1 ? "" : "s"} published`
            : undefined,
    });
  }
  if (event.event === "debate_skipped") {
    upsert({
      id: `${event.run_id}-debate-skipped-${event.round}`,
      kind: "coordinator",
      title: `Debate skipped round ${event.round}`,
      detail: event.reason,
      round: event.round,
      status: "completed",
      content:
        event.coverage_complete != null && event.coverage_total != null
          ? `${event.coverage_complete}/${event.coverage_total} covered`
          : undefined,
    });
  }
  if (event.event === "adaptive_vote") {
    upsert({
      id: `${event.run_id}-adaptive-vote-${event.round}`,
      kind: "vote",
      title: `Adaptive vote round ${event.round}`,
      detail: event.triggers?.join(", "),
      round: event.round,
      status: "running",
    });
  }
  if (event.event === "vote_started") {
    upsert({
      id: `${event.run_id}-vote-${event.round}`,
      kind: "vote",
      title: `Vote after round ${event.round}`,
      round: event.round,
      status: "running",
    });
  }
  if (event.event === "agent_vote") {
    events.push({
      id: `${event.run_id}-vote-${event.round}-${event.agent_id}`,
      kind: "vote",
      title: `${event.agent_name ?? "Agent"} ${event.approve ? "approved" : "blocked"}`,
      detail:
        event.blocker ||
        event.final_points ||
        `${Math.round((event.confidence ?? 0) * 100)}% confidence`,
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      status: event.approve ? "approved" : "rejected",
    });
  }
  if (event.event === "consensus_reached") {
    upsert({
      id: `${event.run_id}-consensus`,
      kind: "consensus",
      title: "Consensus reached",
      detail: `${event.consensus?.approvals ?? 0}/${event.consensus?.required ?? 0} approvals`,
      status: "completed",
    });
  }
  if (event.event === "coordinator_planning_started") {
    upsert({
      id: `${event.run_id}-coordinator-planning-${event.round}`,
      kind: "coordinator",
      title: `${event.agent_name ?? "Coordinator"} planning`,
      detail: "Debate focus",
      status: "running",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
  if (event.event === "coordinator_planning_completed") {
    const guidance = (
      event.guidance && typeof event.guidance === "object"
        ? event.guidance
        : {}
    ) as Record<string, unknown>;
    const summary =
      typeof guidance.summary === "string"
        ? guidance.summary
        : undefined;
    upsert({
      id: `${event.run_id}-coordinator-planning-${event.round}`,
      kind: "coordinator",
      title: `${event.agent_name ?? "Coordinator"} planning`,
      detail:
        event.duration_ms != null
          ? `${event.duration_ms} ms`
          : "Focus assigned",
      status: "completed",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
      content: summary,
    });
  }
  if (event.event === "coordinator_redirect") {
    upsert({
      id: `${event.run_id}-redirect-${event.round}-${event.agent_id}`,
      kind: "coordinator",
      title: "Coordinator redirect",
      detail: event.agent_id,
      round: event.round,
      agentId: event.agent_id,
      status: "completed",
      content: event.redirect,
    });
  }
  if (event.event === "coordinator_started") {
    upsert({
      id: `${event.run_id}-coordinator`,
      kind: "coordinator",
      title: event.agent_name ?? "Coordinator",
      detail: "Final synthesis",
      status: "running",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
  if (event.event === "coordinator_completed") {
    upsert({
      id: `${event.run_id}-coordinator`,
      kind: "coordinator",
      title: event.agent_name ?? "Coordinator",
      detail:
        event.duration_ms != null
          ? `${event.duration_ms} ms`
          : "Final report ready",
      status: "completed",
      round: event.round,
      agentId: event.agent_id,
      agentName: event.agent_name,
    });
  }
  if (event.event === "team_consensus_failed") {
    upsert({
      id: `${event.run_id}-failed`,
      kind: "failed",
      title: "Consensus failed",
      detail: event.reason,
      status: "failed",
    });
  }
  if (event.event === "team_run_cancelled") {
    upsert({
      id: `${event.run_id}-cancelled`,
      kind: "cancelled",
      title: "Team run cancelled",
      status: "cancelled",
    });
  }
  if (event.event === "team_run_completed") {
    upsert({
      id: `${event.run_id}-run`,
      kind: "run",
      title: "Team Mode",
      detail: "Run completed",
      status: "completed",
    });
  }

  return { ...message, teamEvents: events };
}

export function turnTraceId(event: TeamRunEvent) {
  return `${event.run_id}-round-${event.round}-${event.agent_id}`;
}
