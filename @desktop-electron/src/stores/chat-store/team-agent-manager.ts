import type {
  TeamRunUi,
  TeamRunEvent,
  TeamAgentTraceUi,
  TeamAgentLogUi,
  TeamCompactStatus,
  TeamClaimTraceUi,
  TeamToolTraceUi,
} from "../../types/chat";
import {
  MAX_TEAM_AGENT_LOGS,
  bumpTeamAgentLogSequence,
} from "./internal";

export type TeamAgentPatch = Partial<Omit<TeamAgentTraceUi, "claims" | "tools">> & {
  thinkingAppend?: string;
  outputAppend?: string;
  log?: TeamAgentLogUi;
  logs?: TeamAgentLogUi[];
  claim?: TeamClaimTraceUi;
  claims?: TeamClaimTraceUi[];
  tool?: TeamToolTraceUi;
};

export function upsertTeamAgent(
  run: TeamRunUi,
  event: TeamRunEvent,
  patch: TeamAgentPatch,
  mergeClaims: (existing: TeamClaimTraceUi[], incoming: TeamClaimTraceUi[]) => TeamClaimTraceUi[],
  upsertTeamTool: (tools: TeamToolTraceUi[], tool: TeamToolTraceUi) => TeamToolTraceUi[],
): TeamRunUi {
  const agentId = event.agent_id ?? patch.agentId;
  if (!agentId) return run;
  const existingIndex = run.agents.findIndex((item) => item.agentId === agentId);
  const existing =
    existingIndex >= 0
      ? run.agents[existingIndex]
      : {
          agentId,
          agentName: event.agent_name ?? (patch.isCoordinator ? "Coordinator" : agentId),
          agentRole: event.agent_role,
          status: "idle" as TeamCompactStatus,
          thinking: "",
          output: "",
          logs: [],
          claims: [],
          tools: [],
        };

  const claims = patch.claims
    ? mergeClaims(existing.claims, patch.claims)
    : patch.claim
      ? mergeClaims(existing.claims, [patch.claim])
      : existing.claims;
  const tools = patch.tool ? upsertTeamTool(existing.tools, patch.tool) : existing.tools;
  const logs = mergeAgentLogs(
    existing.logs ?? [],
    patch.logs ?? (patch.log ? [patch.log] : []),
  );
  const nextAgent: TeamAgentTraceUi = {
    ...existing,
    ...patch,
    agentId,
    agentName: event.agent_name ?? patch.agentName ?? existing.agentName,
    agentRole: event.agent_role ?? patch.agentRole ?? existing.agentRole,
    phase: patch.phase ?? event.phase ?? existing.phase,
    round: patch.round ?? event.round ?? existing.round,
    thinking: patch.thinking ?? `${existing.thinking}${patch.thinkingAppend ?? ""}`,
    output: patch.output ?? `${existing.output}${patch.outputAppend ?? ""}`,
    logs,
    claims,
    tools,
  };
  delete (nextAgent as TeamAgentPatch).thinkingAppend;
  delete (nextAgent as TeamAgentPatch).outputAppend;
  delete (nextAgent as TeamAgentPatch).log;
  delete (nextAgent as TeamAgentPatch).claim;
  delete (nextAgent as TeamAgentPatch).tool;

  const agents = [...run.agents];
  if (existingIndex >= 0) agents[existingIndex] = nextAgent;
  else agents.push(nextAgent);
  return { ...run, agents };
}

export function mergeAgentLogs(
  existing: TeamAgentLogUi[],
  incoming: TeamAgentLogUi[],
): TeamAgentLogUi[] {
  if (incoming.length === 0) return existing;
  const logs = [...existing];
  for (const log of incoming) {
    if (isEmptyStreamingAgentLog(log) && !hasOpenStreamingAgentLog(logs, log)) {
      continue;
    }
    const mergeIndex = findMergeableAgentLogIndex(logs, log);
    if (mergeIndex >= 0) {
      const previous = logs[mergeIndex];
      logs[mergeIndex] = {
        ...previous,
        content: `${previous.content ?? ""}${log.content ?? ""}`,
        status: log.status ?? previous.status,
        createdAt: log.createdAt ?? previous.createdAt,
      };
      continue;
    }
    const previous = logs[logs.length - 1];
    if (
      previous &&
      previous.kind === log.kind &&
      previous.title === log.title &&
      previous.content === log.content &&
      previous.status === log.status
    ) {
      continue;
    }
    logs.push(log);
  }
  return logs.slice(-MAX_TEAM_AGENT_LOGS);
}

export function isStreamingAgentTextLog(log: TeamAgentLogUi) {
  return (log.kind === "thinking" || log.kind === "response") && log.status === "running";
}

export function isEmptyStreamingAgentLog(log: TeamAgentLogUi) {
  return isStreamingAgentTextLog(log) && (log.content ?? "").trim().length === 0;
}

export function hasOpenStreamingAgentLog(logs: TeamAgentLogUi[], incoming: TeamAgentLogUi) {
  return findMergeableAgentLogIndex(logs, incoming) >= 0;
}

export function findMergeableAgentLogIndex(
  logs: TeamAgentLogUi[],
  incoming: TeamAgentLogUi,
) {
  if (!isStreamingAgentTextLog(incoming)) return -1;
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const previous = logs[index];
    if (!isSameTeamTurnLog(previous, incoming)) break;
    if (
      previous.kind !== "thinking" &&
      previous.kind !== "response" &&
      previous.kind !== "status"
    ) {
      break;
    }
    if (previous.kind === incoming.kind && previous.status === "running") {
      return index;
    }
  }
  return -1;
}

export function isSameTeamTurnLog(
  previous: TeamAgentLogUi,
  incoming: TeamAgentLogUi,
) {
  return previous.round === incoming.round && previous.phase === incoming.phase;
}

export function teamAgentLogFromEvent(
  event: TeamRunEvent,
  kind: TeamAgentLogUi["kind"],
  title: string,
  content?: string,
  status?: TeamCompactStatus,
  toolId?: string,
): TeamAgentLogUi {
  const seq = bumpTeamAgentLogSequence();
  return {
    id: `${event.run_id ?? "team"}-${event.agent_id ?? "agent"}-${event.event}-${seq}`,
    kind,
    title,
    content,
    status,
    round: event.round,
    phase: event.phase,
    createdAt: event.created_at,
    toolId,
  };
}

export function durationSummary(event: TeamRunEvent) {
  if (event.duration_ms == null && event.first_token_ms == null) return undefined;
  const parts = [];
  if (event.duration_ms != null) parts.push(`${event.duration_ms} ms total`);
  if (event.first_token_ms != null)
    parts.push(`${event.first_token_ms} ms first token`);
  return parts.join(" | ");
}
