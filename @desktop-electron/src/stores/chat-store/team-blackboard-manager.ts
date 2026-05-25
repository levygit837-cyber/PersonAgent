import type {
  TeamBlackboardTraceUi,
  TeamRunEvent,
  TeamClaimTraceUi,
  TeamCoverageTraceUi,
  TeamTraceEventUi,
  TeamToolTraceUi,
} from "../../types/chat";
import { numberValue } from "./internal";
import { isRecord, stringValue } from "./chunk-handlers";
import { toolPhaseLabel } from "./team-run-lifecycle";

export function upsertTeamTool(
  tools: TeamToolTraceUi[],
  tool: TeamToolTraceUi,
): TeamToolTraceUi[] {
  const index = tools.findIndex((item) => item.id === tool.id);
  if (index < 0) return [...tools, tool];
  const next = [...tools];
  next[index] = {
    ...next[index],
    ...tool,
    calls: tool.calls.length > 0 ? tool.calls : next[index].calls,
    results: tool.results.length > 0 ? tool.results : next[index].results,
    proposals:
      tool.proposals.length > 0
        ? tool.proposals
        : next[index].proposals,
  };
  return next;
}

export function toolTraceFromEvent(event: TeamRunEvent): TeamToolTraceUi {
  const proposalCount = event.proposals?.length ?? 0;
  const resultCount = event.results?.length ?? 0;
  const callCount = event.calls?.length ?? 0;
  const phase = event.tool_phase ?? event.phase ?? "tools";
  return {
    id: `${event.run_id ?? "team"}-tool-${event.round ?? "x"}-${event.agent_id ?? "blackboard"}-${phase}`,
    phase,
    title: toolPhaseLabel(phase),
    status:
      proposalCount > 0
        ? "blocked"
        : resultCount > 0
          ? "completed"
          : callCount > 0
            ? "running"
            : "completed",
    summary:
      proposalCount > 0
        ? `${proposalCount} proposal${proposalCount === 1 ? "" : "s"} waiting for coordination`
        : resultCount > 0
          ? `${resultCount} result${resultCount === 1 ? "" : "s"} published`
          : callCount > 0
            ? `${callCount} call${callCount === 1 ? "" : "s"} running`
            : undefined,
    calls: event.calls ?? [],
    results: event.results ?? [],
    proposals: event.proposals ?? [],
    createdAt: event.created_at,
  };
}

export function updateBlackboardFromSnapshot(
  blackboard: TeamBlackboardTraceUi,
  event: TeamRunEvent,
): TeamBlackboardTraceUi {
  const snapshot = isRecord(event.snapshot) ? event.snapshot : {};
  const claimGraph = isRecord(snapshot.claim_graph)
    ? snapshot.claim_graph
    : {};
  const coherency = isRecord(snapshot.coherency)
    ? snapshot.coherency
    : undefined;
  return updateBlackboardFromCoherencyObject(
    {
      ...blackboard,
      snapshot,
      entryCount:
        numberValue(snapshot.entry_count) ?? blackboard.entryCount,
      latestSequence:
        numberValue(snapshot.latest_sequence) ??
        blackboard.latestSequence,
      claims: mergeClaims(
        blackboard.claims,
        claimsFromValue(claimGraph.nodes),
      ),
      evidence: mergeTextItems(
        blackboard.evidence,
        textListFromValue(snapshot.evidence),
      ),
      decisions: mergeTextItems(
        blackboard.decisions,
        textListFromValue(snapshot.decisions),
      ),
      blockers: mergeTextItems(
        blackboard.blockers,
        blockerListFromValue(snapshot.blockers),
      ),
      coverage:
        coverageFromValue(snapshot.coverage_matrix) ??
        blackboard.coverage,
    },
    coherency,
  );
}

export function updateBlackboardFromContract(
  blackboard: TeamBlackboardTraceUi,
  event: TeamRunEvent,
): TeamBlackboardTraceUi {
  const contract = isRecord(event.contract) ? event.contract : {};
  const coverage = coverageFromValue(contract.coverage_matrix);
  const objective = stringValue(contract.objective);
  return {
    ...blackboard,
    claims: objective
      ? mergeClaims(blackboard.claims, [
          {
            id: `${event.run_id ?? "team"}-execution-contract`,
            type: "objective",
            text: objective,
            agentId: event.agent_id,
            agentName: event.agent_name ?? "Coordinator",
            status: "active",
          },
        ])
      : blackboard.claims,
    coverage: coverage ?? blackboard.coverage,
    nextAction: "Independent round",
  };
}

export function updateBlackboardFromCoherency(
  blackboard: TeamBlackboardTraceUi,
  event: TeamRunEvent,
): TeamBlackboardTraceUi {
  return updateBlackboardFromCoherencyObject(
    blackboard,
    event.coherency ?? { average: event.coherency_score },
  );
}

export function updateBlackboardFromCoherencyObject(
  blackboard: TeamBlackboardTraceUi,
  coherency: unknown,
): TeamBlackboardTraceUi {
  if (!isRecord(coherency)) return blackboard;
  return {
    ...blackboard,
    coherencyScore:
      numberValue(coherency.average) ?? blackboard.coherencyScore,
    lowCoherencyCount:
      numberValue(coherency.low_count) ?? blackboard.lowCoherencyCount,
  };
}

export function blackboardClaimFromEvent(
  event: TeamRunEvent,
): TeamClaimTraceUi | undefined {
  const payload = isRecord(event.payload) ? event.payload : {};
  const text =
    stringValue(payload.summary) ??
    stringValue(payload.blocker) ??
    stringValue(payload.objective) ??
    stringValue(payload.decision);
  if (!text) return undefined;
  return {
    id: `${event.run_id ?? "team"}-blackboard-${event.sequence ?? event.created_at ?? text}`,
    type: event.event_type ?? (payload.blocker ? "blocker" : "claim"),
    text,
    agentId: event.agent_id,
    agentName: event.agent_name,
    status: "active",
  };
}

export function claimsFromDelta(delta: unknown): TeamClaimTraceUi[] {
  if (!isRecord(delta)) return [];
  return claimsFromValue(delta.nodes);
}

export function claimsFromValue(value: unknown): TeamClaimTraceUi[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((node, index) => ({
      id: stringValue(node.id) ?? `claim-${index}`,
      type: stringValue(node.type) ?? "claim",
      text:
        stringValue(node.text) ?? stringValue(node.summary) ?? "",
      agentId: stringValue(node.agent_id),
      agentName: stringValue(node.agent_name),
      status: stringValue(node.status),
      confidence: numberValue(node.confidence),
      coherencyScore: numberValue(node.coherency_score),
      noveltyScore: numberValue(node.novelty_score),
    }))
    .filter((claim) => claim.text.trim().length > 0);
}

export function mergeClaims(
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

export function coverageFromValue(
  value: unknown,
): TeamCoverageTraceUi[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value
    .filter(isRecord)
    .map((item, index) => ({
      id: stringValue(item.id) ?? `coverage-${index}`,
      title:
        stringValue(item.question) ??
        stringValue(item.expected_output) ??
        stringValue(item.id) ??
        `Coverage ${index + 1}`,
      detail:
        stringValue(item.status) ??
        stringValue(item.owner_agent_id) ??
        stringValue(item.owner),
      ownerAgentId:
        stringValue(item.owner_agent_id) ??
        stringValue(item.owner),
      status: stringValue(item.status),
    }));
}

export function upsertTeamVote(
  votes: TeamTraceEventUi[],
  event: TeamRunEvent,
): TeamTraceEventUi[] {
  const vote: TeamTraceEventUi = {
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
  };
  const index = votes.findIndex((item) => item.id === vote.id);
  if (index < 0) return [...votes, vote];
  const next = [...votes];
  next[index] = vote;
  return next;
}

export function blockerTextFromEvent(event: TeamRunEvent): string[] {
  const payload = isRecord(event.payload) ? event.payload : {};
  const blocker =
    stringValue(payload.blocker) ?? stringValue(event.blocker);
  return blocker ? [blocker] : [];
}

export function decisionTextFromEvent(event: TeamRunEvent): string[] {
  const payload = isRecord(event.payload) ? event.payload : {};
  const decision = stringValue(payload.decision);
  return decision ? [decision] : [];
}

export function blockerListFromValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (!isRecord(item)) return "";
      const payload = isRecord(item.payload)
        ? item.payload
        : {};
      return (
        stringValue(payload.blocker) ??
        stringValue(payload.summary) ??
        stringValue(item.title) ??
        ""
      );
    })
    .filter((item) => item.trim().length > 0);
}

export function textListFromValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (!isRecord(item)) return "";
      return (
        stringValue(item.text) ??
        stringValue(item.summary) ??
        ""
      );
    })
    .filter((item) => item.trim().length > 0);
}

export function mergeTextItems(
  existing: string[],
  incoming: string[],
): string[] {
  if (incoming.length === 0) return existing;
  return Array.from(new Set([...existing, ...incoming])).slice(-16);
}
