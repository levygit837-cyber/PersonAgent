import {
  type ChatMessageUi,
  type TeamAgentLogUi,
  type TeamRunEvent,
} from "../../types/chat";
import type { ChatState } from "./internal";
import {
  setConversationStatus,
  resetLiveTokenTotals,
} from "./internal";
import {
  isRecord,
  stringValue,
  closeActiveReasoning,
  flushTextBuffer,
  queueTextChunk,
  applyLiveTokenUsage,
} from "./chunk-handlers";
import {
  createTeamRun,
  cloneTeamRun,
  seedTeamAgents,
  runStatusForEvent,
  blackboardStatusForEvent,
  isTerminalTeamEvent,
  phaseForEvent,
  phaseLabel,
  nextActionForEvent,
} from "./team-run-lifecycle";
import {
  upsertTeamAgent,
  teamAgentLogFromEvent,
  durationSummary,
} from "./team-agent-manager";
import {
  upsertTeamTool,
  toolTraceFromEvent,
  updateBlackboardFromSnapshot,
  updateBlackboardFromContract,
  updateBlackboardFromCoherency,
  updateBlackboardFromCoherencyObject,
  blackboardClaimFromEvent,
  claimsFromDelta,
  mergeClaims,
  coverageFromValue,
  upsertTeamVote,
  blockerTextFromEvent,
  decisionTextFromEvent,
  mergeTextItems,
} from "./team-blackboard-manager";
import { applyTeamTraceEvent } from "./team-trace-events";

type SetFn = (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void;

export function handleTeamEvent(
  event: TeamRunEvent,
  agentId: string,
  set: SetFn,
  get: () => ChatState,
) {
  if (!isActiveTeamEventTarget(get(), agentId)) return;

  if (event.error && event.event !== "error") {
    flushTextBuffer(agentId, set);
    set({
      error: event.error,
      messages: get().messages.map((item) => (item.id === agentId ? closeActiveReasoning(item, false) : item)),
    });
    setConversationStatus(set, event.conversation_id ?? get().conversationId, "error");
    return;
  }

  if (event.conversation_id) {
    set({ conversationId: event.conversation_id });
    setConversationStatus(set, event.conversation_id, "running");
  }

  if (event.event === "agent_turn_started" && event.agent_id) {
    set((state) => {
      if (state.liveSubAgentIds.includes(String(event.agent_id))) return {};
      const ids = [...state.liveSubAgentIds, String(event.agent_id)];
      return {
        liveSubAgentIds: ids,
        liveSessionUsage: {
          ...state.liveSessionUsage,
          subagents_used: { value: ids.length, estimated: false },
        },
      };
    });
  }

  if (event.event === "agent_delta") {
    queueTeamDeltaEvent(agentId, event, set);
    return;
  }

  if (event.event === "final_delta") {
    applyLiveTokenUsage(
      {
        content: event.content,
        reasoning_content: event.reasoning_content,
      },
      set,
    );
    queueTextChunk(
      agentId,
      {
        content: event.content,
        reasoning_content: event.reasoning_content,
      },
      set,
    );
    return;
  }

  flushTextBuffer(agentId, set);

  if (event.event === "team_run_completed") {
    resetLiveTokenTotals();
    setConversationStatus(set, event.conversation_id ?? get().conversationId, "idle");
    window.dispatchEvent(new CustomEvent("personagent:conversations-changed"));
    window.dispatchEvent(new CustomEvent("personagent:session-panel-changed"));
  } else if (event.event === "team_consensus_failed" || event.event === "team_run_cancelled" || (event.event === "error" && !event.agent_id)) {
    setConversationStatus(set, event.conversation_id ?? get().conversationId, "error");
  }

  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      return applyTeamEventToMessage(item, event);
    }),
    isStreaming: !isTerminalTeamEvent(event),
    error: event.event === "error" && !event.agent_id ? event.error_detail?.message ?? event.error : state.error,
  }));
}

function queueTeamDeltaEvent(
  agentId: string,
  event: TeamRunEvent,
  set: SetFn,
) {
  set((state) => ({
    messages: state.messages.map((item) => {
      if (item.id !== agentId) return item;
      return applyTeamEventToMessage(item, event);
    }),
  }));
}

function applyTeamEventToMessage(message: ChatMessageUi, event: TeamRunEvent): ChatMessageUi {
  let next = shouldResetTeamMessageForRun(message, event)
    ? {
        ...message,
        teamRun: undefined,
        teamEvents: [],
      }
    : message;
  if (event.content || event.event !== "agent_delta") {
    next = closeActiveReasoning(next, true);
  }
  next = applyTeamRunEvent(next, event);
  next = applyTeamTraceEvent(next, event);
  const isTerminal = isTerminalTeamEvent(event);
  return {
    ...next,
    label: "Team Mode",
    isStreaming: !isTerminal,
    isReasoningStreaming: false,
  };
}

function isActiveTeamEventTarget(state: ChatState, agentId: string) {
  if (state.activeAgentId === agentId) return true;
  return state.messages.some((message) => message.id === agentId && message.isStreaming);
}

function shouldResetTeamMessageForRun(message: ChatMessageUi, event: TeamRunEvent) {
  if (event.event !== "team_run_started" || !event.run_id || !message.teamRun) return false;
  return !message.teamRun.runId || message.teamRun.runId !== event.run_id;
}



function applyTeamRunEvent(message: ChatMessageUi, event: TeamRunEvent): ChatMessageUi {
  let run = message.teamRun ? cloneTeamRun(message.teamRun) : createTeamRun(event);
  run = seedTeamAgents(run, event);

  run.runId = event.run_id ?? run.runId;
  run.title = event.team?.name ?? run.title;
  run.status = runStatusForEvent(event, run.status);
  run.round = event.round ?? run.round;
  run.actualPhase = phaseLabel(event.phase) ?? phaseForEvent(event) ?? run.actualPhase;
  run.startedAt = event.started_at ?? run.startedAt;
  run.completedAt = event.completed_at ?? run.completedAt;
  run.blackboard = {
    ...run.blackboard,
    status: blackboardStatusForEvent(event, run.status, run.blackboard.status),
    actualPhase: run.actualPhase ?? run.blackboard.actualPhase,
    nextAction: nextActionForEvent(event) ?? run.blackboard.nextAction,
    updatedAt: event.created_at ?? new Date().toISOString(),
  };

  if (event.event === "agent_turn_started") {
    run = upsertTeamAgent(run, event, {
      status: "running",
      phase: event.phase,
      round: event.round,
      error: undefined,
      log: teamAgentLogFromEvent(event, "status", `Started ${phaseLabel(event.phase) ?? "turn"}`, undefined, "running"),
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "agent_delta") {
    const logs = [
      event.reasoning_content !== undefined
        ? teamAgentLogFromEvent(event, "thinking", "Thinking", event.reasoning_content, "running")
        : undefined,
      event.content !== undefined ? teamAgentLogFromEvent(event, "response", "Output", event.content, "running") : undefined,
    ].filter((log): log is TeamAgentLogUi => Boolean(log));
    run = upsertTeamAgent(run, event, {
      status: "running",
      phase: event.phase,
      round: event.round,
      thinkingAppend: event.reasoning_content,
      outputAppend: event.content,
      logs,
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "agent_turn_completed") {
    run = upsertTeamAgent(run, event, {
      status: event.status === "failed" || event.blocker ? "failed" : "completed",
      phase: event.phase,
      round: event.round,
      thinking: event.reasoning_content,
      output: event.content,
      digest: event.digest,
      durationMs: event.duration_ms,
      firstTokenMs: event.first_token_ms,
      coherencyScore: event.coherency_score,
      error: event.blocker,
      log: teamAgentLogFromEvent(
        event,
        event.status === "failed" || event.blocker ? "error" : "status",
        event.status === "failed" || event.blocker ? "Failed" : "Completed",
        event.digest || event.blocker || durationSummary(event),
        event.status === "failed" || event.blocker ? "failed" : "completed",
      ),
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "error" && event.agent_id) {
    run = upsertTeamAgent(run, event, {
      status: "failed",
      phase: event.phase,
      round: event.round,
      error: event.error ?? "Agent failed",
      log: teamAgentLogFromEvent(event, "error", "Error", event.error ?? "Agent failed", "failed"),
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "coordinator_started" || event.event === "coordinator_planning_started") {
    run = upsertTeamAgent(run, event, {
      status: "running",
      phase: event.phase ?? "coordinator",
      round: event.round,
      isCoordinator: true,
      log: teamAgentLogFromEvent(event, "status", "Coordinator started", undefined, "running"),
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "coordinator_completed" || event.event === "coordinator_planning_completed") {
    const guidance = isRecord(event.guidance) ? event.guidance : {};
    run = upsertTeamAgent(run, event, {
      status: "completed",
      phase: event.phase ?? "coordinator",
      round: event.round,
      output: stringValue(guidance.summary) ?? "",
      durationMs: event.duration_ms,
      isCoordinator: true,
      log: teamAgentLogFromEvent(
        event,
        "status",
        "Coordinator completed",
        stringValue(guidance.summary) ?? durationSummary(event),
        "completed",
      ),
    }, mergeClaims, upsertTeamTool);
  }

  if (event.event === "coherency_score") {
    run = upsertTeamAgent(run, event, {
      phase: event.phase,
      round: event.round,
      coherencyScore: event.coherency_score,
    }, mergeClaims, upsertTeamTool);
    run.blackboard = updateBlackboardFromCoherency(run.blackboard, event);
  }

  if (event.event === "tool_phase") {
    const tool = toolTraceFromEvent(event);
    if (event.agent_id) {
      run = upsertTeamAgent(run, event, {
        phase: event.phase,
        round: event.round,
        tool,
        log: teamAgentLogFromEvent(event, "tool", tool.title, tool.summary, tool.status, tool.id),
      }, mergeClaims, upsertTeamTool);
    } else {
      run.blackboard = { ...run.blackboard, tools: upsertTeamTool(run.blackboard.tools, tool) };
    }
  }

  if (event.event === "execution_contract") {
    run.blackboard = updateBlackboardFromContract(run.blackboard, event);
  }

  if (event.event === "blackboard_event") {
    const claim = blackboardClaimFromEvent(event);
    run.blackboard = {
      ...run.blackboard,
      claims: claim ? mergeClaims(run.blackboard.claims, [claim]) : run.blackboard.claims,
      blockers: mergeTextItems(run.blackboard.blockers, blockerTextFromEvent(event)),
      decisions: mergeTextItems(run.blackboard.decisions, decisionTextFromEvent(event)),
    };
    if (claim && event.agent_id) {
      run = upsertTeamAgent(run, event, {
        claim,
        log: teamAgentLogFromEvent(event, "claim", claim.type, claim.text, "completed"),
      }, mergeClaims, upsertTeamTool);
    }
  }

  if (event.event === "claim_graph_delta") {
    const claims = claimsFromDelta(event.delta);
    run.blackboard = {
      ...run.blackboard,
      claims: mergeClaims(run.blackboard.claims, claims),
      coverage: coverageFromValue(isRecord(event.delta) ? event.delta.coverage_matrix : undefined) ?? run.blackboard.coverage,
    };
    if (event.agent_id && claims.length > 0) {
      const ownClaims = claims.filter((claim) => !claim.agentId || claim.agentId === event.agent_id);
      run = upsertTeamAgent(run, event, {
        claims: ownClaims,
        log: ownClaims[0]
          ? teamAgentLogFromEvent(event, "claim", ownClaims[0].type, ownClaims[0].text, "completed")
          : undefined,
      }, mergeClaims, upsertTeamTool);
    }
    run.blackboard = updateBlackboardFromCoherencyObject(
      run.blackboard,
      isRecord(event.delta) ? event.delta.coherency : undefined,
    );
  }

  if (event.event === "blackboard_snapshot") {
    run.blackboard = updateBlackboardFromSnapshot(run.blackboard, event);
  }

  if (event.event === "coverage_matrix") {
    run.blackboard = {
      ...run.blackboard,
      coverage: coverageFromValue(event.coverage_matrix) ?? run.blackboard.coverage,
      coverageComplete: event.coverage_complete,
      coverageTotal: event.coverage_total ?? event.coverage_matrix?.length,
    };
  }

  if (event.event === "agent_vote") {
    run.votes = upsertTeamVote(run.votes, event);
  }

  return { ...message, teamRun: run };
}














